# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-B: `recover_campaign_access_manager` takes the promoted member's membership before the campaign.

Lock sequence. Before: campaign `FOR NO KEY UPDATE`, then the membership `FOR UPDATE`. After: the
user's open membership `FOR UPDATE` (if any), then the campaign `FOR NO KEY UPDATE`, then the open
membership is looked up again under the campaign lock. The membership-then-campaign order is the one
`end_campaign_membership`, the grant and relationship commands, the group add and the authoring scope
use; recovery was the only command taking them the other way round (DEF-020; design review finding 3).

Evidence class. Campaign recovery has no HTTP route in this repository, so every scenario here is
**command evidence**: both sides are application commands (`dnd_ai.commands.*`) on their own
connections, parked with `LockRace` on a named statement and observed through `pg_blocking_pids`.
Where a scenario deadlocks on the parent commit it says so. R1, R2, R3, R4 and R5 are the pairs of the
P03-A plan section 10.8.1; no committed test pinned them before (their evidence was a scratch run).

Not covered here, on purpose: the future J-1′ commands (they are not implemented), so these tests prove
nothing about the proposed D1 pairs beyond the current commands; and invitation acceptance, which takes
the same membership-then-campaign order since the S5-B acceptance correction and is covered, against
recovery, the end and the grant, in `test_r01_s5b_invitation_acceptance_lock_order.py` (that module
replaced the strict `xfail` this one carried while acceptance still took the campaign first).

Pause statements are chosen to mean the same thing on the parent and after the change:
`CAMPAIGN_NKU` is recovery's campaign statement, and the pause named `after=CAMPAIGN_NKU` stops before
recovery's *next* membership statement, so recovery then holds the campaign (parent) or the campaign and
the membership (after).
"""

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from dnd_ai.commands.access_grants import create_resource_grant
from dnd_ai.commands.memberships import add_campaign_member, end_campaign_membership
from dnd_ai.commands.recovery import RecoveryNotNeededError
from dnd_ai.domain.access import LOCAL_AUTH_ISSUER
from tests.database.test_authoring_scope_recovery_locks import (  # noqa: F401 - fixtures by name
    CAMPAIGN_NKU,
    RECOVERY_MEMBERSHIP,
    _membership_of,
    _owner_roles,
    _recover,
    editor,
    stranded,
)
from tests.database.test_content_authoring_concurrency import (  # noqa: F401 - fixtures by name
    Fixture,
    _drop_user,
    fx,
)
from tests.factories import make_character, make_external_identity, make_user
from tests.lock_race_support import LockRace, Worker

pytestmark = pytest.mark.database

# `end_campaign_membership`: the actor's membership, `FOR KEY SHARE`, which it takes after it holds
# the target's role rows and membership and before its campaign lock.
END_ACTOR_LOCK = (
    r"FROM security\.campaign_memberships WHERE campaign_membership_id = \S+ FOR KEY SHARE"
)
ROLE_INSERT = r"INSERT INTO security\.membership_roles"
MEMBERSHIP_INSERT = r"INSERT INTO security\.campaign_memberships"
GRANT_CAMPAIGN_LOCK = r"FROM campaign\.campaigns c JOIN .* FOR UPDATE OF c"


# --- helpers ------------------------------------------------------------------------------------------------


def _end(fx: Fixture, target: uuid.UUID, *, by: uuid.UUID) -> Callable[[Connection], Any]:
    return lambda c: end_campaign_membership(
        c, campaign_membership_id=target, campaign_id=fx.campaign_id, ended_by_membership_id=by
    )


def _open_memberships(fx: Fixture, user: uuid.UUID) -> int:
    return fx.count(
        "SELECT count(*) FROM security.campaign_memberships "
        "WHERE campaign_id = :c AND user_id = :u AND ended_at IS NULL",
        c=fx.campaign_id,
        u=user,
    )


def _all_memberships(fx: Fixture, user: uuid.UUID) -> int:
    return fx.count(
        "SELECT count(*) FROM security.campaign_memberships WHERE campaign_id = :c AND user_id = :u",
        c=fx.campaign_id,
        u=user,
    )


def _ended(fx: Fixture, membership: uuid.UUID) -> bool:
    return bool(
        fx.count(
            "SELECT count(*) FROM security.campaign_memberships "
            "WHERE campaign_membership_id = :m AND ended_at IS NOT NULL",
            m=membership,
        )
    )


def _live_roles(fx: Fixture, user: uuid.UUID) -> list[str]:
    with fx.engine.connect() as connection:
        return sorted(
            connection.execute(
                text("""
                    SELECT r.code FROM security.membership_roles mr
                    JOIN security.campaign_memberships cm
                      ON cm.campaign_membership_id = mr.campaign_membership_id
                    JOIN security.roles r ON r.role_id = mr.role_id
                    WHERE cm.campaign_id = :c AND cm.user_id = :u AND cm.ended_at IS NULL
                      AND mr.revoked_at IS NULL
                """),
                {"c": fx.campaign_id, "u": user},
            ).scalars()
        )


def _ok(*workers: Worker) -> None:
    for worker in workers:
        assert worker.error is None, worker.describe()


@pytest.fixture
def newcomer(fx: Fixture) -> Iterator[uuid.UUID]:
    """An active account with a local-login identity and no membership in the campaign."""
    with fx.engine.begin() as setup:
        user = make_user(setup, "Recovery Newcomer")
        make_external_identity(
            setup, user, issuer=LOCAL_AUTH_ISSUER, subject=f"s5b-{uuid.uuid4().hex[:8]}"
        )
    yield user
    with fx.engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM security.external_identities WHERE user_id = :u"), {"u": user}
        )
    _drop_user(fx.engine, user)


# --- 1. R1, R2, R4: ending the member recovery promotes (the DEF-020 pairs) --------------------------------


def test_r1_recovery_for_a_member_whose_end_is_in_flight_serializes_after_the_end(
    fx: Fixture, editor: uuid.UUID, stranded: uuid.UUID
) -> None:
    """R1. The end holds the member's role rows and membership and stops before its campaign lock.
    Recovery for that member is blocked by the end's session.

    Parent: recovery had taken the campaign `FOR NO KEY UPDATE` first, so released, the end asked for
    the campaign `FOR UPDATE` while recovery waited for the membership: SQLSTATE 40P01.
    Now: recovery holds nothing while it waits at the membership, so the end commits; recovery then
    finds no open membership (the lookup is re-evaluated after the wait), creates a new one and gives it
    the owner role."""
    member = _membership_of(fx, editor)
    owner = _membership_of(fx, fx.owner)
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="end", pattern=END_ACTOR_LOCK)
        end = race.start("end", _end(fx, member, by=owner))
        pause.wait_reached(end)
        recovery = race.start("recovery", _recover(fx, stranded, editor))
        race.wait_blocked_by(pause, recovery)
        pause.release()
        race.join_all()
    _ok(end, recovery)
    assert _ended(fx, member)
    assert _open_memberships(fx, editor) == 1
    assert _owner_roles(fx, editor) == 1


def test_r2_an_end_started_while_recovery_is_paused_after_its_locks_serializes_after_recovery(
    fx: Fixture, editor: uuid.UUID, stranded: uuid.UUID
) -> None:
    """R2. Recovery stops before its membership lookup under the campaign lock. The end of that member
    starts and is blocked by recovery's session.

    Parent: recovery held only the campaign, so the end locked the membership and then waited for the
    campaign; released, recovery wanted the membership: SQLSTATE 40P01.
    Now: recovery holds the membership too, so the end waits at the membership holding nothing. Recovery
    commits (the member gets the owner role), then the end commits and closes every role of the
    membership, the new owner row included, so the campaign is stranded again (the R3 outcome; the
    retention check passes through the deputy's non-expiring row)."""
    member = _membership_of(fx, editor)
    owner = _membership_of(fx, fx.owner)
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="recovery", pattern=RECOVERY_MEMBERSHIP, after=CAMPAIGN_NKU)
        recovery = race.start("recovery", _recover(fx, stranded, editor))
        pause.wait_reached(recovery)
        end = race.start("end", _end(fx, member, by=owner))
        race.wait_blocked_by(pause, end)
        pause.release()
        race.join_all()
    _ok(recovery, end)
    assert _ended(fx, member)
    assert _owner_roles(fx, editor) == 0


def test_r3_an_end_that_meets_recovery_at_the_role_insert_commits_after_it(
    fx: Fixture, editor: uuid.UUID, stranded: uuid.UUID
) -> None:
    """R3, unchanged by S5-B (parent and now give the same result). Recovery holds the campaign and the
    membership and stops before inserting the owner role; the end locks the member's role rows and waits
    at the membership. Both commit, and the end's closure, a fresh statement, revokes the owner row
    recovery just inserted."""
    member = _membership_of(fx, editor)
    owner = _membership_of(fx, fx.owner)
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="recovery", pattern=ROLE_INSERT)
        recovery = race.start("recovery", _recover(fx, stranded, editor))
        pause.wait_reached(recovery)
        end = race.start("end", _end(fx, member, by=owner))
        race.wait_blocked_by(pause, end)
        pause.release()
        race.join_all()
    _ok(recovery, end)
    assert _ended(fx, member)
    assert _owner_roles(fx, editor) == 0


def test_r4_recovery_for_a_stranded_owner_who_is_removing_themself_serializes_after_the_end(
    fx: Fixture, stranded: uuid.UUID
) -> None:
    """R4. The stranded finite owner ends their own membership (parked holding it). Recovery for that
    same user is blocked by the end. Parent: 40P01 as R1. Now: the end commits, then recovery gives the
    user a new membership with the owner role."""
    own = _membership_of(fx, fx.owner)
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="end", pattern=END_ACTOR_LOCK)
        end = race.start("end", _end(fx, own, by=own))
        pause.wait_reached(end)
        recovery = race.start("recovery", _recover(fx, stranded, fx.owner))
        race.wait_blocked_by(pause, recovery)
        pause.release()
        race.join_all()
    _ok(end, recovery)
    assert _ended(fx, own)
    assert _open_memberships(fx, fx.owner) == 1
    assert _owner_roles(fx, fx.owner) == 1


def test_r5_recovery_for_another_user_finishes_while_an_end_is_paused(
    fx: Fixture, editor: uuid.UUID, stranded: uuid.UUID, newcomer: uuid.UUID
) -> None:
    """R5. An end of the editor's membership is paused before its campaign lock. Recovery for a user with
    no membership at all takes no membership lock (nothing to lock), then the campaign `FOR NO KEY
    UPDATE`, which the end does not hold, so it finishes meanwhile."""
    member = _membership_of(fx, editor)
    owner = _membership_of(fx, fx.owner)
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="end", pattern=END_ACTOR_LOCK)
        end = race.start("end", _end(fx, member, by=owner))
        pause.wait_reached(end)
        recovery = race.start("recovery", _recover(fx, stranded, newcomer))
        race.wait_done(recovery, why="recovery is waiting for the end of another user's membership")
        pause.release()
        race.join_all()
    _ok(end, recovery)
    assert _ended(fx, member)
    assert _owner_roles(fx, newcomer) == 1


# --- 2. a grant to the member recovery promotes (a current command that holds a membership, then the campaign) ----


def _grant_to(fx: Fixture, member: uuid.UUID) -> Callable[[Connection], Any]:
    with fx.engine.begin() as setup:
        character = make_character(setup, fx.world_id, name="Recovery Grant Target")
    return lambda c: create_resource_grant(
        c,
        campaign_id=fx.campaign_id,
        grantee_campaign_membership_id=member,
        grantee_access_group_id=None,
        capability_code="character.view_full",
        effect="allow",
        expected_world_id=fx.world_id,
        granted_by_membership_id=_membership_of(fx, fx.owner),
        character_id=character,
    )


def _grants(fx: Fixture, member: uuid.UUID) -> int:
    return fx.count(
        "SELECT count(*) FROM security.resource_grants WHERE grantee_campaign_membership_id = :m",
        m=member,
    )


def test_a_grant_that_holds_the_member_first_serializes_before_recovery(
    fx: Fixture, editor: uuid.UUID, stranded: uuid.UUID
) -> None:
    """The grant holds the member's membership and stops before its campaign `FOR UPDATE`. Recovery is
    blocked by the grant. Parent: recovery held the campaign `FOR NO KEY UPDATE` while it waited, so the
    released grant's campaign lock deadlocked with it (40P01). Now: recovery waits holding nothing."""
    member = _membership_of(fx, editor)
    grant_op = _grant_to(fx, member)
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="grant", pattern=GRANT_CAMPAIGN_LOCK)
        grant = race.start("grant", grant_op)
        pause.wait_reached(grant)
        recovery = race.start("recovery", _recover(fx, stranded, editor))
        race.wait_blocked_by(pause, recovery)
        pause.release()
        race.join_all()
    _ok(grant, recovery)
    assert _grants(fx, member) == 1
    assert _owner_roles(fx, editor) == 1


def test_recovery_that_holds_its_locks_first_serializes_before_a_grant_to_the_member(
    fx: Fixture, editor: uuid.UUID, stranded: uuid.UUID
) -> None:
    """Recovery stops before its membership lookup under the campaign lock. The grant is blocked by
    recovery's session. Parent: the grant locked the membership and waited for the campaign, and the
    released recovery wanted the membership (40P01). Now: the grant waits at the membership."""
    member = _membership_of(fx, editor)
    grant_op = _grant_to(fx, member)
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="recovery", pattern=RECOVERY_MEMBERSHIP, after=CAMPAIGN_NKU)
        recovery = race.start("recovery", _recover(fx, stranded, editor))
        pause.wait_reached(recovery)
        grant = race.start("grant", grant_op)
        race.wait_blocked_by(pause, grant)
        pause.release()
        race.join_all()
    _ok(recovery, grant)
    assert _grants(fx, member) == 1
    assert _owner_roles(fx, editor) == 1


# --- 3. the user has no open membership: a lock on no row protects nothing ----------------------------------


def _add(fx: Fixture, user: uuid.UUID) -> Callable[[Connection], Any]:
    with fx.engine.connect() as connection:
        role = connection.execute(
            text("SELECT role_id FROM security.roles WHERE code = 'gm' AND campaign_id IS NULL")
        ).scalar_one()
    by = _membership_of(fx, fx.owner)
    return lambda c: add_campaign_member(
        c, campaign_id=fx.campaign_id, user_id=user, role_id=role, added_by_membership_id=by
    )


def test_a_membership_created_while_recovery_waits_for_the_campaign_is_found_by_the_second_lookup(
    fx: Fixture, stranded: uuid.UUID, newcomer: uuid.UUID
) -> None:
    """The first lookup finds no row, so nothing is locked. An add of the same user holds the campaign
    `FOR UPDATE` and stops before inserting the membership; recovery's first lookup has run and it queues
    for the campaign. The add inserts and commits. Recovery then holds the campaign and looks again: it
    finds the new membership and uses it. Without the second lookup recovery would insert a second open
    membership and fail on `ux_campaign_memberships_open`. One open membership results, with both roles."""
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="add", pattern=MEMBERSHIP_INSERT)
        add = race.start("add", _add(fx, newcomer))
        pause.wait_reached(add)
        recovery = race.start("recovery", _recover(fx, stranded, newcomer))
        race.wait_blocked_by(pause, recovery)
        pause.release()
        race.join_all()
    _ok(add, recovery)
    assert _all_memberships(fx, newcomer) == 1
    assert _live_roles(fx, newcomer) == ["campaign_owner", "gm"]


def test_an_add_that_waited_for_recovery_is_refused_and_writes_nothing(
    fx: Fixture, stranded: uuid.UUID, newcomer: uuid.UUID
) -> None:
    """The other order. Recovery has created the membership's place in the queue (holds the campaign) and
    is parked before its second lookup; the add queues at the campaign. Recovery inserts the membership
    and the owner role and commits. The add then reaches its own insert and is refused by
    `ux_campaign_memberships_open` (an `IntegrityError`, the route's 409); its transaction rolls back,
    so the user has exactly recovery's membership, the owner role only, and no `gm` role."""
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="recovery", pattern=RECOVERY_MEMBERSHIP, after=CAMPAIGN_NKU)
        recovery = race.start("recovery", _recover(fx, stranded, newcomer))
        pause.wait_reached(recovery)
        add = race.start("add", _add(fx, newcomer))
        race.wait_blocked_by(pause, add)
        pause.release()
        race.join_all()
    _ok(recovery)
    assert isinstance(add.error, IntegrityError), add.describe()
    assert _all_memberships(fx, newcomer) == 1
    assert _live_roles(fx, newcomer) == ["campaign_owner"]


def test_an_ended_membership_is_ignored_and_a_new_one_is_created(
    fx: Fixture, editor: uuid.UUID, stranded: uuid.UUID
) -> None:
    """Branch check, no race: a user whose only membership has ended has no *open* membership, so recovery
    creates a new row, leaves the ended one as it was, and gives the new one the owner role."""
    member = _membership_of(fx, editor)
    with fx.engine.begin() as connection:
        end_campaign_membership(
            connection,
            campaign_membership_id=member,
            campaign_id=fx.campaign_id,
            ended_by_membership_id=_membership_of(fx, fx.owner),
        )
    with fx.engine.begin() as connection:
        _recover(fx, stranded, editor)(connection)
    assert _ended(fx, member)
    assert _all_memberships(fx, editor) == 2
    assert _open_memberships(fx, editor) == 1
    assert _owner_roles(fx, editor) == 1


# --- 4. repeated and competing recovery ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "has_membership", [True, False], ids=["existing_membership", "no_membership"]
)
def test_a_second_recovery_for_the_same_user_is_refused_as_not_needed(
    fx: Fixture,
    editor: uuid.UUID,
    stranded: uuid.UUID,
    newcomer: uuid.UUID,
    has_membership: bool,
) -> None:
    """The first recovery is parked under its locks; the second for the same user queues behind it (at
    the membership when there is one, at the campaign when there is none), then reads the committed
    result: the campaign has an active access manager, `RecoveryNotNeededError`. One owner role, one open
    membership."""
    user = editor if has_membership else newcomer
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="first", pattern=RECOVERY_MEMBERSHIP, after=CAMPAIGN_NKU)
        first = race.start("first", _recover(fx, stranded, user))
        pause.wait_reached(first)
        second = race.start("second", _recover(fx, stranded, user))
        race.wait_blocked_by(pause, second)
        pause.release()
        race.join_all()
    _ok(first)
    assert isinstance(second.error, RecoveryNotNeededError), second.describe()
    assert _open_memberships(fx, user) == 1
    assert _owner_roles(fx, user) == 1
