# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-E6 correction: the reveal-delegation routes enforce their operation-specific authority at `finalize`.

Luna's finding: `access.manage` is the only requirement `plan.finalize` judged; the live built-in owner (both routes)
and the recipient's live built-in `gm` eligibility (the grant) were plain reads before it, so an assignment that
lapsed between the early reads and the final instant did not stop the request while another role still supplied
`access.manage`. The correction registers `owner_requirement` (both routes) and `recipient_requirement` (the grant)
before `finalize`; both are judged from the one authority snapshot read at the final fresh instant.

Synchronization (deterministic, after the early liveness reads and before the final authorization): a request is
parked twice. Gate A is its first role lock: nothing is locked yet, so the test may change the row, and the expiry is
set to the **database clock** `clock_timestamp() + 6 s` *after* the request has entered. Gate B is the final statement
(`finalize`'s one read): every early read and lock is behind the request, which is parked holding its locks. The test
asserts from the database clock that the expiry has not yet passed (so the early reads judged the row live), waits on
the database clock until it has, and releases. Where the held locks forbid a change (the grantee's membership row,
the owner and `gm` rows), the test demonstrates the serialization instead (the competitor is observed blocked by the
parked request's backend, and applies after it commits).
"""

import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands import reveal_delegation_plans as plans
from dnd_ai.commands.memberships import CampaignOwnerRequiredError
from dnd_ai.domain.access import (
    AuthoritySnapshot,
    find_live_builtin_gm_assignment,
    read_authority_snapshot,
)
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures used by name
    FINAL,
    idle_in_transaction,
    pooled,
    pooled_factory,
)
from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixtures used by name
    World,
    code,
    error_of,
    w,
)
from tests.database.test_r01_s5e2_membership_routes import (  # noqa: F401 - fixtures used by name
    pooled2,
    pooled2_factory,
    waiting_statement,
)
from tests.database.test_r01_s5e6_reveal_delegation_routes import (  # noqa: F401 - fixtures used by name
    D,
    Factory,
    _tidy,
    audits,
    d,
    delegations,
    grant,
    lapse_gm_row_keeping_delegation,
    live,
    revoke,
    snapshot,
)
from tests.factories import (
    make_campaign_membership,
    make_membership_role,
    make_role,
    make_role_capability,
    make_user,
    system_role_id,
)
from tests.http_race_support import StatementGate, run_in_thread
from tests.lock_race_support import LockRace

pytestmark = pytest.mark.database

#: The first role-class lock of either route (the owner row `FOR SHARE` or the `gm` row `FOR UPDATE`): nothing of
#: the request is locked when it is parked here.
FIRST_ROLE_LOCK = (
    r"FROM security\.membership_roles WHERE security\.membership_roles\.membership_role_id = "
    r"%\(row\)s::UUID AND .* FOR (SHARE|UPDATE)$"
)
OWNER_LOCK = FIRST_ROLE_LOCK
WINDOW_SECONDS = 6


# --- helpers ---------------------------------------------------------------------------------------------------------


def db_clock(engine: Engine) -> Any:
    with engine.connect() as c:
        return c.execute(text("SELECT clock_timestamp()")).scalar_one()


def expire_from_the_database_clock(d: D, role: uuid.UUID) -> Any:
    """Sets the assignment's expiry to the database clock plus `WINDOW_SECONDS`; returns the expiry."""
    with d.w.engine.begin() as c:
        return c.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = clock_timestamp() + "
                "make_interval(secs => :s) WHERE membership_role_id = :r RETURNING expires_at"
            ),
            {"s": WINDOW_SECONDS, "r": role},
        ).scalar_one()


def wait_past(d: D, instant: Any) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if db_clock(d.w.engine) >= instant:
            return
        time.sleep(0.05)
    raise AssertionError("the database clock did not pass the expiry")


def give_custom_access_manage(d: D, membership: uuid.UUID) -> None:
    """A second source of `access.manage` for `membership`: a custom (non-owner) role."""
    with d.w.engine.begin() as c:
        capability = c.execute(
            text("SELECT capability_id FROM security.capabilities WHERE code = 'access.manage'")
        ).scalar_one()
        role = make_role(c, campaign_id=d.w.campaign_id)
        make_role_capability(c, role, capability)
        make_membership_role(c, membership, role)


def parked_request(
    d: D,
    pooled: Engine,
    call: Callable[[], Any],
    *,
    lapse_role: uuid.UUID | None,
    at_final: Callable[[], None] | None = None,
) -> Any:
    """Runs `call`, parked at gate A (the first role lock) where `lapse_role` gets its database-clock expiry, then at
    gate B (the final statement) where `at_final` runs and the expiry is waited out; returns the response."""
    with (
        StatementGate(pooled, FIRST_ROLE_LOCK) as gate_a,
        StatementGate(pooled, FINAL) as gate_b,
    ):
        request = run_in_thread("request", call)
        gate_a.wait_reached()
        expiry = expire_from_the_database_clock(d, lapse_role) if lapse_role else None
        gate_a.release()
        gate_b.wait_reached()
        if expiry is not None:
            assert db_clock(d.w.engine) < expiry, (
                "the early reads ran after the expiry: window missed"
            )
        if at_final is not None:
            at_final()
        if expiry is not None:
            wait_past(d, expiry)
        gate_b.release()
        return request.wait("the request finishes")


# --- the owner, at the final instant ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "branch", ("grant-fresh", "grant-existing", "grant-stale", "revoke-live", "revoke-none")
)
def test_an_owner_whose_assignment_lapses_before_finalize_is_refused_though_another_role_supplies_access_manage(
    branch: str, d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*boundary*, both routes and every branch (fresh grant, the existing no-op, the stale replacement, the live
    revoke, the revoke no-op): A is a built-in owner AND holds a custom `access.manage` role. A's owner row lapses
    (database clock) between the early reads, which judged it live, and `finalize`. The route requirement still holds
    (the other role), so only the operation's own requirement can refuse: 403 `campaign_owner_required`, no
    delegation, no closure, no audit row; the connection is clean and the next request (owner B) succeeds."""
    give_custom_access_manage(d, d.a_membership)
    if branch == "grant-existing":
        assert code(grant(pooled_factory, d, actor=d.b_user)) == 200
    elif branch == "grant-stale":
        assert code(grant(pooled_factory, d, actor=d.b_user)) == 200
        lapse_gm_row_keeping_delegation(d, d.x_membership, d.x_role)
    elif branch == "revoke-live":
        assert code(grant(pooled_factory, d, actor=d.b_user)) == 200
    is_grant = branch.startswith("grant")
    before = snapshot(d)
    response = parked_request(
        d,
        pooled,
        (lambda: grant(pooled_factory, d)) if is_grant else (lambda: revoke(pooled_factory, d)),
        lapse_role=d.a_role,
    )
    assert code(response) == 403 and error_of(response) == "campaign_owner_required", response.text
    assert snapshot(d) == before, "a refusal at the final instant writes nothing"
    assert idle_in_transaction(d.w.engine) == 0
    # the other role still supplies access.manage: the route requirement alone would have admitted A
    with d.w.engine.connect() as c:
        final = read_authority_snapshot(
            c, user_id=d.a_user, campaign_id=d.w.campaign_id, with_reveal=True
        )
    assert final.access is not None and "access.manage" in final.access.role_capabilities
    assert final.reveal_authority != "owner"
    # clean pooled reuse: the next request on the same one-connection pool is served
    if is_grant:
        assert code(grant(pooled_factory, d, actor=d.b_user, grantee=d.y_membership)) == 200
    else:
        assert code(revoke(pooled_factory, d, actor=d.b_user)) == 200


@pytest.mark.parametrize("route", ("grant", "revoke"))
def test_the_owner_control_without_a_lapse_succeeds_through_the_same_gates(
    route: str, d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*control*: the identical schedule with no lapse (the same two gates) succeeds, so the refusals above come from
    the lapse and not from the gates."""
    give_custom_access_manage(d, d.a_membership)
    if route == "revoke":
        assert code(grant(pooled_factory, d, actor=d.b_user)) == 200
    call = (
        (lambda: grant(pooled_factory, d))
        if route == "grant"
        else (lambda: revoke(pooled_factory, d))
    )
    response = parked_request(d, pooled, call, lapse_role=None)
    assert code(response) == 200, response.text
    assert len(audits(d)) == (1 if route == "grant" else 2)


# --- the recipient, at the final instant -----------------------------------------------------------------------------


@pytest.mark.parametrize("branch", ("fresh", "existing", "stale"))
def test_a_recipient_whose_gm_assignment_lapses_before_finalize_is_refused_not_gm(
    branch: str, d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*boundary*, every grant branch: the grantee's `gm` row lapses (database clock) between the early reads and
    `finalize`. The caller is still a live owner, so only the recipient requirement can refuse: 409
    `reveal_delegation_recipient_not_gm`; for the existing delegation and the stale replacement too (the no-op and
    the closure never run); nothing is written."""
    gm_row = d.x_role
    if branch == "existing":
        assert code(grant(pooled_factory, d)) == 200
    elif branch == "stale":
        assert code(grant(pooled_factory, d)) == 200
        gm_row = lapse_gm_row_keeping_delegation(d, d.x_membership, d.x_role)
    before = snapshot(d)
    response = parked_request(d, pooled, lambda: grant(pooled_factory, d), lapse_role=gm_row)
    assert code(response) == 409 and error_of(response) == "reveal_delegation_recipient_not_gm", (
        response.text
    )
    assert snapshot(d) == before
    assert idle_in_transaction(d.w.engine) == 0
    assert code(grant(pooled_factory, d, grantee=d.y_membership)) == 200  # clean pooled reuse


def test_a_recipient_account_deactivated_after_the_early_reads_is_refused_not_gm(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*boundary*: the grant locks no account row (nor did the legacy command), so the grantee's account can be
    deactivated while the request is parked at its final statement. The early reads judged the account active; the
    final snapshot does not: 409 `reveal_delegation_recipient_not_gm`, nothing written."""
    before = snapshot(d)

    def deactivate() -> None:
        with d.w.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE security.users SET lifecycle_status_id = (SELECT lifecycle_status_id FROM "
                    "core.lifecycle_statuses WHERE code = 'inactive') WHERE user_id = :u"
                ),
                {"u": d.x_user},
            )

    response = parked_request(
        d, pooled, lambda: grant(pooled_factory, d), lapse_role=None, at_final=deactivate
    )
    assert code(response) == 409 and error_of(response) == "reveal_delegation_recipient_not_gm", (
        response.text
    )
    assert snapshot(d) == before and idle_in_transaction(d.w.engine) == 0


def test_a_change_of_the_recipients_membership_is_serialized_behind_the_parked_grant(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*serialization*, not an impossible schedule: the grant holds the grantee's membership `FOR NO KEY UPDATE`, so
    a status change of that membership cannot commit while the grant is parked at its final statement. It is
    observed blocked by the grant's backend (and its waiting statement), the grant commits first (200), and the
    change then applies; the delegation exists and the membership ends up changed."""
    with d.w.engine.connect() as c:
        other = c.execute(
            text(
                "SELECT membership_status_id FROM security.membership_statuses WHERE code <> 'active' LIMIT 1"
            )
        ).scalar()
    if other is None:
        pytest.skip("the catalogue has no second membership status")
    with StatementGate(pooled, FINAL) as gate, LockRace(d.w.engine) as race:
        request = run_in_thread("grant", lambda: grant(pooled_factory, d))
        gate.wait_reached()

        def change(c: Any) -> None:
            c.execute(
                text(
                    "UPDATE security.campaign_memberships SET membership_status_id = :s "
                    "WHERE campaign_membership_id = :m"
                ),
                {"s": other, "m": d.x_membership},
            )

        worker = race.start("status-change", change)
        race.wait_blocked_by(gate, expected=1)
        assert "campaign_memberships" in waiting_statement(d.w.engine, gate.pid or 0)
        gate.release()
        response = request.wait("the grant finishes")
        race.join_all()
    assert code(response) == 200 and response.json()["granted"] is True
    assert worker.error is None and len(live(d)) == 1
    with d.w.engine.connect() as c:
        status = c.execute(
            text(
                "SELECT membership_status_id FROM security.campaign_memberships WHERE campaign_membership_id = :m"
            ),
            {"m": d.x_membership},
        ).scalar_one()
    assert status == other


@pytest.mark.parametrize("which", ("owner-row", "gm-row"))
def test_a_revocation_of_the_held_role_rows_is_serialized_behind_the_parked_grant(
    which: str, d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*serialization*: the owner row (`FOR SHARE`) and the `gm` row (`FOR UPDATE`) cannot be revoked while the grant
    is parked at its final statement; the revoker is observed blocked by its backend, and applies after the grant
    commits (the delegation is then closed by the role routes, as before)."""
    row = d.a_role if which == "owner-row" else d.x_role

    def revoke_row(c: Any) -> None:
        c.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
            ),
            {"r": row},
        )

    with StatementGate(pooled, FINAL) as gate, LockRace(d.w.engine) as race:
        request = run_in_thread("grant", lambda: grant(pooled_factory, d))
        gate.wait_reached()
        worker = race.start("revoke-row", revoke_row)
        race.wait_blocked_by(gate, expected=1)
        gate.release()
        response = request.wait("the grant finishes")
        race.join_all()
    assert code(response) == 200 and worker.error is None


# --- refusal precedence and the early reads are unchanged ------------------------------------------------------------


def test_the_early_refusals_keep_their_precedence_and_errors(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the final requirements do not replace the early reads. A non-owner custom manager is still refused by
    the early read with the same error (403 `campaign_owner_required`) and a player grantee still 409 not-GM, in the
    same order (owner first), with nothing written."""
    give_custom_access_manage(d, d.m.manager_membership)
    before = snapshot(d)
    both = grant(pooled_factory, d, actor=d.m.manager_user, grantee=d.p_membership)
    assert code(both) == 403 and error_of(both) == "campaign_owner_required"
    player = grant(pooled_factory, d, grantee=d.p_membership)
    assert code(player) == 409 and error_of(player) == "reveal_delegation_recipient_not_gm"
    assert code(revoke(pooled_factory, d, actor=d.m.manager_user)) == 403
    assert snapshot(d) == before and delegations(d) == []


def test_the_final_statement_reads_the_owner_and_the_recipient_in_one_statement(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*sql*: still exactly one authority read per request, at the fresh instant, carrying the reveal CTEs and the
    recipient's `gm` CTE; the recipient CTE is absent from the revoke's final statement."""
    from tests.database.test_r01_s2_profile_routes import Recorder

    with Recorder(pooled) as recorded:
        assert code(grant(pooled_factory, d)) == 200
        assert code(revoke(pooled_factory, d)) == 200
    finals = [
        e
        for e in recorded.events
        if e.startswith("WITH clock AS MATERIALIZED (SELECT clock_timestamp()")
    ]
    assert len(finals) == 2
    assert "reveal AS" in finals[0] and "subject_gm AS" in finals[0]
    assert "reveal AS" in finals[1] and "subject_gm AS" not in finals[1]


# --- the snapshot's recipient source equals the established predicate ---------------------------------------------------


def _member(
    d: D, label: str, role_code: str | None, *, campaign_role: bool = False
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID | None]:
    with d.w.engine.begin() as c:
        user = make_user(c, f"RDF {label}")
        membership = make_campaign_membership(c, d.w.campaign_id, user)
        row = None
        if role_code is not None:
            role = (
                make_role(c, campaign_id=d.w.campaign_id, code=role_code)
                if campaign_role
                else system_role_id(c, role_code)
            )
            row = make_membership_role(c, membership, role)
    return user, membership, row


def _mutate(d: D, sql: str, **binds: Any) -> None:
    with d.w.engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        c.execute(text(sql), binds)


def test_the_snapshots_recipient_assignment_equals_the_established_predicate_across_a_matrix(
    d: D,
) -> None:
    """*differential*: for each state of a recipient, `read_authority_snapshot(subject_gm_membership_id=...)` returns
    exactly what `find_live_builtin_gm_assignment` returns at the same instant (the built-in template only, never a
    campaign role named `gm`, `assistant_gm` or the owner; revoked, expired, ended, non-active and inactive-account
    recipients refused), and the owner source is `owner` only for the built-in owner template."""
    cases: dict[str, tuple[uuid.UUID, uuid.UUID, uuid.UUID | None]] = {}
    cases["live"] = _member(d, "live", "gm")
    cases["player"] = _member(d, "player", "player")
    cases["assistant"] = _member(d, "assistant", "assistant_gm")
    cases["owner-not-gm"] = _member(d, "owner", "campaign_owner")
    cases["lookalike"] = _member(d, "lookalike", "gm", campaign_role=True)
    cases["revoked"] = _member(d, "revoked", "gm")
    cases["expired"] = _member(d, "expired", "gm")
    cases["ended"] = _member(d, "ended", "gm")
    cases["status"] = _member(d, "status", "gm")
    cases["account"] = _member(d, "account", "gm")
    cases["no-role"] = _member(d, "norole", None)
    _mutate(
        d,
        "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r",
        r=cases["revoked"][2],
    )
    _mutate(
        d,
        "UPDATE security.membership_roles SET granted_at = now() - interval '2 hours', "
        "expires_at = now() - interval '1 hour' WHERE membership_role_id = :r",
        r=cases["expired"][2],
    )
    _mutate(
        d,
        "UPDATE security.campaign_memberships SET ended_at = now() WHERE campaign_membership_id = :m",
        m=cases["ended"][1],
    )
    _mutate(
        d,
        "UPDATE security.campaign_memberships SET membership_status_id = (SELECT membership_status_id FROM "
        "security.membership_statuses WHERE code <> 'active' LIMIT 1) WHERE campaign_membership_id = :m",
        m=cases["status"][1],
    )
    _mutate(
        d,
        "UPDATE security.users SET lifecycle_status_id = (SELECT lifecycle_status_id FROM core.lifecycle_statuses "
        "WHERE code = 'inactive') WHERE user_id = :u",
        u=cases["account"][0],
    )
    expected_live = {"live"}
    with d.w.engine.connect() as c:
        for name, (_user, membership, _row) in cases.items():
            snap = read_authority_snapshot(
                c,
                user_id=d.a_user,
                campaign_id=d.w.campaign_id,
                with_reveal=True,
                subject_gm_membership_id=membership,
            )
            established = find_live_builtin_gm_assignment(
                c, campaign_id=d.w.campaign_id, campaign_membership_id=membership
            )
            assert snap.subject_membership_id == membership
            assert snap.subject_gm_assignment == established, name
            assert (snap.subject_gm_assignment is not None) == (name in expected_live), name
        # an unrelated campaign: the same membership id judged in another campaign is no assignment at all
        foreign = read_authority_snapshot(
            c, user_id=d.a_user, campaign_id=uuid.uuid4(), subject_gm_membership_id=cases["live"][1]
        )
        assert foreign.subject_gm_assignment is None
        # the owner source: the built-in owner is `owner`; a gm with a delegation is `delegation`, never `owner`
        owner = read_authority_snapshot(
            c, user_id=d.a_user, campaign_id=d.w.campaign_id, with_reveal=True
        )
        assert owner.reveal_authority == "owner"
        gm = read_authority_snapshot(
            c, user_id=cases["live"][0], campaign_id=d.w.campaign_id, with_reveal=True
        )
        assert gm.reveal_authority == "none"
        undeclared = read_authority_snapshot(c, user_id=d.a_user, campaign_id=d.w.campaign_id)
        assert undeclared.subject_membership_id is None and undeclared.subject_gm_assignment is None


# --- the requirement objects (pure) -------------------------------------------------------------------------------------


def _snapshot(**kw: Any) -> AuthoritySnapshot:
    return AuthoritySnapshot(t_auth=None, isolation="read committed", access=None, **kw)  # type: ignore[arg-type]


def test_the_requirements_judge_only_the_final_snapshot_and_keep_the_established_errors() -> None:
    """*unit-level, no database*: the owner requirement holds for `owner` only (not `delegation`, not `none`, not an
    undeclared source) and raises the established owner error; the recipient requirement raises not-GM for no
    assignment, recipient-changed for a different one, and holds only for the locked row of the named grantee."""
    campaign, actor, grantee, locked = (uuid.uuid4() for _ in range(4))
    owner = plans.owner_requirement(campaign, actor)
    assert owner.reveal is True and owner.gm_subject is None
    assert owner.predicate(_snapshot(reveal_authority="owner")) is True
    for held in ("delegation", "none", None):
        assert owner.predicate(_snapshot(reveal_authority=held)) is False  # type: ignore[arg-type]
        assert isinstance(owner.refusal(), CampaignOwnerRequiredError)
    recipient = plans.recipient_requirement(grantee, locked)
    assert recipient.gm_subject == grantee and recipient.reveal is False
    held = _snapshot(subject_membership_id=grantee, subject_gm_assignment=locked)
    assert recipient.predicate(held) is True
    lapsed = _snapshot(subject_membership_id=grantee, subject_gm_assignment=None)
    assert recipient.predicate(lapsed) is False
    assert error_code(recipient.refusal()) == "reveal_delegation_recipient_not_gm"
    other = _snapshot(subject_membership_id=grantee, subject_gm_assignment=uuid.uuid4())
    assert recipient.predicate(other) is False
    assert error_code(recipient.refusal()) == "reveal_delegation_recipient_changed"
    wrong_subject = _snapshot(subject_membership_id=uuid.uuid4(), subject_gm_assignment=locked)
    assert (
        recipient.predicate(wrong_subject) is False
    )  # a snapshot of someone else never authorizes


def error_code(error: BaseException) -> str:
    return str(getattr(error, "safe_error_code", type(error).__name__))
