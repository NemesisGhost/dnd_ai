# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-E6: the reveal-delegation grant and revoke routes as unkeyed pre-write plans, over real HTTP.

`grant_character_reveal_delegation_endpoint` and `revoke_character_reveal_delegation_endpoint` take the caller's owner
row `FOR SHARE` and (grant) the grantee's `gm` row `FOR UPDATE` in one ascending-id pass, the memberships (the
grantee `FOR NO KEY UPDATE`, the caller `FOR KEY SHARE`), the grantee's delegation rows `FOR UPDATE` and (grant) the
campaign `FOR KEY SHARE`; they read and refuse before `plan.finalize`, then write through declared steps (grant: close
the stale delegation, insert `PerAbsence`, one audit row `AnyConfirmed`; revoke: close the live delegation, one audit
row `PerEvidence`). `commands.character_reveal` stays as the direct command and is the **oracle** here: each branch and
refusal is compared with what it returns or raises on the same state (inside a rolled-back transaction).

Evidence classes: **route** (a real HTTP request through the guard), **sql** (the recorded statement stream), **race**
(two real requests or a request and a competitor, each parked on a named statement; every wait is observed through
`pg_blocking_pids`, with the waiting statement), **mutation (test-side)** (`AuthorizationPlan.execute` wrapped to omit
or repeat a write, `finalize` defeated). Every delegation in the cascade tests is a real, bound row made by the route.
"""

import dataclasses
import re
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.commands import reveal_delegation_plans as plans
from dnd_ai.commands.character_reveal import (
    grant_character_reveal_delegation,
    revoke_character_reveal_delegation,
)
from dnd_ai.domain.authorization import AuthorizationPlan, StepOutcome, ViolationReason
from dnd_ai.domain.reveal_authority import resolve_reveal_authority
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
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
    make_membership_role,
    make_user,
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

OWNER_S = r"FROM security\.membership_roles WHERE .* FOR SHARE$"
GM_U = r"FROM security\.membership_roles WHERE .* FOR UPDATE$"
MEMBERSHIP_NKU = r"FROM security\.campaign_memberships WHERE .* FOR NO KEY UPDATE$"
MEMBERSHIP_KS = r"FROM security\.campaign_memberships WHERE .* FOR KEY SHARE$"
STALE_U = (
    r"FROM security\.character_reveal_delegations WHERE .*gm_membership_role_id != .* FOR UPDATE$"
)
MATCHING_U = (
    r"FROM security\.character_reveal_delegations WHERE .*gm_membership_role_id = .* FOR UPDATE$"
)
REVOKE_ROW_U = r"FROM security\.character_reveal_delegations WHERE .*campaign_id = .* FOR UPDATE$"
CAMPAIGN_KS = r"FROM campaign\.campaigns WHERE .* FOR KEY SHARE$"
UPDATE_DELEGATION = r"^UPDATE security\.character_reveal_delegations SET"
INSERT_DELEGATION = r"^INSERT INTO security\.character_reveal_delegations"
AUDIT_INSERT = r"^INSERT INTO audit\.change_log"
GRANT_COMMAND = "grant_character_reveal_delegation"
REVOKE_COMMAND = "revoke_character_reveal_delegation"
REASON = "Trusted to run the table's reveals"


@dataclasses.dataclass
class D:
    w: World
    m: Managers
    owner: uuid.UUID  # the built-in owner template
    gm: uuid.UUID  # the built-in gm template
    a_user: uuid.UUID  # built-in owner
    a_membership: uuid.UUID
    a_role: uuid.UUID
    b_user: uuid.UUID  # built-in owner
    b_membership: uuid.UUID
    b_role: uuid.UUID
    x_user: uuid.UUID  # built-in gm
    x_membership: uuid.UUID
    x_role: uuid.UUID
    y_user: uuid.UUID  # built-in gm
    y_membership: uuid.UUID
    y_role: uuid.UUID
    p_user: uuid.UUID  # a player
    p_membership: uuid.UUID


@pytest.fixture
def d(w: World) -> D:
    m = make_managers(w.engine, w.campaign_id, label="RD")
    with w.engine.begin() as c:
        owner = system_role_id(c, "campaign_owner")
        gm = system_role_id(c, "gm")
        player = system_role_id(c, "player")
        made = []
        for label, role in (("A", owner), ("B", owner), ("X", gm), ("Y", gm), ("P", player)):
            user = make_user(c, f"RD {label}")
            membership = make_campaign_membership(c, w.campaign_id, user)
            made.append((user, membership, make_membership_role(c, membership, role)))
    (a, b, x, y, p) = made
    return D(
        w,
        m,
        owner,
        gm,
        a[0],
        a[1],
        a[2],
        b[0],
        b[1],
        b[2],
        x[0],
        x[1],
        x[2],
        y[0],
        y[1],
        y[2],
        p[0],
        p[1],
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


def grant(
    factory: Factory,
    d: D,
    *,
    actor: uuid.UUID | None = None,
    grantee: uuid.UUID | None = None,
    reason: str = REASON,
    key: str | None = None,
) -> Any:
    headers = {"Idempotency-Key": key} if key else {}
    with factory(actor or d.a_user) as client:
        return client.post(
            f"{d.w.base}/reveal-delegations",
            json={
                "grantee_campaign_membership_id": str(grantee or d.x_membership),
                "reason": reason,
            },
            headers=headers,
        )


def revoke(
    factory: Factory,
    d: D,
    *,
    actor: uuid.UUID | None = None,
    grantee: uuid.UUID | None = None,
    reason: str = "No longer needed",
    key: str | None = None,
) -> Any:
    headers = {"Idempotency-Key": key} if key else {}
    with factory(actor or d.a_user) as client:
        return client.post(
            f"{d.w.base}/reveal-delegations/{grantee or d.x_membership}/revoke",
            json={"reason": reason},
            headers=headers,
        )


def delegations(d: D) -> list[dict[str, Any]]:
    with d.w.engine.connect() as c:
        return [
            dict(r)
            for r in c.execute(
                text(
                    "SELECT character_reveal_delegation_id AS id, grantee_campaign_membership_id AS grantee, "
                    "gm_membership_role_id AS gm_role, granted_by_membership_id AS granted_by, "
                    "revoked_at IS NULL AS live, end_reason, revoked_by_membership_id AS revoked_by, "
                    "revocation_reason, reason FROM security.character_reveal_delegations "
                    "WHERE campaign_id = :c ORDER BY granted_at, character_reveal_delegation_id"
                ),
                {"c": d.w.campaign_id},
            )
            .mappings()
            .all()
        ]


def live(d: D) -> list[dict[str, Any]]:
    return [r for r in delegations(d) if r["live"]]


def audits(d: D, command: str | None = None) -> list[dict[str, Any]]:
    commands = (command,) if command else (GRANT_COMMAND, REVOKE_COMMAND)
    with d.w.engine.connect() as c:
        return [
            dict(r)
            for r in c.execute(
                text(
                    "SELECT command_name, schema_name, table_name, record_id, entity_id, event_id, world_id, "
                    "actor_user_id, changed_fields, ca.code AS action FROM audit.change_log cl "
                    "JOIN audit.change_actions ca USING (change_action_id) WHERE cl.world_id = :w "
                    "AND cl.command_name = ANY(:n) ORDER BY change_log_id"
                ),
                {"w": d.w.world_id, "n": list(commands)},
            )
            .mappings()
            .all()
        ]


def snapshot(d: D) -> tuple[Any, ...]:
    """Everything a refused or no-op call must leave alone: delegations, role rows, every audit row of the world and
    the receipts."""
    with d.w.engine.connect() as c:
        roles = c.execute(
            text(
                "SELECT mr.membership_role_id, mr.revoked_at IS NULL FROM security.membership_roles mr "
                "JOIN security.campaign_memberships cm USING (campaign_membership_id) "
                "WHERE cm.campaign_id = :c ORDER BY 1"
            ),
            {"c": d.w.campaign_id},
        ).all()
        receipts = c.execute(
            text("SELECT count(*) FROM security.idempotent_requests WHERE campaign_id = :c"),
            {"c": d.w.campaign_id},
        ).scalar_one()
        every_audit = c.execute(
            text("SELECT count(*) FROM audit.change_log WHERE world_id = :w"), {"w": d.w.world_id}
        ).scalar_one()
    return (
        [tuple(r) for r in roles],
        receipts,
        every_audit,
        [tuple(r.values()) for r in delegations(d)],
    )


def legacy(d: D, call: Callable[[Any], Any]) -> tuple[Any, ...]:
    """What the direct command does on the current state, inside a transaction that is always rolled back."""
    with d.w.engine.connect() as c:
        transaction = c.begin()
        try:
            result = call(c)
            return ("ok", result)
        except Exception as error:
            status = getattr(
                error, "safe_status_code", 400 if isinstance(error, ValueError) else 500
            )
            return ("error", status, getattr(error, "safe_error_code", type(error).__name__))
        finally:
            transaction.rollback()


def legacy_grant(d: D, *, actor: uuid.UUID, grantee: uuid.UUID) -> tuple[Any, ...]:
    def call(c: Any) -> Any:
        r = grant_character_reveal_delegation(
            c,
            campaign_id=d.w.campaign_id,
            actor_membership_id=actor,
            grantee_campaign_membership_id=grantee,
            reason=REASON,
        )
        return (r.created, bool(r.replaced_stale_delegation_ids))

    return legacy(d, call)


def legacy_revoke(d: D, *, actor: uuid.UUID, grantee: uuid.UUID) -> tuple[Any, ...]:
    def call(c: Any) -> Any:
        r = revoke_character_reveal_delegation(
            c,
            campaign_id=d.w.campaign_id,
            actor_membership_id=actor,
            grantee_campaign_membership_id=grantee,
            reason="No longer needed",
        )
        return r.revoked

    return legacy(d, call)


def lapse_gm_row_keeping_delegation(d: D, membership: uuid.UUID, old_role: uuid.UUID) -> uuid.UUID:
    """The state a stale delegation comes from: the bound `gm` assignment is gone (revoked by raw SQL, which closes
    nothing) and the member holds a *new* assignment; returns the new assignment."""
    with d.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
            ),
            {"r": old_role},
        )
        return make_membership_role(c, membership, d.gm)


# --- branches --------------------------------------------------------------------------------------------------------


def test_a_first_grant_writes_exactly_one_delegation_bound_to_the_gm_row_and_one_audit_row(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the fresh grant. The direct command (run first, rolled back) says `created`; the route inserts ONE
    delegation bound to X's live `gm` row, granted by A, with the reason, and ONE audit row naming it."""
    expected = legacy_grant(d, actor=d.a_membership, grantee=d.x_membership)
    assert expected == ("ok", (True, False))
    response = grant(pooled_factory, d)
    assert code(response) == 200, response.text
    body = response.json()
    rows = delegations(d)
    assert len(rows) == 1 and rows[0]["live"]
    row = rows[0]
    assert body == {
        "grantee_campaign_membership_id": str(d.x_membership),
        "character_reveal_delegation_id": str(row["id"]),
        "granted": True,
    }
    assert (row["grantee"], row["gm_role"], row["granted_by"], row["reason"]) == (
        d.x_membership,
        d.x_role,
        d.a_membership,
        REASON,
    )
    assert (row["end_reason"], row["revoked_by"], row["revocation_reason"]) == (None, None, None)
    [audit] = audits(d)
    assert audit["command_name"] == GRANT_COMMAND and audit["action"] == "created"
    assert (audit["schema_name"], audit["table_name"]) == (
        "security",
        "character_reveal_delegations",
    )
    assert (
        audit["record_id"] == row["id"] and audit["entity_id"] is None and audit["event_id"] is None
    )
    assert audit["world_id"] == d.w.world_id and audit["actor_user_id"] == d.a_user
    assert audit["changed_fields"] == {
        "grantee_campaign_membership_id": str(d.x_membership),
        "gm_membership_role_id": str(d.x_role),
        "replaced_stale_delegation": False,
    }
    assert idle_in_transaction(d.w.engine) == 0


def test_a_repeated_grant_is_the_existing_delegation_no_op_and_writes_nothing(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: a live delegation already bound to the live `gm` row: `granted` false, the same id, no new row, no
    audit row, no reservation, the connection clean."""
    first = grant(pooled_factory, d)
    before = snapshot(d)
    assert legacy_grant(d, actor=d.a_membership, grantee=d.x_membership) == ("ok", (False, False))
    second = grant(pooled_factory, d)
    assert code(second) == 200 and second.json()["granted"] is False
    assert (
        second.json()["character_reveal_delegation_id"]
        == first.json()["character_reveal_delegation_id"]
    )
    assert snapshot(d) == before and len(audits(d)) == 1
    assert idle_in_transaction(d.w.engine) == 0


def test_a_grant_over_a_stale_delegation_closes_it_and_binds_a_new_one(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: X's bound `gm` assignment is gone and X holds a new one; the old delegation is still live. The grant
    closes it (`gm_assignment_lapsed`, no revoker) and inserts a new one bound to the new row; ONE audit row says
    `replaced_stale_delegation`."""
    first = grant(pooled_factory, d)
    old = first.json()["character_reveal_delegation_id"]
    new_role = lapse_gm_row_keeping_delegation(d, d.x_membership, d.x_role)
    assert legacy_grant(d, actor=d.a_membership, grantee=d.x_membership) == ("ok", (True, True))
    response = grant(pooled_factory, d)
    assert code(response) == 200 and response.json()["granted"] is True
    rows = {str(r["id"]): r for r in delegations(d)}
    assert len(rows) == 2
    assert rows[old]["live"] is False and rows[old]["end_reason"] == "gm_assignment_lapsed"
    assert rows[old]["revoked_by"] is None
    new = rows[response.json()["character_reveal_delegation_id"]]
    assert new["live"] and new["gm_role"] == new_role
    audit = audits(d, GRANT_COMMAND)[-1]
    assert audit["changed_fields"]["replaced_stale_delegation"] is True
    assert audit["record_id"] == new["id"] and len(audits(d, GRANT_COMMAND)) == 2


def test_self_delegation_by_an_owner_who_is_also_a_gm_is_one_delegation_and_one_membership_lock(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: A holds the owner row and a `gm` row; A delegates to A. One delegation, granted by and to A. The
    caller and the grantee are the same membership: it is locked `FOR NO KEY UPDATE` once and the weaker lock lands
    on the held row (no second wait, no deadlock with itself)."""
    with d.w.engine.begin() as c:
        a_gm = make_membership_role(c, d.a_membership, d.gm)
    with Recorder(pooled) as recorded:
        response = grant(pooled_factory, d, grantee=d.a_membership)
    assert code(response) == 200 and response.json()["granted"] is True
    [row] = delegations(d)
    assert (row["grantee"], row["granted_by"], row["gm_role"]) == (
        d.a_membership,
        d.a_membership,
        a_gm,
    )
    nku = [i for i, e in enumerate(recorded.events) if re.search(MEMBERSHIP_NKU, e)]
    ks = [i for i, e in enumerate(recorded.events) if re.search(MEMBERSHIP_KS, e)]
    assert len(nku) == 1 and len(ks) == 1 and nku[0] < ks[0], recorded.events


def test_a_revoke_closes_the_live_delegation_whoever_granted_it_with_one_audit_row(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: A grants, B (another owner) revokes: the grantor is provenance. The row is closed with the revoker,
    the reason and `revoked_by_owner`; ONE revoke audit row names it."""
    granted = grant(pooled_factory, d)
    assert legacy_revoke(d, actor=d.b_membership, grantee=d.x_membership) == ("ok", True)
    response = revoke(pooled_factory, d, actor=d.b_user)
    assert code(response) == 200 and response.json() == {
        "grantee_campaign_membership_id": str(d.x_membership),
        "revoked": True,
    }
    [row] = delegations(d)
    assert str(row["id"]) == granted.json()["character_reveal_delegation_id"]
    assert row["live"] is False and row["end_reason"] == "revoked_by_owner"
    assert (row["revoked_by"], row["revocation_reason"]) == (d.b_membership, "No longer needed")
    [audit] = audits(d, REVOKE_COMMAND)
    assert audit["action"] == "updated" and audit["record_id"] == row["id"]
    assert audit["actor_user_id"] == d.b_user and audit["world_id"] == d.w.world_id
    assert audit["changed_fields"] == {
        "grantee_campaign_membership_id": str(d.x_membership),
        "revoked": True,
    }
    assert (audit["schema_name"], audit["table_name"]) == (
        "security",
        "character_reveal_delegations",
    )
    assert len(audits(d)) == 2 and idle_in_transaction(d.w.engine) == 0


def test_a_revoke_of_a_member_with_no_live_delegation_is_a_no_op_that_writes_nothing(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: `revoked` false, no audit row, nothing changed (and the plan is satisfied with no write at all)."""
    before = snapshot(d)
    assert legacy_revoke(d, actor=d.a_membership, grantee=d.x_membership) == ("ok", False)
    response = revoke(pooled_factory, d)
    assert code(response) == 200 and response.json()["revoked"] is False
    assert snapshot(d) == before and audits(d) == []
    assert idle_in_transaction(d.w.engine) == 0


def test_a_regrant_after_a_revoke_is_a_fresh_delegation(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: grant, revoke, grant: three audit rows, two delegations (the first closed), one live."""
    one = grant(pooled_factory, d)
    assert code(revoke(pooled_factory, d)) == 200
    two = grant(pooled_factory, d)
    assert two.json()["granted"] is True
    assert (
        two.json()["character_reveal_delegation_id"] != one.json()["character_reveal_delegation_id"]
    )
    assert len(delegations(d)) == 2 and len(live(d)) == 1 and len(audits(d)) == 3


# --- refusals --------------------------------------------------------------------------------------------------------


def _grant_refusals() -> dict[str, Callable[[D], dict[str, Any]]]:
    def custom_access_manage_only(d: D) -> dict[str, Any]:
        """`access.manage` is only the route requirement: a custom holder is not a built-in owner."""
        return {"actor": d.m.manager_user, "actor_membership": d.m.manager_membership}

    def not_gm_player(d: D) -> dict[str, Any]:
        return {"grantee": d.p_membership}

    def expired_gm(d: D) -> dict[str, Any]:
        with d.w.engine.begin() as c:
            c.execute(text("SET LOCAL session_replication_role = replica"))
            c.execute(
                text(
                    "UPDATE security.membership_roles SET granted_at = now() - interval '2 hours', "
                    "expires_at = now() - interval '1 hour' WHERE membership_role_id = :r"
                ),
                {"r": d.x_role},
            )
        return {}

    def ended_gm(d: D) -> dict[str, Any]:
        with d.w.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE security.campaign_memberships SET ended_at = now() + interval '1 microsecond' "
                    "WHERE campaign_membership_id = :m"
                ),
                {"m": d.x_membership},
            )
        return {}

    def inactive_gm_account(d: D) -> dict[str, Any]:
        with d.w.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE security.users SET lifecycle_status_id = (SELECT lifecycle_status_id FROM "
                    "core.lifecycle_statuses WHERE code = 'inactive') WHERE user_id = :u"
                ),
                {"u": d.x_user},
            )
        return {}

    def nonexistent(d: D) -> dict[str, Any]:
        return {"grantee": uuid.uuid4()}

    def other_campaign(d: D) -> dict[str, Any]:
        with d.w.engine.begin() as c:
            owner = make_user(c, "RD Other Owner")
            authored = make_authored_world(c, owner_user_id=owner, name="RD Other World")
            other = make_authored_campaign(c, authored, name="RD Other Campaign")
            foreign = make_campaign_membership(c, other, make_user(c, "RD Foreign"))
        return {"grantee": foreign, "purge_owner": owner}

    return {
        "custom-access-manage-holder-is-not-the-owner": custom_access_manage_only,
        "grantee-is-a-player": not_gm_player,
        "grantee-gm-row-expired": expired_gm,
        "grantee-membership-ended": ended_gm,
        "grantee-account-inactive": inactive_gm_account,
        "nonexistent-grantee": nonexistent,
        "grantee-of-another-campaign": other_campaign,
    }


@pytest.mark.parametrize("case", sorted(_grant_refusals()))
def test_each_grant_refusal_matches_the_direct_command_and_persists_nothing(
    case: str, d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: precedence and classification preserved. The direct command on the same state says which refusal
    wins; the route returns the same status and code, nothing persists, the connection returns clean."""
    knobs = _grant_refusals()[case](d)
    try:
        actor = knobs.get("actor", d.a_user)
        actor_membership = knobs.get("actor_membership", d.a_membership)
        grantee = knobs.get("grantee", d.x_membership)
        expected = legacy_grant(d, actor=actor_membership, grantee=grantee)
        assert expected[0] == "error", expected
        before = snapshot(d)
        response = grant(pooled_factory, d, actor=actor, grantee=grantee)
        assert code(response) == expected[1], (response.text, expected)
        assert error_of(response) == expected[2], (response.text, expected)
        assert snapshot(d) == before
        assert idle_in_transaction(d.w.engine) == 0
    finally:
        if "purge_owner" in knobs:
            _purge_user_worlds(d.w.engine, knobs["purge_owner"])


def test_a_custom_access_manage_holder_is_refused_by_the_owner_gate_not_the_route_requirement(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the route dependency (`access.manage`) admits the custom manager (the refusal is NOT the capability
    check's 403); the operation's own authority refuses it 403 `campaign_owner_required` for the grant AND the
    revoke, and a live delegation granted by an owner stays."""
    grant(pooled_factory, d)
    before = snapshot(d)
    for response in (
        grant(pooled_factory, d, actor=d.m.manager_user, grantee=d.y_membership),
        revoke(pooled_factory, d, actor=d.m.manager_user),
    ):
        assert code(response) == 403 and error_of(response) == "campaign_owner_required"
    assert snapshot(d) == before


def _revoke_refusals() -> dict[str, Callable[[D], dict[str, Any]]]:
    return {
        "custom-access-manage-holder-is-not-the-owner": lambda d: {
            "actor": d.m.manager_user,
            "actor_membership": d.m.manager_membership,
        },
        "nonexistent-grantee": lambda d: {"grantee": uuid.uuid4()},
        "grantee-of-another-campaign": _grant_refusals()["grantee-of-another-campaign"],
    }


@pytest.mark.parametrize("case", sorted(_revoke_refusals()))
def test_each_revoke_refusal_matches_the_direct_command_and_persists_nothing(
    case: str, d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    grant(pooled_factory, d)
    knobs = _revoke_refusals()[case](d)
    try:
        actor = knobs.get("actor", d.a_user)
        actor_membership = knobs.get("actor_membership", d.a_membership)
        grantee = knobs.get("grantee", d.x_membership)
        expected = legacy_revoke(d, actor=actor_membership, grantee=grantee)
        assert expected[0] == "error", expected
        before = snapshot(d)
        response = revoke(pooled_factory, d, actor=actor, grantee=grantee)
        assert code(response) == expected[1], (response.text, expected)
        assert error_of(response) == expected[2], (response.text, expected)
        assert snapshot(d) == before
        assert idle_in_transaction(d.w.engine) == 0
    finally:
        if "purge_owner" in knobs:
            _purge_user_worlds(d.w.engine, knobs["purge_owner"])


def test_a_blank_reason_is_refused_before_anything_is_locked_or_written(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: a whitespace-only reason passes the request model and is refused by `normalize_reason`, first."""
    before = snapshot(d)
    with Recorder(pooled) as recorded:
        one = grant(pooled_factory, d, reason="   ")
        two = revoke(pooled_factory, d, reason="   ")
    assert code(one) in (400, 422) and code(two) in (400, 422)
    assert not [
        e for e in recorded.events if re.search(r"FOR (SHARE|UPDATE|KEY SHARE|NO KEY UPDATE)$", e)
    ]
    assert snapshot(d) == before and idle_in_transaction(d.w.engine) == 0


def test_an_idempotency_key_is_ignored_and_no_receipt_is_written(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: both routes stay unkeyed. The same key twice executes twice (grant, then the documented no-op;
    revoke, then the no-op), reserves nothing and replays nothing."""
    key = new_key()
    first, second = grant(pooled_factory, d, key=key), grant(pooled_factory, d, key=key)
    assert (first.json()["granted"], second.json()["granted"]) == (True, False)
    one, two = revoke(pooled_factory, d, key=key), revoke(pooled_factory, d, key=key)
    assert (one.json()["revoked"], two.json()["revoked"]) == (True, False)
    assert snapshot(d)[1] == 0 and len(audits(d)) == 2


# --- the plan ---------------------------------------------------------------------------------------------------------


def _position(events: list[str], patterns: list[str]) -> int:
    position = -1
    for pattern in patterns:
        found = [i for i, e in enumerate(events) if re.search(pattern, e) and i > position]
        assert found, f"{pattern!r} not found after {position}: {events}"
        position = found[0]
    return position


def test_the_grant_statement_order_is_the_documented_lock_order_and_only_declared_writes_follow_finalize(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*sql*: the owner row `FOR SHARE` and the `gm` row `FOR UPDATE` (ascending id), the two memberships, the stale
    and the matching delegation rows, the campaign, the reads, `finalize`; then the stale closure, the insert and ONE
    audit row, and COMMIT. Exercised on the widest branch (a stale replacement)."""
    grant(pooled_factory, d)
    new_gm_row = lapse_gm_row_keeping_delegation(d, d.x_membership, d.x_role)
    with Recorder(pooled) as recorded:
        response = grant(pooled_factory, d)
    assert code(response) == 200 and response.json()["granted"] is True
    events = recorded.events
    # the role class and the membership class are each ONE ascending-id pass: which comes first is the id order
    roles = [OWNER_S, GM_U] if d.a_role < new_gm_row else [GM_U, OWNER_S]
    memberships = (
        [MEMBERSHIP_NKU, MEMBERSHIP_KS]
        if d.x_membership < d.a_membership
        else [MEMBERSHIP_KS, MEMBERSHIP_NKU]
    )
    _position(events, [*roles, *memberships, STALE_U, MATCHING_U, CAMPAIGN_KS, FINAL])
    final = next(i for i, e in enumerate(events) if re.search(FINAL, e))
    after = events[final + 1 :]
    assert all(re.search(r"^(UPDATE|INSERT)|^COMMIT$", e) for e in after), after
    tail = [e for e in after if e != "COMMIT"]
    assert [bool(re.search(UPDATE_DELEGATION, e)) for e in tail[:1]] == [True], (
        "the closure precedes the insert"
    )
    assert len([e for e in tail if re.search(INSERT_DELEGATION, e)]) == 1
    assert len([e for e in tail if re.search(AUDIT_INSERT, e)]) == 1
    assert len([e for e in tail if re.search(UPDATE_DELEGATION, e)]) == 1


def test_the_revoke_statement_order_is_the_documented_lock_order_and_only_declared_writes_follow_finalize(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*sql*: the owner row `FOR SHARE`, the grantee's live delegation `FOR UPDATE`, the caller's membership `FOR KEY
    SHARE` (no campaign lock: nothing the revoke writes takes one), the reads, `finalize`; then the closure, ONE
    audit row, COMMIT."""
    grant(pooled_factory, d)
    with Recorder(pooled) as recorded:
        response = revoke(pooled_factory, d)
    assert code(response) == 200 and response.json()["revoked"] is True
    events = recorded.events
    _position(events, [OWNER_S, REVOKE_ROW_U, MEMBERSHIP_KS, FINAL])
    assert not [e for e in events if re.search(r"campaign\.campaigns .*FOR", e)]
    final = next(i for i, e in enumerate(events) if re.search(FINAL, e))
    tail = [e for e in events[final + 1 :] if e != "COMMIT"]
    assert [bool(re.search(UPDATE_DELEGATION, e)) for e in tail] == [True, False]
    assert len([e for e in tail if re.search(AUDIT_INSERT, e)]) == 1


@pytest.mark.parametrize("route", ("grant", "revoke"))
def test_a_handler_that_forgets_to_finalize_is_a_sanitized_500_that_persists_nothing(
    route: str, d: D, pooled: Engine, pooled_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """*mutation (test-side)*: `finalize` never runs; the first declared write is refused and nothing persists. The
    same pooled connection then serves a normal request (pooled reuse)."""
    if route == "revoke":
        grant(pooled_factory, d)
    before = snapshot(d)
    monkeypatch.setattr(AuthorizationPlan, "finalize", lambda self, connection: None)
    response = (
        grant(pooled_factory, d, grantee=d.y_membership)
        if route == "grant"
        else revoke(pooled_factory, d)
    )
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error"
    assert snapshot(d) == before and idle_in_transaction(d.w.engine) == 0
    assert code(grant(pooled_factory, d, grantee=d.y_membership)) == 200


def _wrap(
    monkeypatch: pytest.MonkeyPatch,
    *,
    skip: tuple[str, ...] = (),
    repeat: tuple[str, ...] = (),
) -> list[ViolationReason]:
    """Test-side wrapper of the plan: omit or repeat a write; returns the latched reasons, first first."""
    original = AuthorizationPlan.execute
    latched: list[ViolationReason] = []
    original_latch = AuthorizationPlan._latch

    def latch(self: AuthorizationPlan, reason: ViolationReason) -> None:
        latched.append(reason)
        original_latch(self, reason)

    def wrapper(self: AuthorizationPlan, connection: Any, step: Any, params: Any) -> StepOutcome:
        if step.name in skip:
            return StepOutcome(step=step.name, keys=((uuid.uuid4(),),))
        outcome = original(self, connection, step, params)
        if step.name in repeat:
            original(self, connection, step, params)
        return outcome

    monkeypatch.setattr(AuthorizationPlan, "execute", wrapper)
    monkeypatch.setattr(AuthorizationPlan, "_latch", latch)
    return latched


def _prepare_branch(d: D, pooled_factory: Factory, branch: str) -> tuple[str, Callable[[], Any]]:
    """(route, call) for each branch of the declarations."""
    if branch == "grant-fresh":
        return "grant", lambda: grant(pooled_factory, d)
    if branch == "grant-stale":
        grant(pooled_factory, d)
        lapse_gm_row_keeping_delegation(d, d.x_membership, d.x_role)
        return "grant", lambda: grant(pooled_factory, d)
    if branch == "grant-existing":
        grant(pooled_factory, d)
        return "grant", lambda: grant(pooled_factory, d)
    if branch == "revoke-live":
        grant(pooled_factory, d)
        return "revoke", lambda: revoke(pooled_factory, d)
    return "revoke", lambda: revoke(pooled_factory, d)  # revoke-none


@pytest.mark.parametrize(
    ("branch", "skipped"),
    (
        ("grant-fresh", "insert_delegation"),
        ("grant-fresh", "audit_delegation_granted"),
        ("grant-stale", "close_stale_delegation"),
        ("grant-stale", "insert_delegation"),
        ("grant-stale", "audit_delegation_granted"),
        ("revoke-live", "revoke_delegation"),
        ("revoke-live", "audit_delegation_revoked"),
    ),
)
def test_an_omitted_required_write_never_commits(
    branch: str,
    skipped: str,
    d: D,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)*: each required write is owed by the locked state. Omitting the closure of a stale
    delegation, the delegation INSERT, the revocation or either audit row leaves a plan the guard refuses: a
    sanitized 500, everything rolled back. (The wrapper returns a fake key for the omitted step so the route
    continues to the next declared write.)"""
    _route, call = _prepare_branch(d, pooled_factory, branch)
    before = snapshot(d)
    latched = _wrap(monkeypatch, skip=(skipped,))
    response = call()
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error", response.text
    assert latched, "the guard latched"
    assert snapshot(d) == before and idle_in_transaction(d.w.engine) == 0


@pytest.mark.parametrize(
    ("branch", "extra"),
    (
        ("grant-existing", "insert_delegation"),
        ("grant-existing", "audit_delegation_granted"),
        ("grant-fresh", "close_stale_delegation"),
        ("revoke-none", "revoke_delegation"),
        ("revoke-none", "audit_delegation_revoked"),
    ),
)
def test_a_forbidden_extra_write_is_refused_before_the_driver_and_nothing_persists(
    branch: str,
    extra: str,
    d: D,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)*: a delegation INSERT where a live one is already bound (`PerAbsence`), an audit row
    where nothing changed (`AnyConfirmed`, `PerEvidence`), a closure with nothing stale (`EachLockedRow`) or a
    revocation with nothing live is refused (`EVIDENCE` or `TARGET`) before the statement reaches the driver."""
    _route, call = _prepare_branch(d, pooled_factory, branch)
    before = snapshot(d)
    latched: list[ViolationReason] = []
    original_latch = AuthorizationPlan._latch
    original_finalize = AuthorizationPlan.finalize
    steps = {
        "insert_delegation": (
            plans.INSERT_DELEGATION,
            {
                "campaign": d.w.campaign_id,
                "grantee": d.x_membership,
                "gm": d.x_role,
                "actor_membership": d.a_membership,
                "reason": "x",
            },
        ),
        "audit_delegation_granted": (
            plans.GRANT_AUDIT,
            {
                "action": uuid.uuid4(),
                "record": uuid.uuid4(),
                "world": d.w.world_id,
                "actor": d.a_user,
                "correlation": None,
                "changed": {},
            },
        ),
        "audit_delegation_revoked": (
            plans.REVOKE_AUDIT,
            {
                "action": uuid.uuid4(),
                "record": uuid.uuid4(),
                "world": d.w.world_id,
                "actor": d.a_user,
                "correlation": None,
                "changed": {},
            },
        ),
        "close_stale_delegation": (plans.CLOSE_STALE_DELEGATION, {"delegation": uuid.uuid4()}),
        "revoke_delegation": (
            plans.REVOKE_DELEGATION,
            {"delegation": uuid.uuid4(), "actor_membership": d.a_membership, "why": "x"},
        ),
    }

    def latch(self: AuthorizationPlan, reason: ViolationReason) -> None:
        latched.append(reason)
        original_latch(self, reason)

    def finalize(self: AuthorizationPlan, connection: Any) -> Any:
        result = original_finalize(self, connection)
        step, params = steps[extra]
        with pytest.raises(Exception):  # noqa: B017, PT011 - the refusal's class is the plan's
            self.execute(connection, step, params)
        return result

    monkeypatch.setattr(AuthorizationPlan, "_latch", latch)
    monkeypatch.setattr(AuthorizationPlan, "finalize", finalize)
    with Recorder(pooled) as recorded:
        response = call()
    monkeypatch.undo()
    assert code(response) == 500, response.text
    assert latched and latched[0] in (ViolationReason.EVIDENCE, ViolationReason.TARGET_NOT_LOCKED)
    assert (
        not [
            e
            for e in recorded.events
            if re.search(INSERT_DELEGATION, e)
            or re.search(UPDATE_DELEGATION, e)
            or re.search(AUDIT_INSERT, e)
        ]
        or branch == "grant-fresh"
    ), recorded.events
    assert snapshot(d) == before and idle_in_transaction(d.w.engine) == 0


@pytest.mark.parametrize(
    ("branch", "repeated"),
    (
        ("grant-fresh", "audit_delegation_granted"),
        ("grant-fresh", "insert_delegation"),
        ("revoke-live", "audit_delegation_revoked"),
        ("revoke-live", "revoke_delegation"),
    ),
)
def test_a_duplicated_write_is_refused_and_everything_rolls_back(
    branch: str,
    repeated: str,
    d: D,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)*: a second INSERT or UPDATE of a declared step is a `COUNT` violation refused before
    the driver: the whole request rolls back (the audit row is exactly one)."""
    _route, call = _prepare_branch(d, pooled_factory, branch)
    before = snapshot(d)
    latched = _wrap(monkeypatch, repeat=(repeated,))
    with Recorder(pooled) as recorded:
        response = call()
    monkeypatch.undo()
    assert code(response) == 500, response.text
    assert latched and latched[0] in (ViolationReason.COUNT, ViolationReason.DUPLICATE_TARGET)
    assert len([e for e in recorded.events if re.search(AUDIT_INSERT, e)]) <= 1
    assert snapshot(d) == before and idle_in_transaction(d.w.engine) == 0


@pytest.mark.parametrize("failing", ("insert_delegation", "audit_delegation_granted"))
def test_a_failure_of_a_later_write_rolls_back_the_earlier_ones(
    failing: str, d: D, pooled: Engine, pooled_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """*route (rollback)*: the stale closure runs, then (a) the INSERT fails or (b) the audit row fails (the last
    write): neither the closure, nor the delegation, nor anything else persists, and the same pooled connection
    serves the next request."""
    grant(pooled_factory, d)
    lapse_gm_row_keeping_delegation(d, d.x_membership, d.x_role)
    before = snapshot(d)
    original = AuthorizationPlan.execute
    ran: list[str] = []

    def wrapper(self: AuthorizationPlan, connection: Any, step: Any, params: Any) -> StepOutcome:
        if step.name == failing and failing == "insert_delegation":
            raise RuntimeError("injected failure before the insert")
        outcome = original(self, connection, step, params)
        ran.append(step.name)
        if step.name == failing:
            raise RuntimeError("injected failure after the audit row")
        return outcome

    monkeypatch.setattr(AuthorizationPlan, "execute", wrapper)
    response = grant(pooled_factory, d)
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error", response.text
    assert "close_stale_delegation" in ran, "the earlier write really ran before the failure"
    assert snapshot(d) == before and idle_in_transaction(d.w.engine) == 0
    assert code(grant(pooled_factory, d)) == 200


def test_a_live_delegation_the_two_locks_did_not_cover_is_the_recipient_changed_refusal(
    d: D, pooled: Engine, pooled_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """*mutation (test-side)*: the drift check is what makes the empty `PerAbsence` evidence mean "none at all". The
    state it guards is unreachable through the locks (a competing delegation needs the `gm` row `FOR KEY SHARE`, which
    the grant's `FOR UPDATE` excludes), so it is made reachable here: the unlocked read reports a delegation the locks
    did not return. The grant refuses 409 `reveal_delegation_recipient_changed` before `finalize` and writes nothing."""
    before = snapshot(d)
    real = plans._live_delegations
    monkeypatch.setattr(
        plans,
        "_live_delegations",
        lambda connection, grantee: {*real(connection, grantee), uuid.uuid4()},
    )
    response = grant(pooled_factory, d)
    monkeypatch.undo()
    assert code(response) == 409 and error_of(response) == "reveal_delegation_recipient_changed"
    assert snapshot(d) == before and idle_in_transaction(d.w.engine) == 0
    assert code(grant(pooled_factory, d)) == 200


# --- the cascade: positive fixtures with real bound delegations -------------------------------------------------------


def _authority(d: D, membership: uuid.UUID) -> Any:
    with d.w.engine.connect() as c:
        return resolve_reveal_authority(
            c, campaign_id=d.w.campaign_id, campaign_membership_id=membership
        )


def test_the_delegation_gives_reveal_authority_until_the_route_revokes_it(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route + resolver*: the row the route binds is what `resolve_reveal_authority` reads (a positive fixture, not
    an empty-set comparison): authority `delegation` after the grant, `none` after the revoke."""
    assert _authority(d, d.x_membership) == "none"
    grant(pooled_factory, d)
    assert _authority(d, d.x_membership) == "delegation"
    revoke(pooled_factory, d)
    assert _authority(d, d.x_membership) == "none"


def test_a_role_revoke_closes_the_delegation_the_route_made_and_a_regrant_needs_a_new_gm_row(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route x route*: revoking X's `gm` assignment (the S5-E2 route) closes the bound delegation
    (`gm_role_revoked`); authority is gone; a grant is then refused 409 (no live `gm` row)."""
    grant(pooled_factory, d)
    with pooled_factory(d.m.manager_user) as client:
        response = client.post(f"{d.w.base}/memberships/roles/{d.x_role}/revoke", json={})
    assert code(response) == 200, response.text
    [row] = delegations(d)
    assert row["live"] is False and row["end_reason"] == "gm_role_revoked"
    assert _authority(d, d.x_membership) == "none"
    refused = grant(pooled_factory, d)
    assert code(refused) == 409 and error_of(refused) == "reveal_delegation_recipient_not_gm"


def test_changing_the_gm_assignment_closes_the_delegation_the_route_made(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    grant(pooled_factory, d)
    with pooled_factory(d.m.manager_user) as client:
        response = client.post(
            f"{d.w.base}/memberships/roles/{d.x_role}/change",
            json={"new_role_id": str(system_role_id_of(d, "player"))},
        )
    assert code(response) == 201, response.text
    [row] = delegations(d)
    assert row["live"] is False and row["end_reason"] == "gm_role_changed"


def system_role_id_of(d: D, role_code: str) -> uuid.UUID:
    with d.w.engine.connect() as c:
        return system_role_id(c, role_code)


def test_ending_the_gms_membership_closes_the_delegation_but_not_ones_it_granted(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route x route*: B holds the owner role AND a `gm` row and is the grantee of A; X is a grantee of B. Ending B's
    membership closes B's own delegation (`membership_ended`) and leaves the one B granted to X."""
    with d.w.engine.begin() as c:
        make_membership_role(c, d.b_membership, d.gm)
    assert code(grant(pooled_factory, d, actor=d.a_user, grantee=d.b_membership)) == 200
    assert code(grant(pooled_factory, d, actor=d.b_user, grantee=d.x_membership)) == 200
    with pooled_factory(d.m.keeper_user) as client:
        response = client.post(f"{d.w.base}/memberships/{d.b_membership}/end", json={})
    assert code(response) == 200, response.text
    rows = {r["grantee"]: r for r in delegations(d)}
    assert (
        rows[d.b_membership]["live"] is False
        and rows[d.b_membership]["end_reason"] == "membership_ended"
    )
    assert rows[d.x_membership]["live"] is True
    # the grantor lost its membership: the survivor is provenance only, still bound to X's gm row
    assert rows[d.x_membership]["granted_by"] in (d.b_membership, None)


def test_a_delegation_outlives_its_grantor_losing_ownership_and_the_new_owner_can_revoke_it(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route x route*: A grants, then A relinquishes ownership to B through the transfer route; the delegation stays
    live (the grantor is provenance) and B revokes it."""
    grant(pooled_factory, d)
    with pooled_factory(d.a_user) as client:
        moved = client.post(
            f"{d.w.base}/ownership-transfer",
            json={
                "target_campaign_membership_id": str(d.b_membership),
                "relinquish_own_ownership": True,
            },
        )
    assert code(moved) == 200, moved.text
    assert len(live(d)) == 1 and _authority(d, d.x_membership) == "delegation"
    assert code(grant(pooled_factory, d, actor=d.a_user, grantee=d.y_membership)) == 403
    assert code(revoke(pooled_factory, d, actor=d.b_user)) == 200 and live(d) == []


# --- the declaration --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("which", ("GRANT_DECLARATION", "REVOKE_DECLARATION"))
def test_the_declaration_holds_against_the_live_catalogue(which: str, w: World) -> None:
    """The S1 catalogue helper checks every assumption the declaration makes about the database (triggers pinned by
    function-source hash, unique waits, FK match type and order, defaults, CHECK expressions)."""
    from tests.r01_pre_write_catalogue import check_declaration

    with w.engine.connect() as connection:
        assert check_declaration(connection, getattr(plans, which)) == []


def test_the_routes_open_a_pre_write_plan_with_their_unkeyed_declaration(
    d: D, pooled: Engine
) -> None:
    """*plan*: `begin_route_plan` opens `PRE_WRITE` with exactly the registered declaration and no reservation."""
    from dnd_ai.api.r01_pre_write_routes import R01_UNKEYED_PRE_WRITE_ROUTES
    from dnd_ai.api.r01_route_plans import begin_route_plan
    from dnd_ai.domain.authorization import PlanMode

    for path, declaration in (
        ("/campaigns/{campaign_id}/reveal-delegations", plans.GRANT_DECLARATION),
        (
            "/campaigns/{campaign_id}/reveal-delegations/{grantee_campaign_membership_id}/revoke",
            plans.REVOKE_DECLARATION,
        ),
    ):
        with pooled.connect() as connection:
            connection.begin()
            plan = begin_route_plan(
                connection,
                method="POST",
                route_path=path,
                actor_user_id=d.a_user,
                campaign_id=d.w.campaign_id,
            )
            assert plan.mode is PlanMode.PRE_WRITE and plan.reservation_kind is None
            assert plan.deferred is False
            assert path in {p for _, p in R01_UNKEYED_PRE_WRITE_ROUTES}
            assert R01_UNKEYED_PRE_WRITE_ROUTES[("POST", path)] is declaration
            connection.rollback()


def test_a_competing_delegation_for_the_same_grantee_is_a_unique_wait_then_a_classified_409(
    d: D,
) -> None:
    """The named `UniqueWait` of the INSERT step (`ux_character_reveal_delegations_live`). A competing delegation
    for the same grantee needs the grantee's `gm` row `FOR KEY SHARE` for its foreign key, which the grant's `FOR
    UPDATE` excludes, so every competitor that follows the lock order queues on that row *before* it can reach the
    index (the two-owners race below: the second finds the first's delegation and is a no-op). A writer outside the
    protocol (a raw INSERT) would meet the index first and deadlock with the grant; none exists in the code base
    (the legacy command locks the same rows in the same order). The step declares the wait and the closure that
    leaves the index is pinned by the S5-E2 test it names."""
    wait = next(iter(plans.INSERT_DELEGATION.unique_waits))
    assert wait.index == "security.ux_character_reveal_delegations_live"
    assert wait.competitor_test.endswith(
        "test_a_competing_delegation_for_the_same_grantee_is_a_unique_wait_then_a_classified_409"
    )
    assert d.w.campaign_id  # the fixture is only here so the module's database fixtures run


# --- races: both orders ------------------------------------------------------------------------------------------------


def _race(
    d: D,
    pooled2: Engine,
    first: Callable[[], Any],
    second: Callable[[], Any],
    *,
    blocked: bool = True,
    waiting: str | None = None,
) -> tuple[Any, Any]:
    """`first` runs to its final statement and parks there, holding everything it locked; `second` starts; when
    `blocked` it is observed blocked by `first`'s backend (and, with `waiting`, on a statement matching it); then
    `first` is released. Returns (first's response, second's response)."""
    deadlocks = deadlock_count(d.w.engine)
    with StatementGate(pooled2, FINAL) as gate:
        one = run_in_thread("one", first)
        gate.wait_reached()
        two = run_in_thread("two", second)
        if blocked:
            with LockRace(d.w.engine) as race:
                race.wait_blocked_by(gate, expected=1)
            if waiting is not None:
                assert re.search(waiting, waiting_statement(d.w.engine, gate.pid or 0)), waiting
        else:
            two_response = two.wait("the second needs nothing the first holds")
            gate.release()
            return one.wait("first"), two_response
        gate.release()
        done_one, done_two = one.wait("first"), two.wait("second")
    assert wait_for_deadlock_count(d.w.engine, deadlocks) == deadlocks
    return done_one, done_two


def _role_revoke(factory: Factory, d: D, role: uuid.UUID) -> Callable[[], Any]:
    def call() -> Any:
        with factory(d.m.manager_user) as client:
            return client.post(f"{d.w.base}/memberships/roles/{role}/revoke", json={})

    return call


@pytest.mark.parametrize("a_first", (True, False))
def test_two_owners_granting_the_same_grantee_serialize_at_the_gm_row(
    a_first: bool, d: D, pooled2: Engine, pooled2_factory: Factory
) -> None:
    """*race*, both orders: the second queues on X's `gm` row (`FOR UPDATE`, blocker pid, waiting statement) and
    then finds the first's delegation bound to the live row: `granted` false, ONE delegation, ONE audit row."""
    one_user, two_user = (d.a_user, d.b_user) if a_first else (d.b_user, d.a_user)
    first, second = _race(
        d,
        pooled2,
        lambda: grant(pooled2_factory, d, actor=one_user),
        lambda: grant(pooled2_factory, d, actor=two_user),
        waiting=r"membership_roles",
    )
    assert (code(first), first.json()["granted"]) == (200, True)
    assert (code(second), second.json()["granted"]) == (200, False)
    assert len(live(d)) == 1 and len(audits(d, GRANT_COMMAND)) == 1


@pytest.mark.parametrize("revoke_first", (True, False))
def test_a_grant_and_a_revocation_of_the_gm_assignment_serialize_in_both_orders(
    revoke_first: bool, d: D, pooled2: Engine, pooled2_factory: Factory
) -> None:
    """*race*, both orders, against the S5-E2 revoke route. (1) The revoke holds first: the grant queues on the `gm`
    row (blocker pid, `membership_roles`) and is then refused 409 (no live `gm` row), nothing written. (2) The grant
    holds first: the revoke queues on the same row and then closes the NEW delegation (`gm_role_revoked`)."""
    role_revoke = _role_revoke(pooled2_factory, d, d.x_role)
    if revoke_first:
        first, second = _race(
            d, pooled2, role_revoke, lambda: grant(pooled2_factory, d), waiting=r"membership_roles"
        )
        assert code(first) == 200 and code(second) == 409
        assert error_of(second) == "reveal_delegation_recipient_not_gm"
        assert delegations(d) == [] and audits(d, GRANT_COMMAND) == []
    else:
        first, second = _race(
            d, pooled2, lambda: grant(pooled2_factory, d), role_revoke, waiting=r"membership_roles"
        )
        assert code(first) == 200 and first.json()["granted"] is True and code(second) == 200
        [row] = delegations(d)
        assert row["live"] is False and row["end_reason"] == "gm_role_revoked"
        assert len(audits(d, GRANT_COMMAND)) == 1


@pytest.mark.parametrize("change_first", (True, False))
def test_a_grant_and_a_role_change_of_the_gm_assignment_serialize_in_both_orders(
    change_first: bool, d: D, pooled2: Engine, pooled2_factory: Factory
) -> None:
    """*race*, both orders, against the S5-E2 change route: the same shape with `gm_role_changed`."""
    player = system_role_id_of(d, "player")

    def change() -> Any:
        with pooled2_factory(d.m.manager_user) as client:
            return client.post(
                f"{d.w.base}/memberships/roles/{d.x_role}/change", json={"new_role_id": str(player)}
            )

    if change_first:
        first, second = _race(
            d, pooled2, change, lambda: grant(pooled2_factory, d), waiting=r"membership_roles"
        )
        assert code(first) == 201 and code(second) == 409 and delegations(d) == []
    else:
        first, second = _race(
            d, pooled2, lambda: grant(pooled2_factory, d), change, waiting=r"membership_roles"
        )
        assert code(first) == 200 and code(second) == 201
        [row] = delegations(d)
        assert row["live"] is False and row["end_reason"] == "gm_role_changed"


@pytest.mark.parametrize("end_first", (True, False))
def test_a_grant_and_the_end_of_the_grantees_membership_serialize_in_both_orders(
    end_first: bool, d: D, pooled2: Engine, pooled2_factory: Factory
) -> None:
    """*race*, both orders, against the S5-E3 end route: ended first, the grant is refused 409; granted first, the end
    closes the new delegation (`membership_ended`)."""

    def end() -> Any:
        with pooled2_factory(d.m.keeper_user) as client:
            return client.post(f"{d.w.base}/memberships/{d.x_membership}/end", json={})

    if end_first:
        first, second = _race(
            d, pooled2, end, lambda: grant(pooled2_factory, d), waiting=r"membership"
        )
        assert code(first) == 200 and code(second) in (404, 409), second.text
        assert live(d) == []
    else:
        first, second = _race(
            d, pooled2, lambda: grant(pooled2_factory, d), end, waiting=r"membership"
        )
        assert code(first) == 200 and code(second) == 200, second.text
        [row] = delegations(d)
        assert row["live"] is False and row["end_reason"] == "membership_ended"


@pytest.mark.parametrize("transfer_first", (True, False))
def test_a_grant_and_a_relinquishing_transfer_by_the_grantor_serialize_in_both_orders(
    transfer_first: bool, d: D, pooled2: Engine, pooled2_factory: Factory
) -> None:
    """*race*, both orders (owner loss across the wait). (1) A's transfer to B holds first: the grant queues on A's
    owner row (blocker pid) and is then refused 403 `campaign_owner_required`, nothing written. (2) The grant holds
    first: the transfer's `NO KEY UPDATE` queues behind the owner row's `FOR SHARE`, applies after, and the
    delegation stays."""

    def transfer() -> Any:
        with pooled2_factory(d.a_user) as client:
            return client.post(
                f"{d.w.base}/ownership-transfer",
                json={
                    "target_campaign_membership_id": str(d.b_membership),
                    "relinquish_own_ownership": True,
                },
            )

    if transfer_first:
        first, second = _race(
            d, pooled2, transfer, lambda: grant(pooled2_factory, d), waiting=r"membership_roles"
        )
        assert code(first) == 200 and code(second) == 403
        assert error_of(second) == "campaign_owner_required" and delegations(d) == []
    else:
        first, second = _race(
            d, pooled2, lambda: grant(pooled2_factory, d), transfer, waiting=r"membership_roles"
        )
        assert code(first) == 200 and code(second) == 200
        assert len(live(d)) == 1 and len(audits(d, GRANT_COMMAND)) == 1


@pytest.mark.parametrize("revoke_first", (True, False))
def test_a_revoke_and_a_grant_of_the_same_grantee_serialize_in_both_orders(
    revoke_first: bool, d: D, pooled2: Engine, pooled2_factory: Factory
) -> None:
    """*race*, both orders. An old delegation exists. (1) B's revoke holds first (the delegation `FOR UPDATE`): A's
    grant queues on that row (blocker pid, `character_reveal_delegations`), then finds none live and inserts a new
    one. (2) A's grant is a no-op (the delegation is bound to the live row) and holds the same delegation row: B's
    revoke queues on it and then revokes. Either way: one live or none, the audit rows say what happened."""
    grant(pooled2_factory, d, actor=d.a_user)
    if revoke_first:
        first, second = _race(
            d,
            pooled2,
            lambda: revoke(pooled2_factory, d, actor=d.b_user),
            lambda: grant(pooled2_factory, d, actor=d.a_user),
            waiting=r"character_reveal_delegations",
        )
        assert first.json()["revoked"] is True and second.json()["granted"] is True
        assert len(live(d)) == 1 and len(delegations(d)) == 2
    else:
        first, second = _race(
            d,
            pooled2,
            lambda: grant(pooled2_factory, d, actor=d.a_user),
            lambda: revoke(pooled2_factory, d, actor=d.b_user),
            waiting=r"character_reveal_delegations",
        )
        assert first.json()["granted"] is False and second.json()["revoked"] is True
        assert live(d) == [] and len(delegations(d)) == 1


@pytest.mark.parametrize("a_first", (True, False))
def test_two_revokes_of_the_same_delegation_close_it_once_in_both_orders(
    a_first: bool, d: D, pooled2: Engine, pooled2_factory: Factory
) -> None:
    """*race*, both orders: the second queues on the delegation row (blocker pid), then finds nothing live: a no-op
    (`revoked` false). One closure, ONE revoke audit row."""
    grant(pooled2_factory, d)
    one, two = (d.a_user, d.b_user) if a_first else (d.b_user, d.a_user)
    first, second = _race(
        d,
        pooled2,
        lambda: revoke(pooled2_factory, d, actor=one),
        lambda: revoke(pooled2_factory, d, actor=two),
        waiting=r"character_reveal_delegations",
    )
    assert first.json()["revoked"] is True and second.json()["revoked"] is False
    assert len(audits(d, REVOKE_COMMAND)) == 1 and live(d) == []


@pytest.mark.parametrize("revoke_first", (True, False))
def test_a_revoke_and_the_revocation_of_the_bound_gm_assignment_serialize_in_both_orders(
    revoke_first: bool, d: D, pooled2: Engine, pooled2_factory: Factory
) -> None:
    """*race*, both orders, against the S5-E2 revoke route, with a real bound delegation. (1) The delegation revoke
    holds first: the role revoke queues on the delegation row and then has nothing to close (`revoked_by_owner`
    stays). (2) The role revoke holds first and closes the delegation (`gm_role_revoked`): the delegation revoke
    queues on the row and is then a no-op."""
    grant(pooled2_factory, d)
    role_revoke = _role_revoke(pooled2_factory, d, d.x_role)
    if revoke_first:
        first, second = _race(
            d,
            pooled2,
            lambda: revoke(pooled2_factory, d),
            role_revoke,
            waiting=r"character_reveal_delegations",
        )
        assert first.json()["revoked"] is True and code(second) == 200
        assert delegations(d)[0]["end_reason"] == "revoked_by_owner"
    else:
        first, second = _race(
            d,
            pooled2,
            role_revoke,
            lambda: revoke(pooled2_factory, d),
            waiting=r"character_reveal_delegations",
        )
        assert code(first) == 200 and second.json()["revoked"] is False
        assert delegations(d)[0]["end_reason"] == "gm_role_revoked"
        assert audits(d, REVOKE_COMMAND) == []


def _wait_lapsed(d: D, role: uuid.UUID) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        with d.w.engine.connect() as c:
            if c.execute(
                text(
                    "SELECT expires_at <= clock_timestamp() FROM security.membership_roles WHERE membership_role_id = :r"
                ),
                {"r": role},
            ).scalar_one():
                return
        time.sleep(0.05)
    raise AssertionError("the assignment did not lapse")


def _finite(d: D, role: uuid.UUID, seconds: int) -> None:
    with d.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = now() + make_interval(secs => :s) WHERE membership_role_id = :r"
            ),
            {"s": seconds, "r": role},
        )


@pytest.mark.parametrize("who", ("grantee-gm-row", "caller-owner-row"))
def test_an_assignment_that_lapses_while_the_request_waits_is_refused_at_a_fresh_instant(
    who: str, d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race* (DEF-013 across the waits): the request parks at its campaign lock with every other lock held; the
    grantee's `gm` row (or the caller's owner row) lapses; released, the fresh-instant reads refuse it (409
    `reveal_delegation_recipient_not_gm`, or 403 `campaign_owner_required`) with nothing written."""
    role = d.x_role if who == "grantee-gm-row" else d.a_role
    _finite(d, role, 3)
    before = snapshot(d)
    with StatementGate(pooled, CAMPAIGN_KS) as gate:
        request = run_in_thread("grant", lambda: grant(pooled_factory, d))
        gate.wait_reached()
        _wait_lapsed(d, role)
        gate.release()
        response = request.wait("the grant finishes")
    if who == "grantee-gm-row":
        assert code(response) == 409 and error_of(response) == "reveal_delegation_recipient_not_gm"
    else:
        assert code(response) == 403 and error_of(response) == "campaign_owner_required"
    assert snapshot(d) == before


def test_a_revoke_whose_callers_owner_assignment_lapses_while_it_waits_is_refused_at_a_fresh_instant(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race* (DEF-013 across the waits, revoke): the request parks at its last lock (the caller's membership); the
    caller's owner row lapses; released, the fresh-instant read refuses it 403 `campaign_owner_required` with the
    delegation still live. (The route requirement alone is not the answer: the refusal is the operation's own.)"""
    grant(pooled_factory, d, actor=d.b_user)
    _finite(d, d.a_role, 3)
    before = snapshot(d)
    with StatementGate(pooled, MEMBERSHIP_KS) as gate:
        request = run_in_thread("revoke", lambda: revoke(pooled_factory, d))
        gate.wait_reached()
        _wait_lapsed(d, d.a_role)
        gate.release()
        response = request.wait("the revoke finishes")
    assert code(response) == 403 and error_of(response) == "campaign_owner_required"
    assert snapshot(d) == before and len(live(d)) == 1


def test_a_gm_row_that_appears_after_discovery_is_the_approved_recipient_changed_refusal(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*: the grantee holds no `gm` row at discovery; the request parks at its first lock; a `gm` row is
    assigned (committed); released, the live `gm` row is not among the rows locked in the role pass: 409
    `reveal_delegation_recipient_changed`, nothing written; a retry grants."""
    with d.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
            ),
            {"r": d.y_role},
        )
    with StatementGate(pooled, OWNER_S) as gate:
        request = run_in_thread("grant", lambda: grant(pooled_factory, d, grantee=d.y_membership))
        gate.wait_reached()
        with d.w.engine.begin() as c:
            make_membership_role(c, d.y_membership, d.gm)
        before = snapshot(
            d
        )  # the new assignment is part of the state; the refused grant must leave the rest
        gate.release()
        response = request.wait("the grant finishes")
    assert code(response) == 409 and error_of(response) == "reveal_delegation_recipient_changed"
    assert snapshot(d) == before and delegations(d) == []
    assert code(grant(pooled_factory, d, grantee=d.y_membership)) == 200
