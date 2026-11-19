# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-F correction: the S5-E2 built-in-owner gate and the ownership transfer judge the owner at `finalize`'s instant.

Luna's S5-F review (plan 6.39.5, G-1, G-2): the owner-role gate of add / assign / change (decision D3) and the owner gate
of the ownership transfer were plain reads and a fresh-clock recheck *before* `plan.finalize`; an owner assignment that
lapses after them, while another role still supplies `access.manage`, was not stopped (probe: 201 and an owner row).
The correction registers `final_owner_requirement` (`reveal_authority == "owner"` of the one final snapshot) with
`plan.require`: for add / assign / change only when the requested role is the database-verified built-in
`campaign_owner`, and for the transfer in every branch.

Boundary scheme (the S5-E6 one): each request is parked twice with `StatementGate`, at its first role lock (gate A:
nothing is locked yet, so the test sets the expiry from the **database clock** + 6 s *after the request has entered*)
and at `finalize`'s one read (gate B: every early read and lock is behind it). At gate B the test asserts from the
database clock that the expiry has **not** passed (the early reads judged the row live), waits on the database clock
until it has, and releases. Asserted for every refusal: the exact status and error, no durable change (assignments,
memberships, audit, the key's receipt), no idle-in-transaction backend, and the next request on the same
one-connection pool is served.

Transfer, **final `access.manage` loss kept separate from owner loss**: the built-in owner template itself supplies
`access.manage`, so (a) an actor whose *only* source lapses loses the route requirement (refused by it, not by the
owner requirement) and (b) an actor with a second, custom `access.manage` role who loses the *owner* assignment keeps the
route requirement and is refused by the owner requirement; (c) losing only the custom role while the owner assignment is
live changes nothing.
"""

import types
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands import membership_role_plans as plans
from dnd_ai.commands.memberships import CampaignOwnerRequiredError
from dnd_ai.domain.access import AuthoritySnapshot
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures used by name
    FINAL,
    idle_in_transaction,
    pooled,
    pooled_factory,
)
from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixtures used by name
    code,
    error_of,
    w,
)
from tests.database.test_r01_s5e2_membership_routes import (  # noqa: F401 - fixtures used by name
    AUDIT_STEPS,
    COMMAND,
    FIRST_LOCK,
    STATUS,
    Scene,
    call,
    m,
    s,
)
from tests.database.test_r01_s5e2_membership_routes import snapshot as role_snapshot
from tests.database.test_r01_s5e2_transfer_route import (  # noqa: F401 - fixtures used by name
    COMMAND as TRANSFER_COMMAND,
)
from tests.database.test_r01_s5e2_transfer_route import (  # noqa: F401 - fixtures used by name
    T,
    _tidy,
    give_owner,
    t,
)
from tests.database.test_r01_s5e2_transfer_route import post as transfer
from tests.database.test_r01_s5e6_final_authority import (
    WINDOW_SECONDS,
    db_clock,
    expire_from_the_database_clock,
    give_custom_access_manage,
    wait_past,
)
from tests.factories import (
    make_campaign_membership,
    make_membership_role,
    make_role,
    make_role_capability,
    make_user,
)
from tests.http_race_support import StatementGate, run_in_thread

pytestmark = pytest.mark.database

#: the first lock-taking statement of a transfer (the actor's role rows, `NO KEY UPDATE` when relinquishing, else `KEY SHARE`)
TRANSFER_FIRST_LOCK = (
    r"security\.membership_roles\.campaign_membership_id = %\(membership\)s::UUID AND "
    r"security\.membership_roles\.revoked_at IS NULL AND .* ORDER BY .* FOR (NO KEY UPDATE|KEY SHARE)$"
)


def parked(
    engine: Engine,
    pool: Engine,
    request: Callable[[], Any],
    *,
    first_lock: str,
    lapse_role: uuid.UUID | None,
    also: Callable[[], None] | None = None,
) -> Any:
    """Runs `request`, parked at gate A (`first_lock`; `lapse_role` gets a database-clock expiry there) and gate B
    (`finalize`'s read; the expiry is waited out). Returns the response."""
    scene = types.SimpleNamespace(w=types.SimpleNamespace(engine=engine))
    with StatementGate(pool, first_lock) as gate_a, StatementGate(pool, FINAL) as gate_b:
        running = run_in_thread("request", request)
        gate_a.wait_reached()
        expiry = expire_from_the_database_clock(scene, lapse_role) if lapse_role else None
        if also is not None:
            also()
        gate_a.release()
        gate_b.wait_reached()
        if expiry is not None:
            assert db_clock(engine) < expiry, "the early reads ran after the expiry: window missed"
            wait_past(scene, expiry)
        gate_b.release()
        return running.wait("the request finishes")


# --- add / assign / change with the built-in owner role -----------------------------------------------------------------


def _owner_with_a_second_manager_role(sc: Scene) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A built-in owner (the row that will lapse) who also holds a custom `access.manage` role."""
    with sc.w.engine.begin() as c:
        user = make_user(c, "S5F owner")
        membership = make_campaign_membership(c, sc.w.campaign_id, user)
        owner_row = make_membership_role(c, membership, sc.owner)
        capability = c.execute(
            text("SELECT capability_id FROM security.capabilities WHERE code = 'access.manage'")
        ).scalar_one()
        custom = make_role(c, campaign_id=sc.w.campaign_id)
        make_role_capability(c, custom, capability)
        make_membership_role(c, membership, custom)
    return user, membership, owner_row


def _core(sc: Scene, key: str | None) -> tuple[Any, ...]:
    """Everything the routes persist, less the lapsing row's expiry (which the test itself sets)."""
    memberships, assignments, audit, receipt = role_snapshot(sc, key)
    return memberships, [row[:3] for row in assignments], audit, receipt


def _owner_effect(sc: Scene, route: str, user: uuid.UUID) -> dict[str, Any]:
    """The business effect of an owner-role route: live built-in owner rows on its target, and the changed row's state."""
    with sc.w.engine.connect() as c:
        if route == "add":
            member = c.execute(
                text(
                    "SELECT campaign_membership_id FROM security.campaign_memberships "
                    "WHERE campaign_id = :c AND user_id = :u"
                ),
                {"c": sc.w.campaign_id, "u": sc.new_user},
            ).scalar_one()
        else:
            member = sc.target_membership
        owner_rows = c.execute(
            text(
                "SELECT count(*) FROM security.membership_roles WHERE campaign_membership_id = :m "
                "AND role_id = :r AND revoked_at IS NULL"
            ),
            {"m": member, "r": sc.owner},
        ).scalar_one()
        old_live = c.execute(
            text(
                "SELECT revoked_at IS NULL FROM security.membership_roles WHERE membership_role_id = :r"
            ),
            {"r": sc.target_role},
        ).scalar_one()
    return {"owner_rows": owner_rows, "old_row_live": old_live}


def _audit_count(sc: Scene, command: str) -> int:
    with sc.w.engine.connect() as c:
        return int(
            c.execute(
                text(
                    "SELECT count(*) FROM audit.change_log WHERE world_id = :w AND command_name = :n"
                ),
                {"w": sc.w.world_id, "n": command},
            ).scalar_one()
        )


def _receipts(sc: Scene, actor: uuid.UUID, key: str) -> list[tuple[Any, ...]]:
    """The receipts scoped by actor, campaign and key: (status, body, completed)."""
    with sc.w.engine.connect() as c:
        return [
            (r[0], r[1], r[2])
            for r in c.execute(
                text(
                    "SELECT response_status_code, response_body, completed_at IS NOT NULL "
                    "FROM security.idempotent_requests "
                    "WHERE actor_user_id = :a AND campaign_id = :c AND idempotency_key = :k"
                ),
                {"a": actor, "c": sc.w.campaign_id, "k": key},
            )
        ]


@pytest.mark.parametrize("keyed", (False, True), ids=("unkeyed", "keyed"))
@pytest.mark.parametrize("route", ("add", "assign", "change"))
def test_the_owner_role_is_refused_when_the_actors_owner_assignment_lapses_before_finalize(
    route: str, keyed: bool, s: Scene, pooled: Engine, pooled_factory: Any
) -> None:
    """*boundary*: the requested role is the built-in `campaign_owner`; the actor's owner row lapses between the early
    reads (live) and `finalize` while a custom role keeps `access.manage`. 403 `campaign_owner_required`; no membership,
    assignment, audit row or receipt; the key is reusable by a live owner; the pool is clean."""
    user, _membership, owner_row = _owner_with_a_second_manager_role(s)
    key = str(uuid.uuid4()) if keyed else None
    before = _core(s, key)
    response = parked(
        s.w.engine,
        pooled,
        lambda: call(pooled_factory, s, route, key=key, actor=user, role=s.owner),
        first_lock=FIRST_LOCK[route],
        lapse_role=owner_row,
    )
    assert (code(response), error_of(response)) == (403, "campaign_owner_required"), response.text
    assert _core(s, key) == before, "a refusal at the final instant writes nothing"
    assert idle_in_transaction(s.w.engine) == 0
    # the route requirement alone would have admitted the actor: the custom role still supplies `access.manage`
    from dnd_ai.domain.access import read_authority_snapshot

    with s.w.engine.connect() as c:
        final = read_authority_snapshot(
            c, user_id=user, campaign_id=s.w.campaign_id, with_reveal=True
        )
    assert final.access is not None and "access.manage" in final.access.role_capabilities
    assert final.reveal_authority != "owner"
    if not keyed:
        # pooled reuse: the next request on the same pooled connection is served
        retry = call(pooled_factory, s, route, key=None, actor=s.w.owner, role=s.owner)
        assert code(retry) in (200, 201), retry.text
        return
    # the same scoped key (actor, campaign, key), same payload: the original actor's owner authority is restored with
    # supported setup (the lapsed assignment is made non-expiring again) and the retry runs the command once
    with s.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = NULL WHERE membership_role_id = :r"
            ),
            {"r": owner_row},
        )
    retry = call(pooled_factory, s, route, key=key, actor=user, role=s.owner)
    assert code(retry) == STATUS[route], (code(retry), retry.text)
    effect = _owner_effect(s, route, user)
    assert effect["owner_rows"] == 1, effect
    if route == "change":
        assert effect["old_row_live"] is False, "the changed assignment was revoked"
    assert _audit_count(s, COMMAND[route]) == len(AUDIT_STEPS[route]), (
        "exactly the route's audit rows, once"
    )
    receipts = _receipts(s, user, key)
    assert len(receipts) == 1, receipts
    status, body, completed = receipts[0]
    assert completed is True and status == STATUS[route] and body == retry.json(), receipts
    # the stored receipt is what a further same-key retry replays, writing nothing
    again = call(pooled_factory, s, route, key=key, actor=user, role=s.owner)
    assert code(again) == STATUS[route] and again.json() == retry.json()
    assert _audit_count(s, COMMAND[route]) == len(AUDIT_STEPS[route])


@pytest.mark.parametrize("route", ("add", "assign", "change"))
def test_the_control_without_a_lapse_succeeds_through_the_same_gates(
    route: str, s: Scene, pooled: Engine, pooled_factory: Any
) -> None:
    user, _membership, _owner_row = _owner_with_a_second_manager_role(s)
    response = parked(
        s.w.engine,
        pooled,
        lambda: call(pooled_factory, s, route, key=None, actor=user, role=s.owner),
        first_lock=FIRST_LOCK[route],
        lapse_role=None,
    )
    assert code(response) in (200, 201), response.text


@pytest.mark.parametrize("route", ("add", "assign", "change"))
@pytest.mark.parametrize("kind", ("another_builtin_role", "campaign_role_named_campaign_owner"))
def test_a_role_that_is_not_the_builtin_owner_registers_no_owner_requirement(
    route: str, kind: str, s: Scene, pooled: Engine, pooled_factory: Any
) -> None:
    """Only the database-verified built-in `campaign_owner` registers the requirement: the same lapse with a built-in
    `observer` role, or a *campaign* role that merely carries the code `campaign_owner`, still succeeds (the custom role
    supplies `access.manage`), exactly as before."""
    user, _membership, owner_row = _owner_with_a_second_manager_role(s)
    if kind == "another_builtin_role":
        role = s.observer
    else:
        with s.w.engine.begin() as c:
            role = make_role(c, campaign_id=s.w.campaign_id, code="campaign_owner")
    response = parked(
        s.w.engine,
        pooled,
        lambda: call(pooled_factory, s, route, key=None, actor=user, role=role),
        first_lock=FIRST_LOCK[route],
        lapse_role=owner_row,
    )
    assert code(response) in (200, 201), response.text


def test_the_final_owner_requirement_judges_only_the_final_snapshot() -> None:
    """*unit-level, no database*: holds for the reveal source `owner` only (not a delegation, not none), reads the
    reveal source, and raises the established owner error."""
    requirement = plans.final_owner_requirement(uuid.uuid4(), uuid.uuid4())
    assert requirement.name == "membership_role.owner" and requirement.reveal is True
    assert requirement.gm_subject is None

    def snap(authority: Any) -> AuthoritySnapshot:
        return AuthoritySnapshot(
            t_auth=None, isolation="read committed", access=None, reveal_authority=authority
        )  # type: ignore[arg-type]

    assert requirement.predicate(snap("owner")) is True
    for held in ("delegation", "none", None):
        assert requirement.predicate(snap(held)) is False
    assert isinstance(requirement.refusal(), CampaignOwnerRequiredError)


# --- the ownership transfer, every branch --------------------------------------------------------------------------------

BRANCHES = ("fresh", "relinquish", "no_op", "stale_replacement", "self")


def _transfer_state(t: T) -> tuple[Any, ...]:
    with t.w.engine.connect() as c:
        roles = c.execute(
            text(
                "SELECT mr.membership_role_id, mr.role_id, mr.revoked_at IS NULL "
                "FROM security.membership_roles mr JOIN security.campaign_memberships cm "
                "USING (campaign_membership_id) WHERE cm.campaign_id = :c ORDER BY 1"
            ),
            {"c": t.w.campaign_id},
        ).all()
        audit = c.execute(
            text("SELECT count(*) FROM audit.change_log WHERE world_id = :w AND command_name = :n"),
            {"w": t.w.world_id, "n": TRANSFER_COMMAND},
        ).scalar_one()
        receipts = c.execute(
            text("SELECT count(*) FROM security.idempotent_requests WHERE campaign_id = :c"),
            {"c": t.w.campaign_id},
        ).scalar_one()
    return [tuple(r) for r in roles], audit, receipts


def _arrange(branch: str, t: T) -> dict[str, Any]:
    if branch == "no_op":
        give_owner(t)  # the recipient is already a live owner
    elif branch == "stale_replacement":
        give_owner(t, expires="expired")  # an unrevoked expired owner row, replaced by the transfer
    kwargs: dict[str, Any] = {"relinquish": branch == "relinquish"}
    if branch == "self":
        kwargs["target"] = t.a_membership
    return kwargs


@pytest.mark.parametrize("branch", BRANCHES)
def test_a_transfer_is_refused_when_the_callers_owner_assignment_lapses_before_finalize_though_another_role_supplies_access_manage(
    branch: str, t: T, pooled: Engine, pooled_factory: Any
) -> None:
    """*boundary*, every branch: A is a built-in owner and holds a custom `access.manage` role; A's owner row lapses
    after the early reads. The route requirement still holds, so only the owner requirement refuses:
    403 `campaign_owner_required`, nothing persisted (assignments, the transfer's audit row, any receipt), clean pool."""
    give_custom_access_manage(t, t.a_membership)
    kwargs = _arrange(branch, t)
    before = _transfer_state(t)
    response = parked(
        t.w.engine,
        pooled,
        lambda: transfer(pooled_factory, t, **kwargs),
        first_lock=TRANSFER_FIRST_LOCK,
        lapse_role=t.a_role,
    )
    assert (code(response), error_of(response)) == (403, "campaign_owner_required"), response.text
    assert _transfer_state(t) == before
    assert idle_in_transaction(t.w.engine) == 0
    assert code(transfer(pooled_factory, t, actor=t.b_user, target=t.b_membership)) == 200, (
        "the next request on the same pooled connection is served"
    )


@pytest.mark.parametrize("branch", BRANCHES)
def test_a_transfer_is_refused_by_the_route_requirement_when_the_only_source_of_access_manage_lapses(
    branch: str, t: T, pooled: Engine, pooled_factory: Any
) -> None:
    """*boundary*, final `access.manage` loss, **kept separate from owner loss**: A's only source of `access.manage` is the
    built-in owner assignment, so its lapse loses the route requirement. The refusal is the route requirement's (403,
    not `campaign_owner_required`), nothing persists, the pool is clean. (An actor cannot lose `access.manage` while the
    built-in owner assignment is live: the owner template supplies it.)"""
    kwargs = _arrange(branch, t)
    before = _transfer_state(t)
    response = parked(
        t.w.engine,
        pooled,
        lambda: transfer(pooled_factory, t, **kwargs),
        first_lock=TRANSFER_FIRST_LOCK,
        lapse_role=t.a_role,
    )
    assert code(response) == 403, response.text
    assert error_of(response) != "campaign_owner_required", response.text
    assert _transfer_state(t) == before
    assert idle_in_transaction(t.w.engine) == 0
    assert code(transfer(pooled_factory, t, actor=t.b_user, target=t.b_membership)) == 200


@pytest.mark.parametrize("branch", BRANCHES)
def test_the_transfer_controls_succeed_through_the_same_gates(
    branch: str, t: T, pooled: Engine, pooled_factory: Any
) -> None:
    """Without a lapse, and with only a *custom* `access.manage` role lapsing while the owner assignment is live (the
    owner template supplies `access.manage`), every branch is served exactly as before."""
    give_custom_access_manage(t, t.a_membership)
    kwargs = _arrange(branch, t)
    with t.w.engine.connect() as c:
        custom_row = c.execute(
            text(
                "SELECT mr.membership_role_id FROM security.membership_roles mr "
                "WHERE mr.campaign_membership_id = :m AND mr.role_id <> :o AND mr.revoked_at IS NULL"
            ),
            {"m": t.a_membership, "o": t.owner},
        ).scalar_one()
    response = parked(
        t.w.engine,
        pooled,
        lambda: transfer(pooled_factory, t, **kwargs),
        first_lock=TRANSFER_FIRST_LOCK,
        lapse_role=custom_row,
    )
    assert code(response) == 200, response.text
    assert WINDOW_SECONDS > 0
