# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-E2 ownership-transfer amendment: the ownership-transfer route as an unkeyed pre-write plan, over real HTTP.

`transfer_campaign_ownership_endpoint` takes the actor's role rows `FOR NO KEY UPDATE`, the recipient's expired
owner row `FOR NO KEY UPDATE` and then its live owner row `FOR KEY SHARE`, the actor's owner row when relinquishing,
the memberships (one ordered `FOR UPDATE` statement), the accounts, the campaign and the owner template; it reads
and refuses before `plan.finalize`, then writes through declared steps (close expired, close delegations, insert
owner `PerAbsence`, relinquish, one audit row `AnyConfirmed`). `memberships.transfer_campaign_ownership` stays the
direct command and is the **oracle** here: each branch and refusal is compared with what the legacy command
returns or raises on the same state (inside a rolled-back transaction).

Evidence classes: **route** (a real HTTP request through the guard), **sql** (the recorded statement stream),
**race** (two real requests or a request and a competitor, each parked on a named statement; every wait is observed
through `pg_blocking_pids`), **mutation (test-side)** (`AuthorizationPlan.execute` wrapped to omit or repeat a write).
"""

import dataclasses
import re
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.commands import membership_role_plans as plans
from dnd_ai.commands.memberships import (
    end_campaign_membership,
    transfer_campaign_ownership,
)
from dnd_ai.domain.authorization import (
    AuthorizationPlan,
    StepOutcome,
    ViolationReason,
    install_authorization_guard,
)
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures used by name
    FINAL,
    Recorder,
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
from tests.factories import (
    make_campaign_membership,
    make_external_identity,
    make_membership_role,
    make_user,
    oidc_principal,
    system_role_id,
)
from tests.http_race_support import (
    StatementGate,
    deadlock_count,
    new_key,
    run_in_thread,
    wait_for_deadlock_count,
)
from tests.lock_race_support import LockRace
from tests.r01_s5d_support import Managers, make_managers

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]

ACTOR_ROWS = (
    r"membership_roles\.campaign_membership_id = %\(membership\)s::UUID AND "
    r"security\.membership_roles\.revoked_at IS NULL ORDER BY .* FOR NO KEY UPDATE$"
)
EXPIRED_ROW = r"expires_at <= pg_catalog\.clock_timestamp\(\) .*FOR NO KEY UPDATE$"
LIVE_ROW = r"FROM security\.membership_roles WHERE .*FOR KEY SHARE$"
OWN_ROW = (
    r"membership_roles\.role_id = %\(role\)s::UUID AND (?!.*clock_timestamp).*FOR NO KEY UPDATE$"
)
MEMBERSHIPS_U = r"FROM security\.campaign_memberships WHERE .* ORDER BY .* FOR UPDATE$"
ACCOUNT_S = r"FROM security\.users WHERE .* FOR SHARE$"
ACCOUNT_KS = r"FROM security\.users WHERE .* FOR KEY SHARE$"
CAMPAIGN_U = r"FROM campaign\.campaigns WHERE campaign\.campaigns\.campaign_id = %\(campaign\)s::UUID FOR UPDATE$"
CATALOGUE_U = r"FROM security\.roles WHERE .* ORDER BY .* FOR UPDATE$"
AUDIT_INSERT = r"^INSERT INTO audit\.change_log"
INSERT_ROLE = r"^INSERT INTO security\.membership_roles"
UPDATE_ROLE = r"^UPDATE security\.membership_roles SET revoked_at"
COMMAND = "transfer_campaign_ownership"


@dataclasses.dataclass
class T:
    w: World
    m: Managers
    owner: uuid.UUID  # the built-in owner template
    a_user: uuid.UUID
    a_membership: uuid.UUID
    a_role: uuid.UUID  # A's owner assignment
    b_user: uuid.UUID
    b_membership: uuid.UUID
    b_role: uuid.UUID
    c_user: uuid.UUID
    c_membership: uuid.UUID  # the recipient: a player, not an owner
    gm: uuid.UUID


@pytest.fixture
def t(w: World) -> T:
    m = make_managers(w.engine, w.campaign_id, label="TR")
    with w.engine.begin() as c:
        owner = system_role_id(c, "campaign_owner")
        player = system_role_id(c, "player")
        gm = system_role_id(c, "gm")
        users = []
        for label in ("A", "B", "C"):
            user = make_user(c, f"TR {label}")
            make_external_identity(c, user, issuer="local")
            users.append((user, make_campaign_membership(c, w.campaign_id, user)))
        (a_user, a_membership), (b_user, b_membership), (c_user, c_membership) = users
        a_role = make_membership_role(c, a_membership, owner)
        b_role = make_membership_role(c, b_membership, owner)
        make_membership_role(c, c_membership, player)
    return T(
        w,
        m,
        owner,
        a_user,
        a_membership,
        a_role,
        b_user,
        b_membership,
        b_role,
        c_user,
        c_membership,
        gm,
    )


@pytest.fixture(autouse=True)
def _tidy(w: World) -> Any:
    yield
    with w.engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text(
                "DELETE FROM audit.change_log WHERE world_id = :w AND table_name IN "
                "('campaign_memberships', 'membership_roles', 'character_reveal_delegations')"
            ),
            {"w": w.world_id},
        )


# --- helpers ---------------------------------------------------------------------------------------------------------


def post(
    factory: Factory,
    t: T,
    *,
    actor: uuid.UUID | None = None,
    target: uuid.UUID | None = None,
    relinquish: bool = False,
    key: str | None = None,
) -> Any:
    headers = {"Idempotency-Key": key} if key else {}
    with factory(actor or t.a_user) as client:
        return client.post(
            f"{t.w.base}/ownership-transfer",
            json={
                "target_campaign_membership_id": str(target or t.c_membership),
                "relinquish_own_ownership": relinquish,
            },
            headers=headers,
        )


def give_owner(
    t: T, membership: uuid.UUID | None = None, *, expires: str | None = None
) -> uuid.UUID:
    """An owner assignment for `membership` (default C): non-expiring, `expires` an SQL interval from now, or
    `'expired'` (unrevoked and long expired)."""
    with t.w.engine.begin() as c:
        row = make_membership_role(c, membership or t.c_membership, t.owner)
        if expires == "expired":
            c.execute(
                text(
                    "UPDATE security.membership_roles SET granted_at = now() - interval '2 hours', "
                    "expires_at = now() - interval '1 hour' WHERE membership_role_id = :r"
                ),
                {"r": row},
            )
        elif expires:
            c.execute(
                text(
                    "UPDATE security.membership_roles SET expires_at = now() + CAST(:i AS interval) "
                    "WHERE membership_role_id = :r"
                ),
                {"r": row, "i": expires},
            )
    return row


def owner_rows(t: T, membership: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]:
    """(id, revoked, expired) of every owner assignment of `membership`."""
    with t.w.engine.connect() as c:
        return [
            (r[0], r[1], r[2])
            for r in c.execute(
                text(
                    "SELECT membership_role_id, revoked_at IS NOT NULL, "
                    "(expires_at IS NOT NULL AND expires_at <= now()) FROM security.membership_roles "
                    "WHERE campaign_membership_id = :m AND role_id = :r ORDER BY granted_at, 1"
                ),
                {"m": membership, "r": t.owner},
            ).all()
        ]


def live_owners(t: T) -> set[uuid.UUID]:
    with t.w.engine.connect() as c:
        return set(
            c.execute(
                text(
                    "SELECT DISTINCT mr.campaign_membership_id FROM security.membership_roles mr "
                    "JOIN security.campaign_memberships cm USING (campaign_membership_id) "
                    "WHERE cm.campaign_id = :c AND mr.role_id = :r AND mr.revoked_at IS NULL "
                    "AND (mr.expires_at IS NULL OR mr.expires_at > clock_timestamp())"
                ),
                {"c": t.w.campaign_id, "r": t.owner},
            ).scalars()
        )


def audits(t: T) -> list[dict[str, Any]]:
    with t.w.engine.connect() as c:
        return [
            dict(r)
            for r in c.execute(
                text(
                    "SELECT command_name, schema_name, table_name, record_id, entity_id, event_id, world_id, "
                    "actor_user_id, changed_fields, ca.code AS action FROM audit.change_log cl "
                    "JOIN audit.change_actions ca USING (change_action_id) WHERE cl.world_id = :w "
                    "AND cl.command_name = :n ORDER BY change_log_id"
                ),
                {"w": t.w.world_id, "n": COMMAND},
            )
            .mappings()
            .all()
        ]


def snapshot(t: T) -> tuple[Any, ...]:
    with t.w.engine.connect() as c:
        roles = c.execute(
            text(
                "SELECT mr.membership_role_id, mr.revoked_at IS NULL FROM security.membership_roles mr "
                "JOIN security.campaign_memberships cm USING (campaign_membership_id) "
                "WHERE cm.campaign_id = :c ORDER BY 1"
            ),
            {"c": t.w.campaign_id},
        ).all()
        receipts = c.execute(
            text("SELECT count(*) FROM security.idempotent_requests WHERE campaign_id = :c"),
            {"c": t.w.campaign_id},
        ).scalar_one()
    return ([tuple(r) for r in roles], receipts, audits(t))


def legacy(t: T, *, actor: uuid.UUID, target: uuid.UUID, relinquish: bool) -> tuple[Any, ...]:
    """What the direct command does on the current state, inside a transaction that is always rolled back."""
    with t.w.engine.connect() as c:
        transaction = c.begin()
        try:
            result = transfer_campaign_ownership(
                c,
                campaign_id=t.w.campaign_id,
                actor_membership_id=actor,
                target_campaign_membership_id=target,
                relinquish_own_ownership=relinquish,
            )
            return (
                "ok",
                result.assigned_membership_role_id is not None,
                bool(result.revoked_membership_role_ids),
                bool(result.replaced_expired_membership_role_ids),
            )
        except Exception as error:
            status = getattr(
                error, "safe_status_code", 400 if isinstance(error, ValueError) else 500
            )
            return ("error", status, getattr(error, "safe_error_code", type(error).__name__))
        finally:
            transaction.rollback()


# --- branches ----------------------------------------------------------------------------------------------------------
# (setup, relinquish, assigned, relinquished, replaced, record of the audit row)
BRANCHES = {
    "N1-live-owner": (lambda t: give_owner(t), False, False, False, False, None),
    "N1-live-finite-owner": (
        lambda t: give_owner(t, expires="1 hour"),
        False,
        False,
        False,
        False,
        None,
    ),
    "N2-no-owner-row": (lambda t: None, False, True, False, False, "new"),
    "N3-expired-owner-row": (
        lambda t: give_owner(t, expires="expired"),
        False,
        True,
        False,
        True,
        "new",
    ),
    "R1-live-owner": (lambda t: give_owner(t), True, False, True, False, "actor"),
    "R2-no-owner-row": (lambda t: None, True, True, True, False, "new"),
    "R3-expired-owner-row": (
        lambda t: give_owner(t, expires="expired"),
        True,
        True,
        True,
        True,
        "new",
    ),
}


@pytest.mark.parametrize("branch", sorted(BRANCHES))
def test_each_branch_matches_the_direct_command_and_writes_exactly_the_documented_rows(
    branch: str, t: T, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: every row of the design's branch table. The legacy command, run first on the same state and rolled
    back, gives the expected flags; the route returns them, closes the expired row, inserts the live owner row only
    when none lives, revokes the caller's row only when relinquishing, and writes ONE audit row (also when it both
    assigns and relinquishes) whose `record_id` is the new assignment, else the relinquished one."""
    setup, relinquish, assigned, relinquished, replaced, record = BRANCHES[branch]
    expired_row = setup(t)
    expected = legacy(t, actor=t.a_membership, target=t.c_membership, relinquish=relinquish)
    assert expected == ("ok", assigned, relinquished, replaced), expected
    before_c = owner_rows(t, t.c_membership)
    response = post(pooled_factory, t, relinquish=relinquish)
    assert code(response) == 200, response.text
    assert response.json() == {
        "target_campaign_membership_id": str(t.c_membership),
        "assigned": assigned,
        "relinquished": relinquished,
    }
    after_c = owner_rows(t, t.c_membership)
    assert len(after_c) == len(before_c) + (1 if assigned else 0)
    assert [r for r in after_c if not r[1] and not r[2]] != [] or not (assigned or before_c)
    if replaced:
        assert next(r for r in after_c if r[0] == expired_row)[1] is True
    assert owner_rows(t, t.a_membership)[0][1] is relinquished
    rows = audits(t)
    if record is None:
        assert rows == []
    else:
        assert len(rows) == 1, "one audit row, also for assign + relinquish"
        row = rows[0]
        assert row["action"] == "updated" and row["schema_name"] == "security"
        assert row["table_name"] == "membership_roles" and row["actor_user_id"] == t.a_user
        assert row["entity_id"] is None and row["event_id"] is None
        assert row["world_id"] == t.w.world_id
        assert row["changed_fields"] == {
            "assigned": assigned,
            "relinquished": relinquished,
            "replaced_expired_assignment": replaced,
        }
        known = {r[0] for r in before_c}
        new = next(r[0] for r in after_c if r[0] not in known) if assigned else None
        assert row["record_id"] == (new if record == "new" else t.a_role)
    assert idle_in_transaction(t.w.engine) == 0


@pytest.mark.parametrize("relinquish", (False, True))
def test_a_transfer_to_oneself_changes_nothing_with_either_flag(
    relinquish: bool, t: T, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: self-transfer is never relinquishing (the owner keeps ownership) and writes nothing."""
    before = snapshot(t)
    response = post(pooled_factory, t, target=t.a_membership, relinquish=relinquish)
    assert code(response) == 200
    assert response.json()["assigned"] is False and response.json()["relinquished"] is False
    assert snapshot(t) == before


def _refusal_cases() -> dict[str, Callable[[T], dict[str, Any]]]:
    def non_owner(t: T) -> dict[str, Any]:
        return {"actor": t.m.manager_user, "actor_membership": t.m.manager_membership}

    def other_campaign(t: T) -> dict[str, Any]:
        with t.w.engine.begin() as c:
            owner = make_user(c, "TR Other Owner")
            authored = make_authored_world(c, owner_user_id=owner, name="TR Other World")
            other = make_authored_campaign(c, authored, name="TR Other Campaign")
            foreign = make_campaign_membership(c, other, make_user(c, "TR Foreign"))
        return {"target": foreign}

    def nonexistent(t: T) -> dict[str, Any]:
        return {"target": uuid.uuid4()}

    def ended(t: T) -> dict[str, Any]:
        with t.w.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE security.campaign_memberships SET ended_at = now() + interval '1 microsecond' "
                    "WHERE campaign_membership_id = :m"
                ),
                {"m": t.c_membership},
            )
        return {}

    def suspended(t: T) -> dict[str, Any]:
        with t.w.engine.begin() as c:
            status = c.execute(
                text(
                    "SELECT membership_status_id FROM security.membership_statuses "
                    "WHERE code <> 'active' ORDER BY code LIMIT 1"
                )
            ).scalar()
            if status is None:
                return {"skip": True}
            c.execute(
                text(
                    "UPDATE security.campaign_memberships SET membership_status_id = :s "
                    "WHERE campaign_membership_id = :m"
                ),
                {"s": status, "m": t.c_membership},
            )
        return {}

    def inactive_account(t: T) -> dict[str, Any]:
        with t.w.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE security.users SET lifecycle_status_id = (SELECT lifecycle_status_id FROM "
                    "core.lifecycle_statuses WHERE code = 'inactive') WHERE user_id = :u"
                ),
                {"u": t.c_user},
            )
        return {}

    def finite_live_relinquish(t: T) -> dict[str, Any]:
        give_owner(t, expires="1 hour")
        return {"relinquish": True}

    def retention_before_replacement(t: T) -> dict[str, Any]:
        """F-9, approved to keep (P3): the expired row is closed *before* the replacement exists, so with no
        other non-expiring manager the legacy retention assert refuses it (400)."""
        give_owner(t, expires="expired")
        with t.w.engine.begin() as c:
            c.execute(text("SET LOCAL session_replication_role = replica"))
            c.execute(
                text(
                    "UPDATE security.membership_roles SET expires_at = now() + interval '1 day' "
                    "WHERE campaign_membership_id IN (SELECT campaign_membership_id FROM "
                    "security.campaign_memberships WHERE campaign_id = :c) AND revoked_at IS NULL "
                    "AND expires_at IS NULL"
                ),
                {"c": t.w.campaign_id},
            )
        return {}

    return {
        "non-owner-caller": non_owner,
        "recipient-in-another-campaign": other_campaign,
        "nonexistent-recipient": nonexistent,
        "ended-recipient": ended,
        "suspended-recipient": suspended,
        "inactive-recipient-account": inactive_account,
        "relinquish-to-a-finite-live-owner": finite_live_relinquish,
        "retention-before-replacement": retention_before_replacement,
    }


@pytest.mark.parametrize("case", sorted(_refusal_cases()))
def test_each_refusal_matches_the_direct_command_in_status_and_code_and_persists_nothing(
    case: str, t: T, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: precedence and classification preserved (design section 2, step order). The legacy command on the
    same state says which refusal wins; the route returns the same status and code, nothing persists, no key is
    consumed, the connection returns clean."""
    knobs = _refusal_cases()[case](t)
    if knobs.get("skip"):
        pytest.skip("no second campaign in the database")
    actor = knobs.get("actor", t.a_user)
    actor_membership = knobs.get("actor_membership", t.a_membership)
    target = knobs.get("target", t.c_membership)
    relinquish = knobs.get("relinquish", False)
    expected = legacy(t, actor=actor_membership, target=target, relinquish=relinquish)
    assert expected[0] == "error", expected
    before = snapshot(t)
    response = post(pooled_factory, t, actor=actor, target=target, relinquish=relinquish)
    assert code(response) == expected[1], (response.text, expected)
    if expected[2] not in ("ValueError",):
        assert error_of(response) == expected[2] or code(response) in (400, 404)
    assert snapshot(t) == before
    assert idle_in_transaction(t.w.engine) == 0


def test_an_idempotency_key_is_ignored_and_no_receipt_is_written(
    t: T, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* (P4): the route stays unkeyed. The same key twice executes twice (assign, then the documented
    no-op), reserves nothing and replays nothing."""
    key = new_key()
    first = post(pooled_factory, t, key=key)
    second = post(pooled_factory, t, key=key)
    assert (code(first), first.json()["assigned"]) == (200, True)
    assert (code(second), second.json()["assigned"]) == (200, False)
    assert snapshot(t)[1] == 0
    assert len(audits(t)) == 1


def test_the_statement_order_is_the_documented_lock_order_and_nothing_but_declared_writes_follow_finalize(
    t: T, pooled: Engine, pooled_factory: Factory
) -> None:
    """*sql*: R3 (every branch's statements): actor rows, the recipient's expired row, its live row, the actor's
    owner row, memberships, the actor's account, the recipient's account, the campaign, the owner template, the
    reads and refusals, `finalize`; then only the closes, the insert, the relinquish and the one audit row."""
    give_owner(t, expires="expired")
    with Recorder(pooled) as recorded:
        response = post(pooled_factory, t, relinquish=True)
    assert code(response) == 200, response.text
    events = recorded.events
    order = [
        ACTOR_ROWS,
        EXPIRED_ROW,
        LIVE_ROW,
        OWN_ROW,
        MEMBERSHIPS_U,
        ACCOUNT_S,
        ACCOUNT_KS,
        CAMPAIGN_U,
        CATALOGUE_U,
        FINAL,
    ]
    position = -1
    for pattern in order:
        found = [i for i, e in enumerate(events) if re.search(pattern, e) and i > position]
        assert found, f"{pattern!r} not found after {position}: {events}"
        position = found[0]
    final = next(i for i, e in enumerate(events) if re.search(FINAL, e))
    assert all(re.search(r"^(UPDATE|INSERT)|^COMMIT$", e) for e in events[final + 1 :]), events[
        final + 1 :
    ]
    tail = [e for e in events[final + 1 :] if e != "COMMIT"]
    assert [bool(re.search(UPDATE_ROLE, e)) for e in tail[:1]] == [True], (
        "the closure precedes the insert"
    )
    assert len([e for e in tail if re.search(INSERT_ROLE, e)]) == 1
    assert len([e for e in tail if re.search(AUDIT_INSERT, e)]) == 1
    assert len([e for e in tail if re.search(UPDATE_ROLE, e)]) == 2
    assert tail.index(next(e for e in tail if re.search(INSERT_ROLE, e))) > 0


def test_a_handler_that_forgets_to_finalize_is_a_sanitized_500_that_persists_nothing(
    t: T, pooled: Engine, pooled_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """*mutation (test-side)*: `finalize` never runs; the first declared write is refused and nothing persists."""
    before = snapshot(t)
    monkeypatch.setattr(AuthorizationPlan, "finalize", lambda self, connection: None)
    response = post(pooled_factory, t)
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error"
    assert snapshot(t) == before and idle_in_transaction(t.w.engine) == 0


# --- fault injection in the write phase ---------------------------------------------------------------------------------


def _wrap(
    monkeypatch: pytest.MonkeyPatch,
    *,
    skip: tuple[str, ...] = (),
    repeat: tuple[str, ...] = (),
    also: Callable[[AuthorizationPlan, Any, Any], None] | None = None,
) -> list[ViolationReason]:
    """Test-side wrapper of the plan: omit, repeat or add a write; returns the latched reasons, first first."""
    original = AuthorizationPlan.execute
    latched: list[ViolationReason] = []
    original_latch = AuthorizationPlan._latch

    def latch(self: AuthorizationPlan, reason: ViolationReason) -> None:
        latched.append(reason)
        original_latch(self, reason)

    def wrapper(self: AuthorizationPlan, connection: Any, step: Any, params: Any) -> StepOutcome:
        if also is not None and step.name in (
            "close_expired_owner",
            "insert_owner_role",
            "relinquish_owner",
        ):
            also(self, connection, step)
        if step.name in skip:
            fake = uuid.uuid4()
            return StepOutcome(step=step.name, keys=((fake,),))
        outcome = original(self, connection, step, params)
        if step.name in repeat:
            original(self, connection, step, params)
        return outcome

    monkeypatch.setattr(AuthorizationPlan, "execute", wrapper)
    monkeypatch.setattr(AuthorizationPlan, "_latch", latch)
    return latched


@pytest.mark.parametrize(
    ("branch", "skipped", "reason"),
    (
        ("N2-no-owner-row", "insert_owner_role", ViolationReason.EVIDENCE),
        ("R2-no-owner-row", "insert_owner_role", ViolationReason.EVIDENCE),
        ("N3-expired-owner-row", "close_expired_owner", ViolationReason.ORDER),
        ("R3-expired-owner-row", "close_expired_owner", ViolationReason.ORDER),
        ("R1-live-owner", "relinquish_owner", ViolationReason.EVIDENCE),
        ("N2-no-owner-row", "audit_transferred", ViolationReason.INCOMPLETE),
    ),
)
def test_an_omitted_required_write_never_commits(
    branch: str,
    skipped: str,
    reason: ViolationReason,
    t: T,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)*: each required write is owed by the locked state. Omitting the owner INSERT (N2, R2),
    the closure that must precede it (N3, R3: the INSERT is then refused `ORDER`, the unique index never reached),
    the relinquish (R1) or the audit row leaves a plan the guard refuses: a sanitized 500, everything rolled back.
    (The wrapper returns a fake key for the omitted step so the route continues to the next declared write.)"""
    setup, relinquish, *_ = BRANCHES[branch]
    setup(t)
    before = snapshot(t)
    latched = _wrap(monkeypatch, skip=(skipped,))
    with Recorder(pooled) as recorded:
        response = post(pooled_factory, t, relinquish=relinquish)
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error", response.text
    assert latched, "the guard latched"
    assert latched[0] in (
        reason,
        ViolationReason.COUNT,
        ViolationReason.EVIDENCE,
        ViolationReason.ORDER,
    )
    assert snapshot(t) == before and idle_in_transaction(t.w.engine) == 0
    if skipped == "close_expired_owner":
        assert not [e for e in recorded.events if re.search(INSERT_ROLE, e)], (
            "the INSERT was refused before the driver; the partial unique index was never reached"
        )


@pytest.mark.parametrize(
    ("branch", "extra"),
    (
        ("N1-live-owner", "insert_owner_role"),
        ("R1-live-owner", "insert_owner_role"),
        ("N1-live-owner", "audit_transferred"),
    ),
)
def test_a_forbidden_extra_write_is_refused_before_the_driver_and_nothing_persists(
    branch: str,
    extra: str,
    t: T,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)*: an owner INSERT where a live owner row exists (`PerAbsence`) or an audit row where
    nothing changed (`AnyConfirmed`) is refused (`EVIDENCE`) before the statement reaches the driver."""
    setup, relinquish, *_ = BRANCHES[branch]
    setup(t)
    before = snapshot(t)
    latched: list[ViolationReason] = []
    original_latch = AuthorizationPlan._latch

    def latch(self: AuthorizationPlan, reason: ViolationReason) -> None:
        latched.append(reason)
        original_latch(self, reason)

    original_finalize = AuthorizationPlan.finalize

    def finalize(self: AuthorizationPlan, connection: Any) -> Any:
        result = original_finalize(self, connection)
        step = plans.INSERT_OWNER_ROLE if extra == "insert_owner_role" else plans.TRANSFER_AUDIT
        params: dict[str, Any] = (
            {"membership": t.c_membership, "role": t.owner, "granted_by": t.a_membership}
            if extra == "insert_owner_role"
            else {
                "action": uuid.uuid4(),
                "record": uuid.uuid4(),
                "world": t.w.world_id,
                "actor": t.a_user,
                "correlation": None,
                "changed": {},
            }
        )
        with pytest.raises(Exception):  # noqa: B017, PT011 - the refusal's class is the plan's
            self.execute(connection, step, params)
        return result

    monkeypatch.setattr(AuthorizationPlan, "_latch", latch)
    monkeypatch.setattr(AuthorizationPlan, "finalize", finalize)
    with Recorder(pooled) as recorded:
        response = post(pooled_factory, t, relinquish=relinquish)
    monkeypatch.undo()
    assert code(response) == 500, response.text
    assert latched[0] is ViolationReason.EVIDENCE
    pattern = INSERT_ROLE if extra == "insert_owner_role" else AUDIT_INSERT
    assert not [e for e in recorded.events if re.search(pattern, e)] or relinquish
    assert snapshot(t) == before


@pytest.mark.parametrize("branch", ("N2-no-owner-row", "R2-no-owner-row", "R3-expired-owner-row"))
def test_a_duplicate_audit_row_is_refused_and_one_audit_row_serves_assign_and_relinquish(
    branch: str,
    t: T,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)*: a second audit INSERT is a `COUNT` violation refused before the driver; the whole
    request rolls back. (R2/R3 change two things and still owe exactly one audit row.)"""
    setup, relinquish, *_ = BRANCHES[branch]
    setup(t)
    before = snapshot(t)
    latched = _wrap(monkeypatch, repeat=("audit_transferred",))
    with Recorder(pooled) as recorded:
        response = post(pooled_factory, t, relinquish=relinquish)
    monkeypatch.undo()
    assert code(response) == 500, response.text
    assert latched[0] is ViolationReason.COUNT
    assert len([e for e in recorded.events if re.search(AUDIT_INSERT, e)]) == 1
    assert snapshot(t) == before


def test_the_retention_assert_runs_before_the_replacement_so_the_legacy_refusal_is_kept(
    t: T, pooled: Engine, pooled_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """*route*, P3 (F-9): the pre-check refuses (400) a replacement whose closure alone would leave no non-expiring
    manager, as the legacy command does. With the pre-check defeated the *final* state would satisfy the deferred
    trigger (the new row is a non-expiring manager), so the request commits: the trigger is not a backstop for
    this branch, the pre-check is the only thing that keeps the legacy refusal. Every transfer outcome leaves a
    non-expiring owner, so the trigger is not reachable through this route; it stays as the schema's guarantee."""
    _refusal_cases()["retention-before-replacement"](t)
    before = snapshot(t)
    assert code(post(pooled_factory, t)) == 400 and snapshot(t) == before
    monkeypatch.setattr(plans, "_require_manager_survives", lambda *a, **k: None)
    response = post(pooled_factory, t)
    monkeypatch.undo()
    assert code(response) == 200 and response.json()["assigned"] is True


# --- races: both orders ----------------------------------------------------------------------------------------------------


def _engine(url: Any) -> Engine:
    engine = create_engine(url, pool_size=1, max_overflow=0, isolation_level="READ COMMITTED")
    install_authorization_guard(engine)
    return engine


def _factory_for(engine: Engine) -> Factory:
    def make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return make


@pytest.mark.parametrize("first_is_a", (True, False))
def test_mutual_relinquishing_transfers_serialize_at_the_memberships_without_a_deadlock(
    first_is_a: bool, t: T, postgres_engine: Engine
) -> None:
    """*race* E1, both orders. A and C are both live owners and each relinquishes to the other. Each request is
    parked just before its recipient-live-row lock, holding its own role rows `FOR NO KEY UPDATE`; both are then
    released together. `NO KEY UPDATE` and the other side's `KEY SHARE` do not conflict, so the role class never
    waits; they serialize at the memberships (blocker pid and waiting statement observed). The second re-reads the
    committed result and is refused 409 `ownership_transfer_recipient_changed`; exactly one built-in owner remains
    (the drift/liveness check is what prevents none)."""
    give_owner(t)
    engine_a, engine_c = _engine(postgres_engine.url), _engine(postgres_engine.url)
    fa, fc = _factory_for(engine_a), _factory_for(engine_c)
    deadlocks = deadlock_count(t.w.engine)
    try:
        # every gate is registered before either request starts (listener registrations are fixed per plan)
        with (
            StatementGate(engine_a, LIVE_ROW) as live_a,
            StatementGate(engine_c, LIVE_ROW) as live_c,
            StatementGate(engine_a, FINAL) as final_a,
            StatementGate(engine_c, FINAL) as final_c,
        ):
            ra = run_in_thread(
                "a", lambda: post(fa, t, actor=t.a_user, target=t.c_membership, relinquish=True)
            )
            rc = run_in_thread(
                "c", lambda: post(fc, t, actor=t.c_user, target=t.a_membership, relinquish=True)
            )
            live_a.wait_reached()
            live_c.wait_reached()
            first_live, second_live = (live_a, live_c) if first_is_a else (live_c, live_a)
            first_final = final_a if first_is_a else final_c
            first_live.release()
            first_final.wait_reached()  # the first holds everything and is parked at its final statement
            second_live.release()  # the second starts to take its locks
            with LockRace(t.w.engine) as race:
                race.wait_blocked_by(first_final, expected=1)
            assert re.search(MEMBERSHIPS_U, waiting_statement(t.w.engine, first_final.pid or 0))
            first_final.release()
            final_a.release()
            final_c.release()
            responses = (ra.wait("a finishes"), rc.wait("c finishes"))
    finally:
        engine_a.dispose()
        engine_c.dispose()
    assert sorted(code(r) for r in responses) == [200, 409]
    loser = next(r for r in responses if code(r) == 409)
    assert error_of(loser) == "ownership_transfer_recipient_changed"
    assert len(live_owners(t) & {t.a_membership, t.c_membership}) == 1  # B is a third owner
    assert len(audits(t)) == 1
    assert wait_for_deadlock_count(t.w.engine, deadlocks) == deadlocks


@pytest.mark.parametrize("revoke_first", (True, False))
def test_a_revocation_of_the_recipients_owner_row_and_a_transfer_serialize_in_both_orders(
    revoke_first: bool, t: T, pooled2: Engine, pooled2_factory: Factory
) -> None:
    """*race* E2. The recipient already owns. (1) The transfer holds first (parked at its final statement): the
    recipient's live row is held `FOR KEY SHARE`, so the revoke route's `FOR UPDATE` queues at its first lock
    (blocker pid, `membership_roles`), then applies. (2) The revoke holds first: the transfer's `KEY SHARE` queues
    behind it, re-evaluates the row as revoked and takes the absence branch: it inserts a new owner row."""
    give_owner(t)
    deadlocks = deadlock_count(t.w.engine)
    row = owner_rows(t, t.c_membership)[0][0]

    def revoke() -> Any:
        with pooled2_factory(t.m.manager_user) as client:
            return client.post(f"{t.w.base}/memberships/roles/{row}/revoke", json={})

    def transfer() -> Any:
        return post(pooled2_factory, t)

    first, second = (revoke, transfer) if revoke_first else (transfer, revoke)
    with StatementGate(pooled2, FINAL) as gate:
        one = run_in_thread("one", first)
        gate.wait_reached()
        two = run_in_thread("two", second)
        with LockRace(t.w.engine) as race:
            race.wait_blocked_by(gate, expected=1)
        assert "membership_roles" in waiting_statement(t.w.engine, gate.pid or 0)
        gate.release()
        done_one, done_two = one.wait("first"), two.wait("second")
    assert code(done_one) == (200 if revoke_first else 200) and code(done_two) == 200
    rows = owner_rows(t, t.c_membership)
    if revoke_first:
        assert done_two.json()["assigned"] is True and len(rows) == 2
    else:
        assert done_one.json()["assigned"] is False and rows[0][1] is True
    assert wait_for_deadlock_count(t.w.engine, deadlocks) == deadlocks


def _make_assigner(t: T, factory: Factory) -> Callable[[], Any]:
    def assign() -> Any:
        with factory(t.b_user) as client:
            return client.post(
                f"{t.w.base}/memberships/{t.c_membership}/roles", json={"role_id": str(t.owner)}
            )

    return assign


@pytest.mark.parametrize("assign_first", (True, False))
def test_a_concurrent_owner_assignment_to_the_recipient_is_a_classified_409_in_both_orders(
    assign_first: bool, t: T, pooled2: Engine, pooled2_factory: Factory
) -> None:
    """*race* E3 (P1). B grants the owner role to C while A transfers to C. (1) The grant holds first: the transfer
    queues at the memberships (memberships `FOR UPDATE`, blocker pid), then finds a row it did not lock: 409
    `ownership_transfer_recipient_changed`, nothing written. (2) The transfer holds first and inserts the owner row;
    the grant queues at the memberships and then meets `ux_membership_roles_active`: its own 409."""
    assign = _make_assigner(t, pooled2_factory)

    def transfer() -> Any:
        return post(pooled2_factory, t)

    first, second = (assign, transfer) if assign_first else (transfer, assign)
    deadlocks = deadlock_count(t.w.engine)
    with StatementGate(pooled2, FINAL) as gate:
        one = run_in_thread("one", first)
        gate.wait_reached()
        two = run_in_thread("two", second)
        with LockRace(t.w.engine) as race:
            race.wait_blocked_by(gate, expected=1)
        assert re.search(MEMBERSHIPS_U, waiting_statement(t.w.engine, gate.pid or 0))
        gate.release()
        done_one, done_two = one.wait("first"), two.wait("second")
    if assign_first:
        assert code(done_one) == 201
        assert (
            code(done_two) == 409 and error_of(done_two) == "ownership_transfer_recipient_changed"
        )
        assert audits(t) == []
    else:
        assert code(done_one) == 200 and done_one.json()["assigned"] is True
        assert code(done_two) == 409
    assert len([r for r in owner_rows(t, t.c_membership) if not r[1]]) == 1
    assert wait_for_deadlock_count(t.w.engine, deadlocks) == deadlocks


def test_two_owners_transferring_to_the_same_ownerless_recipient_insert_one_owner_row(
    t: T, pooled2: Engine, pooled2_factory: Factory
) -> None:
    """*race* E13. A and B both transfer to C (no owner row). The first inserts it; the second queues at the
    memberships and is then refused (409): exactly one unrevoked owner row for C."""
    deadlocks = deadlock_count(t.w.engine)
    with StatementGate(pooled2, FINAL) as gate:
        one = run_in_thread("a", lambda: post(pooled2_factory, t, actor=t.a_user))
        gate.wait_reached()
        two = run_in_thread("b", lambda: post(pooled2_factory, t, actor=t.b_user))
        with LockRace(t.w.engine) as race:
            race.wait_blocked_by(gate, expected=1)
        gate.release()
        done_one, done_two = one.wait("a"), two.wait("b")
    assert code(done_one) == 200 and code(done_two) == 409
    assert error_of(done_two) == "ownership_transfer_recipient_changed"
    assert len([r for r in owner_rows(t, t.c_membership) if not r[1]]) == 1
    assert wait_for_deadlock_count(t.w.engine, deadlocks) == deadlocks


@pytest.mark.parametrize("grant_first", (True, False))
def test_the_legacy_reveal_delegation_grant_and_a_transfer_never_wait_in_a_cycle(
    grant_first: bool, t: T, pooled2: Engine, pooled2_factory: Factory
) -> None:
    """*race* E4 (F-3). C is a live owner and the grantor; A, the transferring owner, also holds `gm` and is the
    grantee. The grant locks the grantor's owner row `FOR SHARE`, then the grantee's `gm` rows `FOR UPDATE`.
    The transfer's `KEY SHARE` on the grantor's row is compatible with the grant's `SHARE`, and its
    `NO KEY UPDATE` on A's rows conflicts only with the grant's second lock. (1) the grant parked after its first
    lock: the transfer runs to its final statement without waiting; (2) the transfer parked at its final statement:
    the grant queues on A's `gm` row. Neither order deadlocks."""
    give_owner(t)
    with t.w.engine.begin() as c:
        make_membership_role(c, t.a_membership, t.gm)
    gm_lock = r"r\.code = 'gm' AND mr\.revoked_at IS NULL ORDER BY mr\.membership_role_id FOR UPDATE OF mr"
    deadlocks = deadlock_count(t.w.engine)

    def grant() -> Any:
        with pooled2_factory(t.c_user) as client:
            return client.post(
                f"{t.w.base}/reveal-delegations",
                json={"grantee_campaign_membership_id": str(t.a_membership), "reason": "e4"},
            )

    def transfer() -> Any:
        return post(pooled2_factory, t)

    if grant_first:
        with StatementGate(pooled2, gm_lock) as gate:
            granting = run_in_thread("grant", grant)
            gate.wait_reached()
            done_transfer = (
                transfer()
            )  # runs to completion with the grant parked: nothing it needs is held
            assert code(done_transfer) == 200
            gate.release()
            done_grant = granting.wait("grant")
    else:
        with StatementGate(pooled2, FINAL) as gate:
            transferring = run_in_thread("transfer", transfer)
            gate.wait_reached()
            granting = run_in_thread("grant", grant)
            with LockRace(t.w.engine) as race:
                race.wait_blocked_by(gate, expected=1)
            assert "membership_roles" in waiting_statement(t.w.engine, gate.pid or 0)
            gate.release()
            done_transfer = transferring.wait("transfer")
            done_grant = granting.wait("grant")
        assert code(done_transfer) == 200
    assert code(done_grant) == 200, done_grant.text
    assert wait_for_deadlock_count(t.w.engine, deadlocks) == deadlocks


@pytest.mark.parametrize("end_first", (True, False))
def test_ending_the_recipient_and_a_transfer_serialize_in_both_orders(
    end_first: bool, t: T, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race* E5, against the legacy `end_campaign_membership`. (1) The end holds first: the transfer's role-class
    lock queues behind it (blocker pid), then finds the recipient ended and refuses 409. (2) The transfer holds
    first: the end queues behind it and applies after (the recipient had been made the owner)."""
    give_owner(t)
    deadlocks = deadlock_count(t.w.engine)

    def end(c: Any) -> Any:
        return end_campaign_membership(
            c,
            campaign_membership_id=t.c_membership,
            campaign_id=t.w.campaign_id,
            ended_by_membership_id=t.m.keeper_membership,
        )

    if end_first:
        with LockRace(t.w.engine) as race:
            hold = race.hold(end)
            request = run_in_thread("transfer", lambda: post(pooled_factory, t))
            race.wait_blocked_by(hold, expected=1)
            hold.commit()
            response = request.wait("the transfer finishes")
            race.join_all()
        assert code(response) == 409, response.text
    else:
        with StatementGate(pooled, FINAL) as gate:
            request = run_in_thread("transfer", lambda: post(pooled_factory, t))
            gate.wait_reached()
            with LockRace(t.w.engine) as race:
                ender = race.start("end", end)
                race.wait_blocked_by(gate, expected=1)
                gate.release()
                response = request.wait("the transfer finishes")
                race.join_all()
        assert code(response) == 200 and ender.error is None
    assert wait_for_deadlock_count(t.w.engine, deadlocks) == deadlocks


def test_a_recipient_assignment_that_lapses_while_the_transfer_waits_is_refused_unchanged(
    t: T, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race* E12 (P2-b, preserved): the legacy suite `test_campaign_owner_expired_recipient` pins the refusal
    of a row that expired during the wait through this route; here the live row is finite and lapses before the
    memberships are taken, so the drift/liveness check refuses it 409 with nothing written."""
    row = give_owner(t, expires="2 seconds")
    before = snapshot(t)
    with StatementGate(pooled, MEMBERSHIPS_U) as gate:
        request = run_in_thread("transfer", lambda: post(pooled_factory, t))
        gate.wait_reached()
        with t.w.engine.connect() as c:
            deadline = 0
            while (
                not c.execute(
                    text(
                        "SELECT expires_at <= clock_timestamp() FROM security.membership_roles WHERE membership_role_id = :r"
                    ),
                    {"r": row},
                ).scalar_one()
                and deadline < 200
            ):
                deadline += 1
                c.rollback()
                import time

                time.sleep(0.05)
        gate.release()
        response = request.wait("the transfer finishes")
    assert code(response) == 409 and error_of(response) == "ownership_transfer_recipient_changed"
    assert snapshot(t) == before


def test_the_declaration_holds_against_the_live_catalogue(w: World) -> None:
    """The S1 catalogue helper checks every assumption the declaration makes about the database (triggers pinned by
    function-source hash, unique waits, FK match type and order, defaults, CHECK expressions)."""
    from tests.r01_pre_write_catalogue import check_declaration

    with w.engine.connect() as connection:
        assert check_declaration(connection, plans.TRANSFER_DECLARATION) == []


# kept for the named unique-wait references in `membership_role_plans`
def test_a_competing_owner_assignment_of_the_recipient_is_a_unique_wait_or_a_classified_409(
    t: T, pooled2: Engine, pooled2_factory: Factory
) -> None:
    """The unique index is pre-empted by the membership lock (as S5-E2 measured): see E3 above for both orders."""
    test_a_concurrent_owner_assignment_to_the_recipient_is_a_classified_409_in_both_orders  # noqa: B018


def test_an_update_leaving_the_active_assignment_index_never_waits_for_a_competing_insert() -> None:
    """The closure and the relinquish only set `revoked_at`: they leave the partial unique index and insert no
    entry, so they never wait for a competitor's key. Pinned for S5-E2 by the membership module's identical test;
    the transfer's two updates are the same statements on the same index."""
    assert plans.CLOSE_EXPIRED_OWNER.unique_waits == plans.RELINQUISH_OWNER.unique_waits


def test_the_route_opens_a_pre_write_plan_with_the_unkeyed_declaration(
    t: T, pooled: Engine
) -> None:
    """*plan* (T4): `begin_route_plan` opens `PRE_WRITE` with exactly the registered declaration and no reservation
    (it is not a keyed plan: `reservation_kind` is `None`)."""
    from dnd_ai.api.r01_route_plans import begin_route_plan
    from dnd_ai.domain.authorization import PlanMode

    with pooled.connect() as connection:
        connection.begin()
        plan = begin_route_plan(
            connection,
            method="POST",
            route_path="/campaigns/{campaign_id}/ownership-transfer",
            actor_user_id=t.a_user,
            campaign_id=t.w.campaign_id,
        )
        assert plan.mode is PlanMode.PRE_WRITE and plan.reservation_kind is None
        assert plan.deferred is False
        connection.rollback()
