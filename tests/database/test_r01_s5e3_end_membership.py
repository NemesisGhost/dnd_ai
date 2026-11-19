# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-E3: end campaign membership as a keyed-optional pre-write plan, over real HTTP and real connections.

The route (`dnd_ai.commands.membership_end_plans`) takes the actor's and the target's role rows in one ascending
pass (the actor's S, the target's U), the target's live delegation, the actor's open membership S and the target
membership U, the actor's account, the campaign (U for a removal, KS for the no-op), then every dependent row of
the member U (relationships, grants, group memberships, targeting revelations, snapshot rows), the receipt; it
judges authority at `plan.finalize` and only then writes through declared steps.

Evidence classes (labelled in each docstring), as in the S5-E2 modules:

- **route**: a real HTTP request through the guard on a one-connection pool.
- **sql**: the recorded statement stream of such a request (`Recorder`).
- **race**: a route request on one side and a competitor on the other, each held on a named statement or an open
  transaction; every wait is observed through `pg_blocking_pids`, never assumed.
- **mutation (test-side)**: `AuthorizationPlan.execute` is wrapped to omit or repeat a write, to show that the
  declared obligations refuse it. Nothing production-side is changed.

The shared authoring harness cannot establish transaction, deferral, lock or COMMIT guarantees (it shares one
transaction and never commits); none of this module uses it.
"""

import dataclasses
import re
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.domain.authorization import AuthorizationPlan
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures used by name
    FINAL,
    FINAL_RE,
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
    Scene,
    m,
    pooled2,
    pooled2_factory,
    s,
)
from tests.factories import (
    make_access_group,
    make_access_group_membership,
    make_campaign_membership,
    make_character,
    make_membership_character_relationship,
    make_membership_role,
    make_resource_grant,
    make_user,
)
from tests.http_race_support import new_key
from tests.r01_s5d_support import revoke_role

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]
KEYED = pytest.mark.parametrize("keyed", (True, False), ids=("keyed", "unkeyed"))
COMMAND = "end_campaign_membership"

KEY_LOCK = r"pg_advisory_xact_lock"
ROLES_S = r"FROM security\.membership_roles WHERE .* FOR SHARE$"
ROLE_ROW_U = r"FROM security\.membership_roles WHERE .*membership_role_id = %\(row\)s.* FOR UPDATE$"
DELEGATIONS_U = r"FROM security\.character_reveal_delegations WHERE .* FOR UPDATE$"
MEMBERSHIP_S = r"FROM security\.campaign_memberships WHERE .* FOR SHARE$"
MEMBERSHIP_U = r"FROM security\.campaign_memberships WHERE .* FOR UPDATE$"
ACCOUNT_S = r"FROM security\.users WHERE .* FOR SHARE$"
CAMPAIGN_U = r"FROM campaign\.campaigns WHERE campaign\.campaigns\.campaign_id = %\(campaign\)s::UUID FOR UPDATE$"
CAMPAIGN_KS = r"FROM campaign\.campaigns WHERE .* FOR KEY SHARE$"
RELATIONSHIPS_U = r"FROM security\.membership_character_relationships WHERE .* FOR UPDATE$"
GRANTS_U = r"FROM security\.resource_grants WHERE .* FOR UPDATE$"
GROUPS_U = r"FROM security\.access_group_memberships WHERE .* FOR UPDATE$"
REVELATIONS_U = r"FROM security\.character_revelations WHERE .* FOR UPDATE$"
SNAPSHOT_U = r"FROM security\.character_revelation_members WHERE .* FOR UPDATE$"
RECEIPT_U = r"FROM security\.idempotent_requests WHERE .*idempotent_request_id = %\(receipt\)s::UUID FOR UPDATE"
AUDIT_INSERT = r"^INSERT INTO audit\.change_log"
RECEIPT_UPDATE = r"^UPDATE security\.idempotent_requests"
UPDATE_ROLE = r"^UPDATE security\.membership_roles SET revoked_at"
UPDATE_DELEGATION = r"^UPDATE security\.character_reveal_delegations"
UPDATE_RELATIONSHIP = r"^UPDATE security\.membership_character_relationships"
UPDATE_GRANT = r"^UPDATE security\.resource_grants"
UPDATE_GROUP = r"^UPDATE security\.access_group_memberships"
UPDATE_REVELATION = r"^UPDATE security\.character_revelations"
UPDATE_SNAPSHOT = r"^UPDATE security\.character_revelation_members"
UPDATE_MEMBERSHIP = r"^UPDATE security\.campaign_memberships"

#: Step names of the declaration, in the order the writes run.
STEPS = (
    "end_revoke_role",
    "end_close_delegation",
    "end_revoke_relationship",
    "end_revoke_grant",
    "end_remove_group_membership",
    "end_close_revelation",
    "end_remove_revelation_member",
    "end_membership",
    "audit_membership_ended",
)


# --- the member being ended ----------------------------------------------------------------------------------------


@dataclasses.dataclass
class Member:
    """A membership holding one row of every kind the cascade closes."""

    user: uuid.UUID
    membership: uuid.UUID
    player_row: uuid.UUID
    gm_row: uuid.UUID
    delegation: uuid.UUID | None
    relationship: uuid.UUID
    relationship_type: uuid.UUID
    capability: uuid.UUID
    grant: uuid.UUID
    group: uuid.UUID
    group_membership: uuid.UUID
    revelation: uuid.UUID
    snapshot_revelation: uuid.UUID
    snapshot_row: uuid.UUID
    character: uuid.UUID

    def role_rows(self) -> list[uuid.UUID]:
        return sorted((self.player_row, self.gm_row))


def build_member(sc: Scene, label: str = "S5E3 Member", *, with_delegation: bool = True) -> Member:
    """A member with two role rows (player, gm), the live delegation bound to the gm row, a character relationship,
    a resource grant as grantee, an access-group membership, a revelation that targets the member and a
    campaign_current revelation with the member's snapshot row."""
    with sc.w.engine.begin() as c:
        user = make_user(c, label)
        membership = make_campaign_membership(c, sc.w.campaign_id, user)
        player_row = make_membership_role(c, membership, sc.player)
        gm_row = make_membership_role(c, membership, sc.gm)
        delegation = (
            c.execute(
                text(
                    "INSERT INTO security.character_reveal_delegations (campaign_id, "
                    "grantee_campaign_membership_id, gm_membership_role_id, granted_by_membership_id, "
                    "reason) VALUES (:c, :g, :r, :a, 'x') RETURNING character_reveal_delegation_id"
                ),
                {"c": sc.w.campaign_id, "g": membership, "r": gm_row, "a": sc.m.keeper_membership},
            ).scalar_one()
            if with_delegation
            else None
        )
        character = make_character(c, sc.w.world_id, name=f"{label} character")
        # a seeded type (a test must not add rows to the seed lookup that other tests assert exactly)
        relationship_type = c.execute(
            text(
                "SELECT character_relationship_type_id FROM security.character_relationship_types WHERE code = 'portrayer'"
            )
        ).scalar_one()
        relationship = make_membership_character_relationship(
            c,
            membership,
            character,
            relationship_type,
            granted_by_membership_id=sc.m.keeper_membership,
        )
        capability = c.execute(
            text(
                "SELECT capability_id FROM security.capabilities WHERE code = 'character.view_summary'"
            )
        ).scalar_one()
        grant = make_resource_grant(
            c,
            sc.w.campaign_id,
            capability,
            grantee_campaign_membership_id=membership,
            character_id=character,
            granted_by_membership_id=sc.m.keeper_membership,
        )
        group = make_access_group(c, sc.w.campaign_id, name=f"{label} group")
        group_membership = make_access_group_membership(c, group, membership)
        # a revelation needs a public-profile release of its character and a snapshot row is added only by the
        # transaction that created the revelation; the fixture writes both with triggers off (test setup only)
        c.execute(text("SET LOCAL session_replication_role = replica"))
        revelation = _revelation(c, sc, character, "member", member=membership)
        snapshot_revelation = _revelation(c, sc, character, "campaign_current")
        snapshot_row = c.execute(
            text(
                "INSERT INTO security.character_revelation_members "
                "(character_revelation_id, campaign_id, campaign_membership_id) VALUES (:r, :c, :m) "
                "RETURNING character_revelation_member_id"
            ),
            {"r": snapshot_revelation, "c": sc.w.campaign_id, "m": membership},
        ).scalar_one()
        c.execute(text("SET LOCAL session_replication_role = origin"))
    return Member(
        user,
        membership,
        player_row,
        gm_row,
        delegation,
        relationship,
        relationship_type,
        capability,
        grant,
        group,
        group_membership,
        revelation,
        snapshot_revelation,
        snapshot_row,
        character,
    )


def _revelation(
    c: Any, sc: Scene, character: uuid.UUID, kind: str, *, member: uuid.UUID | None = None
) -> uuid.UUID:
    value = c.execute(
        text(
            "INSERT INTO security.character_revelations (campaign_id, character_id, "
            "revelation_audience_kind_id, target_campaign_membership_id, created_by_membership_id, "
            "authority_source_code, reason) VALUES (:campaign, :character, (SELECT "
            "revelation_audience_kind_id FROM security.revelation_audience_kinds WHERE code = :kind), "
            ":member, :creator, 'owner', 'because') RETURNING character_revelation_id"
        ),
        {
            "campaign": sc.w.campaign_id,
            "character": character,
            "kind": kind,
            "member": member,
            "creator": sc.m.keeper_membership,
        },
    ).scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


@pytest.fixture
def e(s: Scene) -> Member:
    return build_member(s)


@pytest.fixture(autouse=True)
def _tidy_end(w: World) -> Any:
    yield
    with w.engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM audit.change_log WHERE world_id = :w AND command_name = :c"),
            {"w": w.world_id, "c": COMMAND},
        )


# --- helpers ------------------------------------------------------------------------------------------------------


def end(
    factory: Factory,
    sc: Scene,
    target: uuid.UUID,
    *,
    key: str | None = None,
    actor: uuid.UUID | None = None,
) -> Any:
    headers = {"Idempotency-Key": key} if key else {}
    with factory(actor or sc.m.manager_user) as client:
        return client.post(f"{sc.w.base}/memberships/{target}/end", headers=headers)


@dataclasses.dataclass
class State:
    """Everything the route can persist for one member, plus the audit rows and the key's receipt."""

    membership: tuple[Any, ...]
    roles: list[tuple[Any, ...]]
    delegations: list[tuple[Any, ...]]
    relationships: list[tuple[Any, ...]]
    grants: list[tuple[Any, ...]]
    groups: list[tuple[Any, ...]]
    revelations: list[tuple[Any, ...]]
    snapshots: list[tuple[Any, ...]]
    audits: list[tuple[Any, ...]]
    receipt: tuple[Any, ...]


def state(sc: Scene, member: uuid.UUID, key: str | None = None) -> State:
    with sc.w.engine.connect() as c:

        def rows(sql: str) -> list[tuple[Any, ...]]:
            return [
                tuple(r) for r in c.execute(text(sql), {"m": member, "c": sc.w.campaign_id}).all()
            ]

        membership = rows(
            "SELECT ended_at IS NOT NULL, ended_by_membership_id, (SELECT code FROM "
            "security.membership_statuses s WHERE s.membership_status_id = cm.membership_status_id) "
            "FROM security.campaign_memberships cm WHERE campaign_membership_id = :m"
        )[0]
        receipt = (
            c.execute(
                text(
                    "SELECT response_status_code, response_body, completed_at IS NOT NULL "
                    "FROM security.idempotent_requests WHERE campaign_id = :c AND idempotency_key = :k"
                ),
                {"c": sc.w.campaign_id, "k": key},
            ).one_or_none()
            if key
            else None
        )
        return State(
            membership,
            rows(
                "SELECT membership_role_id, revoked_at IS NOT NULL FROM security.membership_roles "
                "WHERE campaign_membership_id = :m ORDER BY 1"
            ),
            rows(
                "SELECT character_reveal_delegation_id, revoked_at IS NOT NULL, end_reason FROM "
                "security.character_reveal_delegations WHERE grantee_campaign_membership_id = :m ORDER BY 1"
            ),
            rows(
                "SELECT membership_character_relationship_id, revoked_at IS NOT NULL FROM "
                "security.membership_character_relationships WHERE campaign_membership_id = :m ORDER BY 1"
            ),
            rows(
                "SELECT resource_grant_id, revoked_at IS NOT NULL FROM security.resource_grants "
                "WHERE grantee_campaign_membership_id = :m ORDER BY 1"
            ),
            rows(
                "SELECT access_group_membership_id, removed_at IS NOT NULL FROM "
                "security.access_group_memberships WHERE campaign_membership_id = :m ORDER BY 1"
            ),
            rows(
                "SELECT character_revelation_id, ended_at IS NOT NULL, end_reason FROM "
                "security.character_revelations WHERE target_campaign_membership_id = :m ORDER BY 1"
            ),
            rows(
                "SELECT character_revelation_member_id, removed_at IS NOT NULL, removal_reason FROM "
                "security.character_revelation_members WHERE campaign_membership_id = :m ORDER BY 1"
            ),
            rows(
                "SELECT command_name, table_name, record_id, previous_status, new_status, changed_fields "
                "FROM audit.change_log WHERE command_name = 'end_campaign_membership' "
                "AND record_id = :m ORDER BY change_log_id"
            ),
            tuple(receipt) if receipt else (),
        )


def open_dependents(sc: Scene, member: uuid.UUID) -> dict[str, int]:
    """Rows of the member that are still open (the completeness invariant: all zero once it is ended)."""
    with sc.w.engine.connect() as c:
        return {
            name: int(c.execute(text(sql), {"m": member}).scalar_one())
            for name, sql in {
                "roles": "SELECT count(*) FROM security.membership_roles WHERE campaign_membership_id = :m AND revoked_at IS NULL",
                "delegations": "SELECT count(*) FROM security.character_reveal_delegations WHERE grantee_campaign_membership_id = :m AND revoked_at IS NULL",
                "relationships": "SELECT count(*) FROM security.membership_character_relationships WHERE campaign_membership_id = :m AND revoked_at IS NULL",
                "grants": "SELECT count(*) FROM security.resource_grants WHERE grantee_campaign_membership_id = :m AND revoked_at IS NULL",
                "groups": "SELECT count(*) FROM security.access_group_memberships WHERE campaign_membership_id = :m AND removed_at IS NULL",
                "revelations": "SELECT count(*) FROM security.character_revelations WHERE target_campaign_membership_id = :m AND ended_at IS NULL",
                "snapshots": "SELECT count(*) FROM security.character_revelation_members WHERE campaign_membership_id = :m AND removed_at IS NULL",
            }.items()
        }


def index(events: list[str], pattern: str, start: int = 0) -> int:
    matches = [i for i, x in enumerate(events) if i >= start and re.search(pattern, x)]
    assert matches, f"no statement matches {pattern!r}: {events}"
    return matches[0]


def audit_row(sc: Scene, member: uuid.UUID) -> list[tuple[Any, ...]]:
    with sc.w.engine.connect() as c:
        return [
            tuple(r)
            for r in c.execute(
                text(
                    "SELECT table_name, previous_status, new_status, actor_user_id, changed_fields "
                    "FROM audit.change_log WHERE command_name = 'end_campaign_membership' "
                    "AND record_id = :m ORDER BY change_log_id"
                ),
                {"m": member},
            ).all()
        ]


def writes_of(events: list[str]) -> list[str]:
    return [x for x in events if x.startswith(("INSERT", "UPDATE", "DELETE"))]


def remove_keeper(sc: Scene) -> None:
    """The keeper's access.manage lapses a day from now: the manager becomes the only non-expiring holder."""
    with sc.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = now() + interval '1 day' "
                "WHERE campaign_membership_id IN (SELECT campaign_membership_id FROM "
                "security.campaign_memberships WHERE campaign_id = :c) AND membership_role_id <> :mgr"
            ),
            {"c": sc.w.campaign_id, "mgr": sc.m.manager_role},
        )


def restore_keeper(sc: Scene) -> None:
    with sc.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = NULL WHERE campaign_membership_id = :k"
            ),
            {"k": sc.m.keeper_membership},
        )


# --- success, no-op, invalid targets -------------------------------------------------------------------------------


@KEYED
def test_a_manager_ends_a_member_and_every_dependent_row_closes_with_one_audit_row(
    keyed: bool, s: Scene, e: Member, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: 200 and the echoed id; the membership closed by the actor with the `revoked` status; every role,
    delegation, relationship, grant, group membership, targeting revelation and snapshot row of the member closed
    (never deleted) with the documented reason; exactly one audit row naming the closed ids; a receipt only for a
    keyed request, whose body is the response."""
    key = new_key() if keyed else None
    before = state(s, e.membership, key)
    assert before.membership == (False, None, "active") and before.audits == []
    assert all(count > 0 for count in open_dependents(s, e.membership).values())
    response = end(pooled_factory, s, e.membership, key=key)
    assert code(response) == 200, response.text
    assert response.json() == {"campaign_membership_id": str(e.membership)}
    after = state(s, e.membership, key)
    assert after.membership == (True, s.m.manager_membership, "revoked")
    assert after.roles == [(r, True) for r in e.role_rows()]
    assert after.delegations == [(e.delegation, True, "membership_ended")]
    assert after.relationships == [(e.relationship, True)]
    assert after.grants == [(e.grant, True)]
    assert after.groups == [(e.group_membership, True)]
    assert after.revelations == [(e.revelation, True, "target_membership_ended")]
    assert after.snapshots == [(e.snapshot_row, True, "membership_ended")]
    assert set(open_dependents(s, e.membership).values()) == {0}
    [(table, previous, new, actor, changed)] = audit_row(s, e.membership)
    assert (table, previous, new, actor) == (
        "campaign_memberships",
        "active",
        "revoked",
        s.m.manager_user,
    )
    assert changed == {
        "revoked_membership_role_ids": [str(r) for r in e.role_rows()],
        "revoked_membership_character_relationship_ids": [str(e.relationship)],
        "revoked_resource_grant_ids": [str(e.grant)],
        "removed_access_group_membership_ids": [str(e.group_membership)],
        "closed_character_revelation_ids": [str(e.revelation)],
        "removed_character_revelation_member_ids": [str(e.snapshot_row)],
    }
    assert after.receipt == ((200, response.json(), True) if keyed else ())
    assert idle_in_transaction(s.w.engine) == 0


def test_rows_of_other_members_and_the_delegations_the_member_granted_stay_open(
    s: Scene, e: Member, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the cascade closes only rows naming this membership. Another member's rows (all seven kinds), among
    them a delegation the ended member *granted*, are untouched."""
    other = build_member(s, "S5E3 Other")
    with s.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.character_reveal_delegations SET granted_by_membership_id = :g "
                "WHERE character_reveal_delegation_id = :d"
            ),
            {"g": e.membership, "d": other.delegation},
        )
    before_other = open_dependents(s, other.membership)
    assert code(end(pooled_factory, s, e.membership, key=new_key())) == 200
    assert open_dependents(s, other.membership) == before_other
    assert state(s, other.membership).membership[0] is False


@KEYED
def test_ending_an_already_ended_membership_writes_nothing_and_a_keyed_one_completes_its_receipt(
    keyed: bool, s: Scene, e: Member, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* and *sql*: the legitimate no-op. No update, no audit row; the campaign is locked `FOR KEY SHARE` (a
    removal takes `FOR UPDATE`) and no dependent row is locked; a fresh keyed no-op still completes its receipt
    exactly once and replays it; a second audit row never appears for one real removal."""
    assert code(end(pooled_factory, s, e.membership, key=new_key())) == 200
    after_first = state(s, e.membership)
    key = new_key() if keyed else None
    with Recorder(pooled) as recorded:
        response = end(pooled_factory, s, e.membership, key=key)
    assert code(response) == 200 and response.json() == {
        "campaign_membership_id": str(e.membership)
    }
    after = state(s, e.membership, key)
    assert after.roles == after_first.roles and after.audits == after_first.audits
    assert len(after.audits) == 1
    events = recorded.events
    assert [x for x in writes_of(events) if "idempotent_requests" not in x] == []
    assert len([x for x in events if re.search(RECEIPT_UPDATE, x)]) == (1 if keyed else 0)
    assert any(re.search(CAMPAIGN_KS, x) for x in events)
    assert not any(re.search(CAMPAIGN_U, x) for x in events)
    # the role and delegation classes precede the membership in the order, so they ran (and found nothing); the
    # dependent classes follow the campaign and are locked only for a removal
    for pattern in (RELATIONSHIPS_U, GRANTS_U, GROUPS_U, REVELATIONS_U, SNAPSHOT_U):
        assert not any(re.search(pattern, x) for x in events), pattern
    if keyed:
        assert after.receipt == (200, response.json(), True)
        again = end(pooled_factory, s, e.membership, key=key)
        assert code(again) == 200 and again.json() == response.json()
        assert state(s, e.membership, key).audits == after_first.audits


@KEYED
def test_invalid_targets_keep_their_errors_persist_nothing_and_the_key_is_reusable(
    keyed: bool, s: Scene, e: Member, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: a membership that does not exist and one of another campaign are the same 404 `not_found` as before,
    after the caller's authority is judged; nothing persists, no key is consumed, the connection returns clean."""
    from tests.factories import make_campaign

    with s.w.engine.begin() as c:
        timeline = c.execute(
            text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": s.w.campaign_id},
        ).scalar_one()
        other_campaign = make_campaign(c, timeline, lifecycle_status_code="pending")
        foreign = make_campaign_membership(c, other_campaign, make_user(c, "S5E3 Foreign"))
    key = new_key() if keyed else None
    for target in (uuid.uuid4(), foreign):
        before = state(s, e.membership, key)
        response = end(pooled_factory, s, target, key=key)
        assert code(response) == 404 and error_of(response) == "not_found", response.text
        assert state(s, e.membership, key) == before
        assert idle_in_transaction(s.w.engine) == 0
    with s.w.engine.connect() as c:
        assert c.execute(
            text(
                "SELECT ended_at IS NULL FROM security.campaign_memberships "
                "WHERE campaign_membership_id = :m"
            ),
            {"m": foreign},
        ).scalar_one()
    assert code(end(pooled_factory, s, e.membership, key=key)) == 200


def test_a_caller_without_access_manage_is_refused_before_the_target_is_looked_up(
    s: Scene, e: Member, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: precedence is unchanged. A player learns nothing about the target: the same 403 for a member and for a
    membership that does not exist."""
    mine = end(pooled_factory, s, e.membership, actor=e.user)
    absent = end(pooled_factory, s, uuid.uuid4(), actor=e.user)
    assert code(mine) == code(absent) and code(mine) in (403, 404)
    assert error_of(mine) == error_of(absent)
    assert state(s, e.membership).membership[0] is False and idle_in_transaction(s.w.engine) == 0


# --- self-end, retention ---------------------------------------------------------------------------------------------


@KEYED
def test_a_manager_may_end_their_own_membership_when_another_manager_survives(
    keyed: bool, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: self-end is judged against the authority held before the command (the final check runs before any
    write), so it succeeds; the keeper survives; the actor's own role rows close; the membership names the actor as
    its ender; the same caller is then refused."""
    key = new_key() if keyed else None
    target = s.m.manager_membership
    response = end(pooled_factory, s, target, key=key)
    assert code(response) == 200, response.text
    after = state(s, target, key)
    assert after.membership == (True, target, "revoked")
    assert (s.m.manager_role, True) in after.roles and all(r[1] for r in after.roles)
    assert len(audit_row(s, target)) == 1
    assert code(end(pooled_factory, s, target, key=key)) in (403, 404)


@KEYED
def test_the_last_manager_cannot_end_their_own_membership_and_nothing_persists(
    keyed: bool, s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the manager is the only non-expiring `access.manage` holder. The pre-check (before `finalize`,
    under the held campaign lock) refuses with the same 400; nothing persists; the key is reusable once a keeper
    is restored."""
    remove_keeper(s)
    key = new_key() if keyed else None
    target = s.m.manager_membership
    before = state(s, target, key)
    with Recorder(pooled) as recorded:
        response = end(pooled_factory, s, target, key=key)
    assert code(response) == 400, response.text
    assert state(s, target, key) == before and idle_in_transaction(s.w.engine) == 0
    assert not any(FINAL_RE.search(x) for x in recorded.events), (
        "refused before the final statement"
    )
    assert [x for x in writes_of(recorded.events) if "idempotent_requests" not in x] == []
    restore_keeper(s)
    assert code(end(pooled_factory, s, target, key=key)) == 200


def test_ending_another_manager_is_refused_when_it_would_leave_no_non_expiring_manager(
    s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the keeper (expiring) ends the manager, the only non-expiring holder: 400, nothing persists. The
    manager (non-expiring) ending the keeper is permitted."""
    remove_keeper(s)
    before = state(s, s.m.manager_membership)
    response = end(pooled_factory, s, s.m.manager_membership, actor=s.m.keeper_user)
    assert code(response) == 400, response.text
    assert state(s, s.m.manager_membership) == before
    assert code(end(pooled_factory, s, s.m.keeper_membership)) == 200


def test_a_defeated_pre_check_is_caught_by_the_deferred_backstop_at_commit(
    s: Scene, pooled: Engine, pooled_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """*mutation (test-side)*: the pre-check that makes the deferred triggers unreachable is defeated, so the last
    manager's self-end passes it and the trigger refuses at COMMIT (it re-acquires the campaign lock the request
    already holds `FOR UPDATE`: no upgrade). A server error, nothing persisted, the key reusable; with the
    pre-check back the same request is the classified 400."""
    from dnd_ai.commands import membership_end_plans as plans

    remove_keeper(s)
    key = new_key()
    target = s.m.manager_membership
    before = state(s, target, key)
    monkeypatch.setattr(plans, "_require_manager_survives_end", lambda *a, **k: None)
    response = end(pooled_factory, s, target, key=key)
    monkeypatch.undo()
    assert code(response) >= 500, response.text
    assert state(s, target, key) == before and idle_in_transaction(s.w.engine) == 0
    assert code(end(pooled_factory, s, target, key=key)) == 400


# --- replay and authority ----------------------------------------------------------------------------------------------


def test_an_authorized_replay_returns_the_stored_receipt_without_a_lock_or_a_write(
    s: Scene, e: Member, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* and *sql*: the stored body, no row lock, no write, and the final authority statement last before
    COMMIT (the receipt does not leave before the check). The replay does not re-run the command."""
    key = new_key()
    first = end(pooled_factory, s, e.membership, key=key)
    assert code(first) == 200
    stored = state(s, e.membership, key)
    with Recorder(pooled) as recorded:
        replay = end(pooled_factory, s, e.membership, key=key)
    assert code(replay) == 200 and replay.json() == first.json()
    assert state(s, e.membership, key) == stored
    finals = [x for x in recorded.events if FINAL_RE.search(x)]
    assert len(finals) == 1 and recorded.events[-2:] == [finals[0], "COMMIT"]
    assert not [
        x for x in recorded.events if re.search(r"FOR (KEY SHARE|SHARE|UPDATE|NO KEY UPDATE)", x)
    ]
    assert all(
        "idempotent_requests" in x and "ON CONFLICT" in x for x in writes_of(recorded.events)
    )


def test_a_replay_after_authority_loss_is_refused_and_returns_nothing_from_the_receipt(
    s: Scene, e: Member, pooled: Engine, pooled_factory: Factory
) -> None:
    key = new_key()
    assert code(end(pooled_factory, s, e.membership, key=key)) == 200
    stored = state(s, e.membership, key)
    revoke_role(s.w.engine, s.m.manager_role)
    again = end(pooled_factory, s, e.membership, key=key)
    assert code(again) in (403, 404), again.text
    assert str(e.membership) not in again.text and "campaign_membership_id" not in again.text
    assert state(s, e.membership, key) == stored


def test_a_reused_key_with_another_target_is_the_same_conflict_and_changes_nothing(
    s: Scene, e: Member, pooled: Engine, pooled_factory: Factory
) -> None:
    key = new_key()
    assert code(end(pooled_factory, s, e.membership, key=key)) == 200
    stored = state(s, e.membership, key)
    response = end(pooled_factory, s, s.target_membership, key=key)
    assert code(response) == 409 and error_of(response) == "conflict", response.text
    assert state(s, e.membership, key) == stored
    assert state(s, s.target_membership).membership[0] is False


@KEYED
@pytest.mark.parametrize("self_end", (False, True), ids=("other", "self"))
def test_a_role_that_lapses_before_the_final_statement_refuses_the_route_and_rolls_everything_back(
    keyed: bool, self_end: bool, s: Scene, e: Member, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* (race, expiry at the authorization boundary): the manager's role is valid for every early check and
    has lapsed (a DATABASE condition, polled) when the final authority statement runs, every lock already held.
    Nothing persists (a self-end included: it never ends the membership of a caller whose authority lapsed); the
    key is reusable."""
    from tests.r01_s5d_support import run_with_role_lapsing_before_final

    key = new_key() if keyed else None
    target = s.m.manager_membership if self_end else e.membership
    before = state(s, target, key)
    response = run_with_role_lapsing_before_final(
        s.w.engine,
        pooled,
        s.m.manager_role,
        lambda: end(pooled_factory, s, target, key=key),
        first_gate=KEY_LOCK if keyed else r"FROM security\.membership_roles WHERE",
    )
    assert code(response) in (403, 404), response.text
    assert state(s, target, key) == before and idle_in_transaction(s.w.engine) == 0
    with s.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = NULL WHERE membership_role_id = :r"
            ),
            {"r": s.m.manager_role},
        )
    assert code(end(pooled_factory, s, target, key=key)) == 200


def test_a_role_revoked_before_the_request_is_refused_early_and_writes_nothing(
    s: Scene, e: Member, pooled: Engine, pooled_factory: Factory
) -> None:
    revoke_role(s.w.engine, s.m.manager_role)
    key = new_key()
    before = state(s, e.membership, key)
    response = end(pooled_factory, s, e.membership, key=key)
    assert code(response) in (403, 404), response.text
    assert state(s, e.membership, key) == before


# --- the declared statement stream ------------------------------------------------------------------------------------


def role_lock_modes(events: list[str]) -> list[str]:
    """The role-class lock statements in order, as their modes ("S" the actor's range, "U" a target row)."""
    modes = []
    for x in events:
        if re.search(r"FROM security\.membership_roles WHERE .* FOR SHARE$", x):
            modes.append("S")
        elif re.search(ROLE_ROW_U, x):
            modes.append("U")
    return modes


@KEYED
def test_the_route_runs_its_statements_in_the_declared_order(
    keyed: bool, s: Scene, e: Member, pooled: Engine, pooled_factory: Factory
) -> None:
    """*sql*: [key lock, deferral, reservation,] the role class (the actor's ranges S around the target's rows U, one
    ascending pass), the delegation, the actor's membership S and the target U, the target's open evidence, the actor's
    account, the campaign `FOR UPDATE`, the five dependent classes, [our receipt row,] the one final authority statement,
    and only after it the declared writes in the order roles, delegation, relationships, grants, group memberships,
    revelations, snapshot rows, the membership, the audit row, [the receipt], COMMIT last, no row lock after the
    final statement."""
    key = new_key() if keyed else None
    with Recorder(pooled) as recorded:
        response = end(pooled_factory, s, e.membership, key=key)
    assert code(response) == 200, response.text
    ev = recorded.events
    assert role_lock_modes(ev) == ["S", "U", "S", "U", "S"], (
        "two target rows, the actor's rows between them"
    )
    chain = [
        index(ev, ROLES_S),
        index(ev, DELEGATIONS_U),
        max(
            index(ev, MEMBERSHIP_S), index(ev, MEMBERSHIP_U)
        ),  # either first (id order); both before the account
        index(ev, ACCOUNT_S),
        index(ev, CAMPAIGN_U),
        index(ev, RELATIONSHIPS_U),
        index(ev, GRANTS_U),
        index(ev, GROUPS_U),
        index(ev, REVELATIONS_U),
        index(ev, SNAPSHOT_U),
    ]
    if keyed:
        chain.append(index(ev, RECEIPT_U))
    final = index(ev, FINAL)
    chain.append(final)
    for pattern in (
        UPDATE_ROLE,
        UPDATE_DELEGATION,
        UPDATE_RELATIONSHIP,
        UPDATE_GRANT,
        UPDATE_GROUP,
        UPDATE_REVELATION,
        UPDATE_SNAPSHOT,
        UPDATE_MEMBERSHIP,
        AUDIT_INSERT,
    ):
        chain.append(index(ev, pattern))
    if keyed:
        chain.append(index(ev, RECEIPT_UPDATE))
    assert chain == sorted(chain), (chain, ev)
    # the membership S precedes the membership U only because of the ids; both precede the account either way
    first_lock = min(
        i for i, x in enumerate(ev) if re.search(r"FOR (KEY SHARE|SHARE|UPDATE)|pg_advisory", x)
    )
    if keyed:
        assert index(ev, KEY_LOCK) == first_lock
        assert (
            index(ev, r"SET CONSTRAINTS security\.idempotent_requests_campaign_id_fkey DEFERRED")
            < index(ev, KEY_LOCK)
            < index(ev, r"^INSERT INTO security\.idempotent_requests")
            < index(ev, ROLES_S)
        )
    else:
        assert not [
            x for x in ev if re.search(r"pg_advisory|idempotent_requests|SET CONSTRAINTS", x)
        ]
    assert ev[-1] == "COMMIT"
    assert not [
        x for x in ev[final:] if re.search(r"\bFOR (KEY SHARE|SHARE|UPDATE|NO KEY UPDATE)\b", x)
    ]
    assert len([x for x in ev if re.search(UPDATE_ROLE, x)]) == 2
    assert len([x for x in ev if re.search(AUDIT_INSERT, x)]) == 1


def test_a_self_end_locks_the_role_rows_once_exclusively_in_one_pass(
    s: Scene, pooled: Engine, pooled_factory: Factory
) -> None:
    """*sql*: when the actor is the target the shared rows are locked once, `FOR UPDATE`, in id order: no `FOR SHARE`
    role statement at all (a shared lock taken first would be an upgrade), and the actor's membership lock lands on
    the row already held."""
    with Recorder(pooled) as recorded:
        response = end(pooled_factory, s, s.m.manager_membership)
    assert code(response) == 200, response.text
    assert role_lock_modes(recorded.events) == ["U"]
    assert not [x for x in recorded.events if re.search(r"membership_roles WHERE .* FOR SHARE$", x)]


# --- the plan's obligations ---------------------------------------------------------------------------------------------


@KEYED
def test_a_handler_that_forgets_to_finalize_is_a_sanitized_500_that_persists_nothing(
    keyed: bool,
    s: Scene,
    e: Member,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = new_key() if keyed else None
    before = state(s, e.membership, key)
    monkeypatch.setattr(AuthorizationPlan, "finalize", lambda self, connection: None)
    response = end(pooled_factory, s, e.membership, key=key)
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error"
    assert state(s, e.membership, key) == before and idle_in_transaction(s.w.engine) == 0
    assert code(end(pooled_factory, s, e.membership, key=key)) == 200


def _wrap(
    monkeypatch: pytest.MonkeyPatch,
    *,
    skip: tuple[str, ...] = (),
    repeat: tuple[str, ...] = (),
    after: dict[str, tuple[Any, dict[str, Any]]] | None = None,
) -> None:
    """Test-side mutation of `AuthorizationPlan.execute`: omit a step, run it twice, or run another declared step
    (with its own parameters) right after one."""
    original = AuthorizationPlan.execute

    def wrapper(self: AuthorizationPlan, connection: Any, step: Any, params: Any) -> Any:
        if step.name in skip:
            from dnd_ai.domain.authorization import StepOutcome

            return StepOutcome(step=step.name, keys=())
        outcome = original(self, connection, step, params)
        if step.name in repeat:
            original(self, connection, step, params)
        if after and step.name in after:
            extra_step, extra_params = after[step.name]
            original(self, connection, extra_step, extra_params)
        return outcome

    monkeypatch.setattr(AuthorizationPlan, "execute", wrapper)


@KEYED
@pytest.mark.parametrize("step", (*STEPS, "receipt"))
def test_an_omitted_required_write_is_refused_at_commit_and_rolls_everything_back(
    keyed: bool,
    step: str,
    s: Scene,
    e: Member,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)*: every closure, the membership update, the audit row and (keyed) the receipt is owed by
    the locked state. A request that never runs one cannot commit: the guard refuses the incomplete plan (sanitized
    500), everything rolls back, the key is reusable, the connection is clean."""
    if step == "receipt" and not keyed:
        pytest.skip("an unkeyed request has no receipt")
    key = new_key() if keyed else None
    before = state(s, e.membership, key)
    _wrap(monkeypatch, skip=(step,))
    response = end(pooled_factory, s, e.membership, key=key)
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error", (step, response.text)
    assert state(s, e.membership, key) == before and idle_in_transaction(s.w.engine) == 0, step
    assert code(end(pooled_factory, s, e.membership, key=key)) == 200


@KEYED
@pytest.mark.parametrize("step", STEPS)
def test_a_repeated_write_is_refused_and_the_whole_request_rolls_back(
    keyed: bool,
    step: str,
    s: Scene,
    e: Member,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)*: a second update of a row, a second membership update or a second audit row is a
    forbidden extra write: the second attempt is refused before the driver and nothing persists."""
    key = new_key() if keyed else None
    before = state(s, e.membership, key)
    pattern = {
        "end_revoke_role": UPDATE_ROLE,
        "end_close_delegation": UPDATE_DELEGATION,
        "end_revoke_relationship": UPDATE_RELATIONSHIP,
        "end_revoke_grant": UPDATE_GRANT,
        "end_remove_group_membership": UPDATE_GROUP,
        "end_close_revelation": UPDATE_REVELATION,
        "end_remove_revelation_member": UPDATE_SNAPSHOT,
        "end_membership": UPDATE_MEMBERSHIP,
        "audit_membership_ended": AUDIT_INSERT,
    }[step]
    expected_first = 2 if step == "end_revoke_role" else 1
    _wrap(monkeypatch, repeat=(step,))
    with Recorder(pooled) as recorded:
        response = end(pooled_factory, s, e.membership, key=key)
    monkeypatch.undo()
    assert code(response) == 500, response.text
    assert len([x for x in recorded.events if re.search(pattern, x)]) <= expected_first, (
        "the repeat never reached the driver"
    )
    assert state(s, e.membership, key) == before and idle_in_transaction(s.w.engine) == 0


@pytest.mark.parametrize("step", STEPS[:-1])
def test_a_write_to_a_row_the_request_did_not_lock_is_refused_and_nothing_persists(
    step: str,
    s: Scene,
    e: Member,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*mutation (test-side)*: right after the genuine membership update the request tries the same kind of write
    against another member's row, which it never locked: refused (it is not in the lock evidence), the whole request
    rolls back, and the other member keeps every open row."""
    from dnd_ai.commands import membership_end_plans as plans

    other = build_member(s, "S5E3 Unlocked")
    victim = {
        "end_revoke_role": other.player_row,
        "end_close_delegation": other.delegation,
        "end_revoke_relationship": other.relationship,
        "end_revoke_grant": other.grant,
        "end_remove_group_membership": other.group_membership,
        "end_close_revelation": other.revelation,
        "end_remove_revelation_member": other.snapshot_row,
        "end_membership": other.membership,
    }[step]
    declared = {item.name: item for item in plans.END_DECLARATIONS.unkeyed.steps}  # type: ignore[union-attr]
    extra = (
        {"actor": s.m.manager_membership, "status": uuid.uuid4()}
        if step == "end_membership"
        else {}
    )
    _wrap(monkeypatch, after={"end_membership": (declared[step], {"target": victim, **extra})})
    before = state(s, e.membership)
    before_other = (state(s, other.membership), open_dependents(s, other.membership))
    response = end(pooled_factory, s, e.membership)
    monkeypatch.undo()
    assert code(response) == 500, response.text
    assert state(s, e.membership) == before
    assert (state(s, other.membership), open_dependents(s, other.membership)) == before_other
    assert idle_in_transaction(s.w.engine) == 0


def test_a_one_connection_pool_serves_success_noop_refusals_and_a_retry_without_leaking_state(
    s: Scene, e: Member, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: one pooled connection, reused for success, the no-op, a 404, a 400, a refusal for a non-manager and a replay in turn. Each
    answers as it would alone, the connection is never left in a transaction, and nothing one request held reaches
    the next."""
    key = new_key()
    assert code(end(pooled_factory, s, e.membership, key=key)) == 200
    assert idle_in_transaction(s.w.engine) == 0
    assert code(end(pooled_factory, s, e.membership)) == 200  # the no-op
    assert code(end(pooled_factory, s, uuid.uuid4())) == 404
    assert code(end(pooled_factory, s, s.target_membership, actor=e.user)) in (403, 404)
    remove_keeper(s)
    assert code(end(pooled_factory, s, s.m.manager_membership)) == 400
    restore_keeper(s)
    assert code(end(pooled_factory, s, e.membership, key=key)) == 200  # the replay
    assert code(end(pooled_factory, s, s.target_membership)) == 200
    assert idle_in_transaction(s.w.engine) == 0
    assert len(audit_row(s, e.membership)) == 1


def test_the_declarations_hold_against_the_live_catalogue(w: World) -> None:
    """The S1 catalogue helper checks every assumption a declaration makes about the database (triggers pinned by
    function-source hash, unique waits, FK match type and order, defaults, CHECK expressions). An empty list is the
    only passing answer."""
    from dnd_ai.commands import membership_end_plans as plans
    from tests.r01_pre_write_catalogue import check_declaration

    problems: list[str] = []
    with w.engine.connect() as connection:
        for kind, decl in (
            ("reserved", plans.END_DECLARATIONS.reserved),
            ("unkeyed", plans.END_DECLARATIONS.unkeyed),
        ):
            assert decl is not None
            problems += [f"{kind}: {x}" for x in check_declaration(connection, decl)]
    assert problems == [], chr(10).join(problems)


# --- unique waits ----------------------------------------------------------------------------------------------------


def _competing_insert(sc: Scene, e: Member, index: str) -> Callable[[Any], Any]:
    """An INSERT that carries the same key as the row the end closes, for each partial unique index it leaves."""

    def run(c: Any) -> Any:
        if index == "relationship":
            return make_membership_character_relationship(
                c, e.membership, e.character, e.relationship_type
            )
        if index == "grant":
            return make_resource_grant(
                c,
                sc.w.campaign_id,
                e.capability,
                grantee_campaign_membership_id=e.membership,
                character_id=e.character,
            )
        if index == "group":
            return make_access_group_membership(c, e.group, e.membership)
        if index == "revelation":
            c.execute(text("SET LOCAL session_replication_role = replica"))
            return _revelation(c, sc, e.character, "member", member=e.membership)
        return make_campaign_membership(c, sc.w.campaign_id, e.user)

    return run


@pytest.mark.parametrize("index", ("relationship", "grant", "group", "revelation", "membership"))
def test_an_update_leaving_a_partial_unique_index_never_waits_for_a_competing_insert(
    index: str, s: Scene, e: Member, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, `ux_membership_character_relationships_active_type`, `ux_resource_grants_active`,
    `ux_access_group_memberships_open`, `ux_character_revelations_live` and `ux_campaign_memberships_open`: each
    closing `UPDATE` leaves its partial index, so it takes no unique wait. A competitor inserting the same key while
    the request is parked at its audit insert (every update done, uncommitted) queues behind *the request* (blocked by
    its pid); the request finishes while the competitor is still queued, then the competitor completes (the key is
    free)."""
    from tests.database.test_r01_s5e2_membership_routes import waiting_statement
    from tests.http_race_support import StatementGate, run_in_thread
    from tests.lock_race_support import LockRace

    with StatementGate(pooled, AUDIT_INSERT) as gate:
        request = run_in_thread("end", lambda: end(pooled_factory, s, e.membership, key=new_key()))
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(s.w.engine) as race:
            competitor = race.start("insert", _competing_insert(s, e, index))
            race.wait_blocked_by(gate, expected=1)
            assert re.search(r"INSERT INTO security\.", waiting_statement(s.w.engine, gate.pid))
            gate.release()
            response = request.wait("the end finishes while the competitor is queued")
            race.join_all()
    assert code(response) == 200 and competitor.error is None


def test_an_ended_membership_that_still_holds_an_open_row_is_the_untouched_no_op(
    s: Scene, e: Member, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* and *sql*: data an older version left behind (a live delegation on an ended membership) makes no
    difference: the request is the documented no-op (200, nothing written, no lock taken on the stray row), as the
    baseline command was. The early role and delegation passes are skipped for a membership that looks ended."""
    assert code(end(pooled_factory, s, e.membership)) == 200
    with s.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.character_reveal_delegations SET revoked_at = NULL, end_reason = NULL "
                "WHERE character_reveal_delegation_id = :d"
            ),
            {"d": e.delegation},
        )
    before = state(s, e.membership)
    key = new_key()
    with Recorder(pooled) as recorded:
        response = end(pooled_factory, s, e.membership, key=key)
    assert code(response) == 200, response.text
    after = state(s, e.membership, key)
    assert after.delegations == before.delegations == [(e.delegation, False, None)]
    assert after.audits == before.audits and after.roles == before.roles
    assert not any(re.search(DELEGATIONS_U, x) for x in recorded.events)
    assert [x for x in writes_of(recorded.events) if "idempotent_requests" not in x] == []
