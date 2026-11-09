# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""The A3a acceptance races that complete the §10.8.4 matrix (P03-A A3a review corrections).

Command races use `LockRace`: the first command is paused at a named statement, the second is
proven (through `pg_blocking_pids`) to wait on it, and only then is the pause released. The keyed
expiry cases run the real routes through `TestClient`, held in flight by a row this test owns.
Every case asserts the outcome of each command or request, and the persisted audit, receipt,
revelation, snapshot, membership and role state.
"""

import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.commands.access_grants import create_resource_grant
from dnd_ai.commands.character_reveal import grant_character_reveal_delegation  # noqa: F401
from dnd_ai.commands.character_revelations import create_character_revelation
from dnd_ai.commands.local_auth import _disable_local_account_impl
from dnd_ai.commands.memberships import (
    add_campaign_member,
    end_campaign_membership,
    transfer_campaign_ownership,
)
from dnd_ai.commands.recovery import recover_campaign_access_manager
from dnd_ai.domain.access import LOCAL_AUTH_ISSUER
from dnd_ai.domain.public_profiles import (
    CharacterRevealRequiredError,
    RevelationTargetNotActiveError,
)
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_campaign_owner_lock_order import (  # noqa: F401 - autouse fixture
    _release_everything,
    _status,
)
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.database.test_character_revelations import (  # noqa: F401 - fixtures used by name
    CREATE_COMMAND,
    REVOKE_COMMAND,
    Rev,
    audit,
    campaign_body,
    error_code,
    member_body,
    rev,
    revelations,
    snapshot,
    url,
)
from tests.database.test_character_revelations_keyed import (
    assert_roles,
    hold_audit_action,
    key_ids,
    live_role_ids,
    make_revelation,
    membership_open,
    receipts,
    role_rows,
    start,
    wait_blocked,
    wait_key_queue,
)
from tests.factories import make_external_identity, make_system_role_assignment, make_user
from tests.lock_race_support import LockRace

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]

# The statements the pauses name. The flattened SQL carries `%(name)s` parameters.
CAMPAIGN_KEY_SHARE = r"FROM campaign\.campaigns WHERE campaign_id = .* FOR KEY SHARE"
CAMPAIGN_FOR_UPDATE = r"FROM campaign\.campaigns WHERE campaign_id = .* FOR UPDATE"
MEMBER_TARGET_KEY_SHARE = (
    r"FROM security\.campaign_memberships WHERE campaign_membership_id = .* FOR KEY SHARE"
)
SNAPSHOT_CANDIDATES = r"FROM security\.campaign_memberships WHERE campaign_id = .* FOR KEY SHARE"
CALLER_ACCOUNT_KEY_SHARE = r"SELECT 1 FROM security\.users WHERE user_id = .* FOR KEY SHARE"
CHARACTER_KEY_SHARE = r"FROM core\.entities WHERE entity_id = .* FOR KEY SHARE"
ROLE_INSERT = r"INSERT INTO security\.membership_roles"


# --- command builders -------------------------------------------------------------------------


def create_as(
    g: Gate,
    character: uuid.UUID,
    actor: uuid.UUID,
    kind: str,
    *,
    member: uuid.UUID | None = None,
) -> Callable[[Any], Any]:
    return lambda cn: create_character_revelation(
        cn,
        campaign_id=g.campaign_id,
        character_id=character,
        actor_membership_id=actor,
        audience_kind=kind,
        target_campaign_membership_id=member,
        target_access_group_id=None,
        reason="Race",
        reserve=lambda: False,
    )


def end_of(g: Gate, membership: uuid.UUID, by: uuid.UUID) -> Callable[[Any], Any]:
    return lambda cn: end_campaign_membership(
        cn, campaign_membership_id=membership, campaign_id=g.campaign_id,
        ended_by_membership_id=by,
    )  # fmt: skip


def row_for(engine: Engine, g: Gate, character: uuid.UUID) -> dict[str, Any]:
    [row] = revelations(engine, g, character)
    return row


# --- M1 to M3: a member-target creation against the end of its target or its creator ----------


def test_m1_a_member_creation_that_reaches_the_target_first_is_closed_by_the_end(
    postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    with LockRace(postgres_engine) as race:
        pause = race.pause(
            thread_name="create", pattern=CAMPAIGN_KEY_SHARE, after=MEMBER_TARGET_KEY_SHARE
        )
        create = race.start("create", create_as(g, c, g.o1, "member", member=g.player))
        pause.wait_reached(create)
        end = race.start("end", end_of(g, g.player, g.o2))
        race.wait_blocked_by(pause, end)  # the end waits at the target the creation holds
        pause.release()
        race.join_all()
    assert create.error is None and end.error is None, (create.error, end.error)
    row = row_for(postgres_engine, g, c)
    assert row["end_reason"] == "target_membership_ended" and row["ended_at"] is not None
    assert not membership_open(postgres_engine, g.player)
    assert end.result.closed_character_revelation_ids == (row["character_revelation_id"],)  # type: ignore[union-attr]
    assert_roles(postgres_engine, g, ended=(g.player,))


def test_m2_an_end_that_reaches_the_target_first_makes_the_creation_a_409_that_writes_nothing(
    postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="end", pattern=CAMPAIGN_FOR_UPDATE)
        end = race.start("end", end_of(g, g.player, g.o2))
        pause.wait_reached(end)
        create = race.start("create", create_as(g, c, g.o1, "member", member=g.player))
        race.wait_blocked_by(pause, create)  # the creation waits at the target (step 4)
        pause.release()
        race.join_all()
    assert end.error is None, end.error
    assert isinstance(create.error, RevelationTargetNotActiveError), create.error
    assert revelations(postgres_engine, g, c) == []
    assert_roles(postgres_engine, g, ended=(g.player,))


def test_m3_ending_the_creator_after_the_creation_keeps_the_committed_revelation(
    postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    with LockRace(postgres_engine) as race:
        pause = race.pause(
            thread_name="create", pattern=CAMPAIGN_KEY_SHARE, after=MEMBER_TARGET_KEY_SHARE
        )
        create = race.start("create", create_as(g, c, g.o2, "member", member=g.player))
        pause.wait_reached(create)
        end = race.start("end", end_of(g, g.o2, g.o1))  # the revealer is ended by the other owner
        race.wait_blocked_by(pause, end)  # at the revealer's owner row, which the creation holds
        pause.release()
        race.join_all()
    assert create.error is None and end.error is None, (create.error, end.error)
    row = row_for(postgres_engine, g, c)
    assert row["ended_at"] is None  # D9-f: the revelation survives its creator
    assert row["created_by_membership_id"] == g.o2
    assert_roles(postgres_engine, g, ended=(g.o2,))


def test_m3_prime_an_end_that_reaches_the_creator_first_makes_the_creation_a_403(
    postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="end", pattern=CAMPAIGN_FOR_UPDATE)
        end = race.start("end", end_of(g, g.o2, g.o1))
        pause.wait_reached(end)  # the end holds the creator's role rows
        create = race.start("create", create_as(g, c, g.o2, "member", member=g.player))
        race.wait_blocked_by(pause, create)
        pause.release()
        race.join_all()
    assert end.error is None, end.error
    assert isinstance(create.error, CharacterRevealRequiredError), create.error
    assert revelations(postgres_engine, g, c) == []
    assert_roles(postgres_engine, g, ended=(g.o2,))


def test_m3_prime_keyed_the_refused_creator_gets_403_no_receipt_and_no_audit_row(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    key = f"m3p-{uuid.uuid4().hex[:8]}"
    with LockRace(postgres_engine) as race:
        held = race.hold(lambda cn: end_campaign_membership(
            cn, campaign_membership_id=g.o2, campaign_id=g.campaign_id,
            ended_by_membership_id=g.o1,
        ))  # fmt: skip
        request = race.start(
            "create",
            lambda _cn: _post(client_factory, g.o2_user_id, url(g, c), member_body(g.player), key),
        )
        race.wait_blocked_by(held, request)  # past the route pre-check, blocked in the command
        held.commit()
        race.join_all()
    response = request.result
    assert response.status_code == 403 and error_code(response) == "character_reveal_required"  # type: ignore[union-attr]
    assert receipts(postgres_engine, g, g.o2_user_id, key) == []
    assert audit(postgres_engine, g, CREATE_COMMAND) == []
    assert revelations(postgres_engine, g, c) == []


def _post(factory: Factory, user: uuid.UUID, path: str, body: dict[str, object], key: str) -> Any:
    with factory(user) as client:
        return client.post(path, json=body, headers={"Idempotency-Key": key})


# --- S3 to S8: the snapshot against recovery, transfers, grants and an add -------------------


@pytest.fixture
def stranded(postgres_engine: Engine, g: Gate) -> uuid.UUID:
    """Strands the campaign so recovery may run, and returns a platform administrator's user id:
    both owners' assignments become finite (the manager's stays, so the retention trigger allows
    it), then the manager's account is archived. `o1` keeps authority to reveal."""
    with postgres_engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE security.membership_roles SET expires_at = now() + interval '1 day'
                WHERE membership_role_id = ANY(:ids)
            """),
            {"ids": [g.o1_role, g.o2_role]},
        )
    with postgres_engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE security.users SET lifecycle_status_id = (
                    SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived')
                WHERE user_id = :u
            """),
            {"u": g.manager_user_id},
        )
        admin = make_user(connection, "Snapshot Recovery Admin")
        make_system_role_assignment(connection, admin, "admin")
    return admin


def _owner_role_live(engine: Engine, membership: uuid.UUID) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text("""
                    SELECT count(*) FROM security.membership_roles mr
                    JOIN security.roles r ON r.role_id = mr.role_id
                    WHERE mr.campaign_membership_id = :m AND r.code = 'campaign_owner'
                      AND mr.revoked_at IS NULL
                """),
                {"m": membership},
            ).scalar_one()
        )


def _recover(g: Gate, admin: uuid.UUID, user: uuid.UUID) -> Callable[[Any], Any]:
    return lambda cn: recover_campaign_access_manager(
        cn, admin_user_id=admin, campaign_id=g.campaign_id, new_user_id=user, reason="Recover"
    )


def test_s3_a_creation_that_reaches_the_member_first_includes_them_and_recovery_then_commits(
    postgres_engine: Engine, g: Gate, rev: Rev, stranded: uuid.UUID
) -> None:
    c = rev.character_id
    with LockRace(postgres_engine) as race:
        pause = race.pause(
            thread_name="create", pattern=CAMPAIGN_KEY_SHARE, after=SNAPSHOT_CANDIDATES
        )
        create = race.start("create", create_as(g, c, g.o1, "campaign_current"))
        pause.wait_reached(create)
        recovery = race.start("recovery", _recover(g, stranded, g.player_user_id))
        race.wait_blocked_by(pause, recovery)  # at the member the snapshot statement holds
        pause.release()
        race.join_all()
    assert create.error is None and recovery.error is None, (create.error, recovery.error)
    row = row_for(postgres_engine, g, c)
    assert g.player in snapshot(postgres_engine, row["character_revelation_id"])
    assert _owner_role_live(postgres_engine, g.player)
    assert_roles(postgres_engine, g, roles={g.player: {g.player_role_id, g.owner_role_id}})


def test_s4_recovery_that_holds_the_member_first_leaves_them_in_the_snapshot(
    postgres_engine: Engine, g: Gate, rev: Rev, stranded: uuid.UUID
) -> None:
    c = rev.character_id
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="recovery", pattern=ROLE_INSERT)
        recovery = race.start("recovery", _recover(g, stranded, g.player_user_id))
        pause.wait_reached(recovery)  # it holds the campaign (NO KEY UPDATE) and the member
        create = race.start("create", create_as(g, c, g.o1, "campaign_current"))
        race.wait_blocked_by(pause, create)
        pause.release()
        race.join_all()
    assert create.error is None and recovery.error is None, (create.error, recovery.error)
    row = row_for(postgres_engine, g, c)
    assert g.player in snapshot(postgres_engine, row["character_revelation_id"])
    assert _owner_role_live(postgres_engine, g.player)
    assert_roles(postgres_engine, g, roles={g.player: {g.player_role_id, g.owner_role_id}})


def _transfer(g: Gate, to: uuid.UUID) -> Callable[[Any], Any]:
    return lambda cn: transfer_campaign_ownership(
        cn,
        campaign_id=g.campaign_id,
        actor_membership_id=g.o1,
        target_campaign_membership_id=to,
        relinquish_own_ownership=True,
    )


def test_s5_a_creation_that_reaches_the_recipient_first_includes_them_and_the_transfer_commits(
    postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    with LockRace(postgres_engine) as race:
        pause = race.pause(
            thread_name="create", pattern=CAMPAIGN_KEY_SHARE, after=SNAPSHOT_CANDIDATES
        )
        create = race.start("create", create_as(g, c, g.o2, "campaign_current"))
        pause.wait_reached(create)
        transfer = race.start("transfer", _transfer(g, g.player))
        race.wait_blocked_by(pause, transfer)
        pause.release()
        race.join_all()
    assert create.error is None and transfer.error is None, (create.error, transfer.error)
    row = row_for(postgres_engine, g, c)
    assert g.player in snapshot(postgres_engine, row["character_revelation_id"])
    assert _owner_role_live(postgres_engine, g.player) and not _owner_role_live(
        postgres_engine, g.o1
    )
    # The recipient holds the built-in owner role as well as their own; the relinquisher none.
    assert_roles(
        postgres_engine,
        g,
        roles={g.player: {g.player_role_id, g.owner_role_id}, g.o1: set()},
    )


def test_s6_a_transfer_that_holds_the_recipient_first_leaves_them_in_the_snapshot(
    postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="transfer", pattern=ROLE_INSERT)
        transfer = race.start("transfer", _transfer(g, g.player))
        pause.wait_reached(transfer)  # past its campaign lock, holding the recipient
        create = race.start("create", create_as(g, c, g.o2, "campaign_current"))
        race.wait_blocked_by(pause, create)  # at the recipient in step 4a
        pause.release()
        race.join_all()
    assert create.error is None and transfer.error is None, (create.error, transfer.error)
    row = row_for(postgres_engine, g, c)
    assert g.player in snapshot(postgres_engine, row["character_revelation_id"])
    assert _owner_role_live(postgres_engine, g.player) and not _owner_role_live(
        postgres_engine, g.o1
    )
    # The recipient holds the built-in owner role as well as their own; the relinquisher none.
    assert_roles(
        postgres_engine,
        g,
        roles={g.player: {g.player_role_id, g.owner_role_id}, g.o1: set()},
    )


def test_s7_a_resource_grant_to_a_member_waits_for_the_creation_and_both_commit(
    postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    grant = lambda cn: create_resource_grant(  # noqa: E731
        cn,
        campaign_id=g.campaign_id,
        grantee_campaign_membership_id=g.player,
        grantee_access_group_id=None,
        capability_code="character.view_summary",
        effect="allow",
        expected_world_id=g.world_id,
        granted_by_membership_id=g.o2,
        character_id=c,
    )
    with LockRace(postgres_engine) as race:
        pause = race.pause(
            thread_name="create", pattern=CAMPAIGN_KEY_SHARE, after=SNAPSHOT_CANDIDATES
        )
        create = race.start("create", create_as(g, c, g.o1, "campaign_current"))
        pause.wait_reached(create)
        granted = race.start("grant", grant)
        race.wait_blocked_by(pause, granted)  # the grant needs the member FOR UPDATE
        pause.release()
        race.join_all()
    assert create.error is None and granted.error is None, (create.error, granted.error)
    row = row_for(postgres_engine, g, c)
    assert g.player in snapshot(postgres_engine, row["character_revelation_id"])
    with postgres_engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM security.resource_grants "
                    "WHERE grantee_campaign_membership_id = :m AND revoked_at IS NULL"
                ),
                {"m": g.player},
            ).scalar_one()
            == 1
        )


def test_s8_a_member_being_added_is_after_the_cutoff_and_not_in_the_snapshot(
    postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    add = lambda cn: add_campaign_member(  # noqa: E731
        cn,
        campaign_id=g.campaign_id,
        user_id=g.new_user_id,
        role_id=g.player_role_id,
        added_by_membership_id=g.o2,
    )
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="add", pattern=ROLE_INSERT)
        adding = race.start("add", add)
        pause.wait_reached(adding)  # holding the campaign FOR UPDATE, with its new membership
        create = race.start("create", create_as(g, c, g.o1, "campaign_current"))
        race.wait_blocked_by(pause, create)  # the creation waits at step 5, past its snapshot
        pause.release()
        race.join_all()
    assert create.error is None and adding.error is None, (create.error, adding.error)
    row = row_for(postgres_engine, g, c)
    members = snapshot(postgres_engine, row["character_revelation_id"])
    with postgres_engine.connect() as connection:
        new_membership = connection.execute(
            text(
                "SELECT campaign_membership_id FROM security.campaign_memberships "
                "WHERE campaign_id = :c AND user_id = :u"
            ),
            {"c": g.campaign_id, "u": g.new_user_id},
        ).scalar_one()
    assert new_membership not in members  # committed after the cutoff (D9-a)
    assert g.player in members and g.o1 in members
    assert live_role_ids(postgres_engine, new_membership) == [g.player_role_id]  # the role added
    assert_roles(postgres_engine, g)  # nobody else gained or lost a role


# --- AC1 to AC3: the caller's account ---------------------------------------------------------


def test_ac1_adding_an_existing_member_waits_for_the_creation_then_fails_on_the_open_membership(
    postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    with (
        postgres_engine.begin() as connection
    ):  # eligible to be added: only the open membership refuses
        make_external_identity(
            connection,
            g.o1_user_id,
            issuer=LOCAL_AUTH_ISSUER,
            subject=f"ac1-{uuid.uuid4().hex[:8]}",
        )
    add = lambda cn: add_campaign_member(  # noqa: E731
        cn,
        campaign_id=g.campaign_id,
        user_id=g.o1_user_id,  # already a member
        role_id=g.player_role_id,
        added_by_membership_id=g.o2,
    )
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="create", pattern=CALLER_ACCOUNT_KEY_SHARE)
        create = race.start("create", create_as(g, c, g.o1, "campaign_current"))
        pause.wait_reached(create)  # after the campaign KEY SHARE, before the account lock
        adding = race.start("add", add)
        race.wait_blocked_by(pause, adding)  # the add needs the campaign FOR UPDATE
        pause.release()
        race.join_all()
    assert create.error is None, create.error
    # Refused after waiting, by the unique index on open memberships (not by eligibility).
    assert adding.error is not None and "ux_campaign_memberships_open" in str(adding.error)
    assert len(revelations(postgres_engine, g, c)) == 1
    with postgres_engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM security.campaign_memberships "
                    "WHERE campaign_id = :c AND user_id = :u AND ended_at IS NULL"
                ),
                {"c": g.campaign_id, "u": g.o1_user_id},
            ).scalar_one()
            == 1
        )
        assert live_role_ids(postgres_engine, g.o1) == [g.owner_role_id]  # A's roles are unchanged


@pytest.fixture
def admin(postgres_engine: Engine) -> uuid.UUID:
    with postgres_engine.begin() as connection:
        user = make_user(connection, "Deactivation Admin")
        make_system_role_assignment(connection, user, "admin")
    return user


def _account_active(engine: Engine, user_id: uuid.UUID) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text("""
                    SELECT ls.code = 'active' FROM security.users u
                    JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
                    WHERE u.user_id = :u
                """),
                {"u": user_id},
            ).scalar_one()
        )


def test_ac2_a_deactivation_that_holds_the_account_first_makes_the_creation_a_403(
    postgres_engine: Engine, g: Gate, rev: Rev, admin: uuid.UUID
) -> None:
    c = rev.character_id
    assignments = role_rows(postgres_engine, g.o1)
    with LockRace(postgres_engine) as race:
        held = race.hold(lambda cn: _disable_local_account_impl(
            cn, admin_user_id=admin, target_user_id=g.o1_user_id
        ))  # fmt: skip
        create = race.start("create", create_as(g, c, g.o1, "campaign_current"))
        race.wait_blocked_by(held, create)  # at the caller's account (step 5a)
        held.commit()
        race.join_all()
    assert isinstance(create.error, CharacterRevealRequiredError), create.error
    assert revelations(postgres_engine, g, c) == []
    assert not _account_active(postgres_engine, g.o1_user_id)
    # Deactivating the account and the refused creation changed none of the caller's assignments:
    # the same rows, still unrevoked and unexpired, holding the built-in owner role.
    assert role_rows(postgres_engine, g.o1) == assignments
    assert live_role_ids(postgres_engine, g.o1) == [g.owner_role_id]
    assert_roles(postgres_engine, g)


def test_ac3_a_creation_past_the_account_lock_commits_before_the_deactivation(
    postgres_engine: Engine, g: Gate, rev: Rev, admin: uuid.UUID
) -> None:
    c = rev.character_id
    with LockRace(postgres_engine) as race:
        pause = race.pause(
            thread_name="create", pattern=CHARACTER_KEY_SHARE, after=CALLER_ACCOUNT_KEY_SHARE
        )
        create = race.start("create", create_as(g, c, g.o1, "campaign_current"))
        pause.wait_reached(create)  # holding the account FOR KEY SHARE
        disable = race.start(
            "disable",
            lambda cn: _disable_local_account_impl(
                cn, admin_user_id=admin, target_user_id=g.o1_user_id
            ),
        )
        race.wait_blocked_by(pause, disable)
        pause.release()
        race.join_all()
    assert create.error is None and disable.error is None, (create.error, disable.error)
    assert len(revelations(postgres_engine, g, c)) == 1
    assert not _account_active(postgres_engine, g.o1_user_id)


# --- keyed requests: an assignment that expires during the key-lock wait ----------------------


def _expire_soon(engine: Engine, membership_role: uuid.UUID, seconds: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.membership_roles "
                "SET expires_at = clock_timestamp() + make_interval(secs => :s) "
                "WHERE membership_role_id = :r"
            ),
            {"s": seconds, "r": membership_role},
        )


def _wait_until_expired(engine: Engine, membership_role: uuid.UUID) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            if connection.execute(
                text(
                    "SELECT expires_at < clock_timestamp() FROM security.membership_roles "
                    "WHERE membership_role_id = :r"
                ),
                {"r": membership_role},
            ).scalar_one():
                return
        time.sleep(0.2)
    raise AssertionError("the assignment never expired")


@pytest.mark.parametrize("route", ["create", "revoke"])
@pytest.mark.parametrize("caller", ["owner", "gm"])
def test_a_keyed_waiter_whose_assignment_expires_during_the_key_wait_is_refused_afresh(
    client_factory: Factory,
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    rev: Rev,
    route: str,
    caller: str,
) -> None:
    c = rev.character_id
    existing = make_revelation(client_factory, g, c, g.manager)
    user, assignment = (g.o1_user_id, g.o1_role) if caller == "owner" else (m.gm_user_id, m.gm_role)
    key = f"expiry-{route}-{caller}-{uuid.uuid4().hex[:8]}"
    if route == "create":
        path, body, action = url(g, c), campaign_body("campaign_current"), "created"
    else:
        path, body, action = url(g, c, f"/{existing}/revoke"), {"reason": "Because"}, "updated"
    before_revelations = len(revelations(postgres_engine, g, c))
    _expire_soon(postgres_engine, assignment, 8)
    hold = hold_audit_action(postgres_engine, action)
    try:
        first = start(client_factory, user, path, body, key)
        wait_blocked(postgres_engine, hold, first)  # past its authority check, at its audit insert
        second = start(client_factory, user, path, body, key)
        wait_key_queue(postgres_engine, key_ids(postgres_engine, user, g, key), first, second, hold)
        _wait_until_expired(postgres_engine, assignment)  # while the second waits at the key lock
    finally:
        hold.release()
    one, two = first.join(), second.join()
    assert _status(one) in (200, 201)  # type: ignore[arg-type]  # the first checked before expiry
    assert _status(two) == 403 and error_code(two) == "character_reveal_required"
    assert "character_revelation_id" not in two.text  # type: ignore[attr-defined]  # no replay
    assert len(receipts(postgres_engine, g, user, key)) == 1  # the first's, unchanged
    created = len(audit(postgres_engine, g, CREATE_COMMAND))
    revoked = len(audit(postgres_engine, g, REVOKE_COMMAND))
    assert (created, revoked) == ((2, 0) if route == "create" else (1, 1))  # the setup row + one
    after = len(revelations(postgres_engine, g, c))
    assert after == before_revelations + (1 if route == "create" else 0)
