# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""`add_access_group_members` against the commands it met in the wrong lock order (DEF-015).

The add took the campaign `FOR UPDATE` and then each member's membership; every authoring command,
the end of a membership and an A2a release take the membership first and the campaign after. The
add now locks the group, the members' memberships (`FOR NO KEY UPDATE`), the acting membership
(`FOR KEY SHARE`), then the campaign (`FOR KEY SHARE`). Each scenario pairs the add with one of
those commands in both orders, with real PostgreSQL locks and `LockRace` (tests/lock_race_support.py).
A wait is observed through `pg_blocking_pids` as blocked by the intended session, or the scenario
asserts the second command finished while the first was paused; no scenario relies on a longer
timeout or on `lock_timeout`.

Where the statement text matters, the pause patterns accept both the old and the new statements of
the add, so each scenario can be run against the parent commit.
"""

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from sqlalchemy import Connection, text

from dnd_ai.commands.access_grants import MembershipNotActiveError, create_resource_grant
from dnd_ai.commands.access_groups import (
    add_access_group_members,
    create_access_group,
)
from dnd_ai.commands.memberships import end_campaign_membership, revoke_membership_role
from dnd_ai.commands.recovery import recover_campaign_access_manager  # noqa: F401
from tests.database.test_authoring_concurrency import _client_for
from tests.database.test_authoring_scope_recovery_locks import (  # noqa: F401 - fixtures by name
    AFTER_CAMPAIGN_LOCK,
    CAMPAIGN_LOCK,
    RECOVERY_MEMBERSHIP,
    _location_count,
    _membership_of,
    _owner_roles,
    _recover,
    editor,
    stranded,
)
from tests.database.test_content_authoring_concurrency import (  # noqa: F401 - fixture by name
    Fixture,
    _create_as,
    _deputy,
    _drop_user,
    fx,
)
from tests.factories import make_character
from tests.lock_race_support import LockRace

pytestmark = pytest.mark.database

# The add's statement just before its second family of locks: the old membership statement (the
# add already holds the campaign `FOR UPDATE`) or the new campaign statement (the add already holds
# the members' memberships).
ADD_SECOND_LOCK = (
    r"FROM security\.campaign_memberships cm JOIN .* FOR UPDATE OF cm"
    r"|FROM campaign\.campaigns c JOIN .* FOR KEY SHARE OF c"
)
ADD_INSERT = r"INSERT INTO security\.access_group_memberships"
ADD_ACCOUNT_LOCK = r"FROM security\.users u JOIN .* FOR (UPDATE|KEY SHARE) OF u"


# --- fixtures and helpers -------------------------------------------------------------------------


@pytest.fixture
def make_group(fx: Fixture) -> Iterator[Callable[[str], uuid.UUID]]:
    created: list[uuid.UUID] = []

    def _make(name: str) -> uuid.UUID:
        with fx.engine.begin() as connection:
            result = create_access_group(
                connection, campaign_id=fx.campaign_id, name=name, description=None
            )
        created.append(result.access_group_id)
        return result.access_group_id

    yield _make
    with fx.engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        for group in created:
            cleanup.execute(
                text("DELETE FROM security.access_group_memberships WHERE access_group_id = :g"),
                {"g": group},
            )
            cleanup.execute(
                text("DELETE FROM security.resource_grants WHERE grantee_access_group_id = :g"),
                {"g": group},
            )
            cleanup.execute(
                text("DELETE FROM security.access_groups WHERE access_group_id = :g"), {"g": group}
            )


@pytest.fixture
def group(make_group: Callable[[str], uuid.UUID]) -> uuid.UUID:
    return make_group("Lock Race Group")


def _add(
    fx: Fixture, group_id: uuid.UUID, member: uuid.UUID, *, by: uuid.UUID | None = None
) -> Callable[[Connection], Any]:
    """Adds the membership `member` to the group, as the campaign creator unless `by` names the
    acting membership."""
    actor = by if by is not None else _membership_of(fx, fx.owner)
    return lambda c: add_access_group_members(
        c,
        access_group_id=group_id,
        campaign_membership_ids=(member,),
        campaign_id=fx.campaign_id,
        added_by_membership_id=actor,
    )


def _group_rows(fx: Fixture, group_id: uuid.UUID, member: uuid.UUID) -> list[bool]:
    """One entry per `access_group_memberships` row of the pair: whether it is still open."""
    with fx.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT removed_at IS NULL FROM security.access_group_memberships "
                "WHERE access_group_id = :g AND campaign_membership_id = :m ORDER BY added_at"
            ),
            {"g": group_id, "m": member},
        ).scalars()
        return [bool(row) for row in rows]


def _end(fx: Fixture, target: uuid.UUID, *, by: uuid.UUID) -> Callable[[Connection], Any]:
    return lambda c: end_campaign_membership(
        c, campaign_membership_id=target, campaign_id=fx.campaign_id, ended_by_membership_id=by
    )


# --- 1 and 2. an authoring write by the member being added ----------------------------------------


def test_adding_a_member_waits_for_that_members_author_paused_before_its_campaign_lock(
    fx: Fixture, editor: uuid.UUID, group: uuid.UUID
) -> None:
    """S1. The author holds its membership `FOR SHARE` and stops before the campaign statement.
    The add queues for that membership; released, the author takes the campaign `KEY SHARE` and
    both commit. Campaign-first, the add held the campaign `FOR UPDATE` while it queued, and the
    author's campaign lock deadlocked with it."""
    member = _membership_of(fx, editor)
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="author", pattern=CAMPAIGN_LOCK)
        author = race.start("author", _create_as(fx, editor, "Author before add"))
        pause.wait_reached(author)
        add = race.start("add", _add(fx, group, member))
        race.wait_blocked_by(pause, add)
        pause.release()
        race.join_all()
    assert author.error is None, author.error
    assert add.error is None, add.error
    assert _location_count(fx, "Author before add") == 1
    assert _group_rows(fx, group, member) == [True]


def test_an_author_waits_for_an_add_paused_before_its_second_lock(
    fx: Fixture, editor: uuid.UUID, group: uuid.UUID
) -> None:
    """S2. The add stops before its second family of locks (campaign-first: holding the campaign;
    now: holding the members' memberships). The author is blocked by the add; released, both
    commit."""
    member = _membership_of(fx, editor)
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="add", pattern=ADD_SECOND_LOCK)
        add = race.start("add", _add(fx, group, member))
        pause.wait_reached(add)
        author = race.start("author", _create_as(fx, editor, "Author after add"))
        race.wait_blocked_by(pause, author)
        pause.release()
        race.join_all()
    assert add.error is None, add.error
    assert author.error is None, author.error
    assert _location_count(fx, "Author after add") == 1
    assert _group_rows(fx, group, member) == [True]


# --- 3. recovery, both orders ------------------------------------------------------------------------


def test_adding_the_member_recovery_promotes_finishes_while_recovery_is_paused(
    fx: Fixture, editor: uuid.UUID, stranded: uuid.UUID, group: uuid.UUID
) -> None:
    """S3. Recovery holds the campaign `FOR NO KEY UPDATE` and stops before its membership
    statement. The add must finish meanwhile (`KEY SHARE` does not wait for `NO KEY UPDATE`), and
    then recovery commits. With the campaign `FOR UPDATE` the add waits at the campaign."""
    member = _membership_of(fx, editor)
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="recovery", pattern=RECOVERY_MEMBERSHIP)
        recovery = race.start("recovery", _recover(fx, stranded, editor))
        pause.wait_reached(recovery)
        add = race.start("add", _add(fx, group, member))
        race.wait_done(add, why="the add is waiting for recovery's campaign lock")
        pause.release()
        race.join_all()
    assert add.error is None, add.error
    assert recovery.error is None, recovery.error
    assert _group_rows(fx, group, member) == [True]
    assert _owner_roles(fx, editor) == 1


def test_recovery_waits_at_the_membership_for_an_add_paused_before_its_second_lock(
    fx: Fixture, editor: uuid.UUID, stranded: uuid.UUID, group: uuid.UUID
) -> None:
    """S4. The other order: recovery is blocked by the add, and both commit."""
    member = _membership_of(fx, editor)
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="add", pattern=ADD_SECOND_LOCK)
        add = race.start("add", _add(fx, group, member))
        pause.wait_reached(add)
        recovery = race.start("recovery", _recover(fx, stranded, editor))
        race.wait_blocked_by(pause, recovery)
        pause.release()
        race.join_all()
    assert add.error is None, add.error
    assert recovery.error is None, recovery.error
    assert _group_rows(fx, group, member) == [True]
    assert _owner_roles(fx, editor) == 1


# --- 4. ending the added member's membership, both orders -----------------------------------------------


def test_an_add_that_waited_for_the_end_of_the_members_membership_is_refused_as_not_active(
    fx: Fixture, editor: uuid.UUID, group: uuid.UUID
) -> None:
    """S5. The end holds the member's membership (`FOR UPDATE`) and its commit will need the campaign
    `FOR UPDATE` (the retention trigger). The add is blocked by the end without holding the
    campaign, so the end commits; the add then reads the ended membership and is refused 409-class
    (`MembershipNotActiveError`), not 404-class: the member rows are locked without a join to
    `membership_statuses`, which READ COMMITTED would re-check against the old status row."""
    member = _membership_of(fx, editor)
    owner = _membership_of(fx, fx.owner)
    with LockRace(fx.engine) as race:
        end = race.hold(_end(fx, member, by=owner))
        add = race.start("add", _add(fx, group, member))
        race.wait_blocked_by(end, add)
        end.commit()
        race.join_all()
    assert isinstance(add.error, MembershipNotActiveError), add.error
    assert _group_rows(fx, group, member) == []


def test_ending_a_membership_waits_for_an_add_and_closes_the_row_the_add_wrote(
    fx: Fixture, editor: uuid.UUID, group: uuid.UUID
) -> None:
    """S6. The add stops before its second lock; the end is blocked by the add (at the membership,
    or at commit for the campaign). Both commit, and the end closes the group row the add inserted,
    because its `UPDATE` takes a fresh snapshot after its wait."""
    member = _membership_of(fx, editor)
    owner = _membership_of(fx, fx.owner)
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="add", pattern=ADD_SECOND_LOCK)
        add = race.start("add", _add(fx, group, member))
        pause.wait_reached(add)
        end = race.start("end", _end(fx, member, by=owner))
        race.wait_blocked_by(pause, end)
        pause.release()
        race.join_all()
    assert add.error is None, add.error
    assert end.error is None, end.error
    assert _group_rows(fx, group, member) == [False]
    assert (
        add.result.access_group_membership_ids[0] in end.result.removed_access_group_membership_ids
    )


# --- 5. ending the acting membership, both orders --------------------------------------------------------


def test_ending_the_actors_membership_waits_for_an_add_paused_before_its_insert(
    fx: Fixture, editor: uuid.UUID, group: uuid.UUID
) -> None:
    """S9. A second owner adds the editor. The add stops just before its insert, which names the
    owner's membership in `added_by_membership_id`; ending that membership is blocked by the add
    (the actor's `KEY SHARE`). Both commit."""
    deputy, _ = _deputy(fx)
    try:
        actor = _membership_of(fx, deputy)
        member = _membership_of(fx, editor)
        owner = _membership_of(fx, fx.owner)
        with LockRace(fx.engine) as race:
            pause = race.pause(thread_name="add", pattern=ADD_INSERT)
            add = race.start("add", _add(fx, group, member, by=actor))
            pause.wait_reached(add)
            end = race.start("end", _end(fx, actor, by=owner))
            race.wait_blocked_by(pause, end)
            pause.release()
            race.join_all()
        assert add.error is None, add.error
        assert end.error is None, end.error
        assert _group_rows(fx, group, member) == [True]
    finally:
        _drop_user(fx.engine, deputy)


def test_an_add_waits_for_the_end_of_the_actors_membership_and_both_commit(
    fx: Fixture, editor: uuid.UUID, group: uuid.UUID
) -> None:
    """S10. The end of the acting owner's membership is held; the add queues at the actor's
    `KEY SHARE` before it takes the campaign, so the end's commit-time campaign lock is free and
    both commit. (The add's authorization is not re-checked under lock: it still commits and names
    an ended membership. Recorded as a separate follow-up, not changed here.)"""
    deputy, _ = _deputy(fx)
    try:
        actor = _membership_of(fx, deputy)
        member = _membership_of(fx, editor)
        owner = _membership_of(fx, fx.owner)
        with LockRace(fx.engine) as race:
            end = race.hold(_end(fx, actor, by=owner))
            add = race.start("add", _add(fx, group, member, by=actor))
            race.wait_blocked_by(end, add)
            end.commit()
            race.join_all()
        assert add.error is None, add.error
        assert _group_rows(fx, group, member) == [True]
    finally:
        _drop_user(fx.engine, deputy)


# --- 6. a resource grant made by the member being added ------------------------------------------------


def _grant_by(fx: Fixture, granter: uuid.UUID, grantee: uuid.UUID, character: uuid.UUID) -> Any:
    return lambda c: create_resource_grant(
        c,
        campaign_id=fx.campaign_id,
        grantee_campaign_membership_id=grantee,
        grantee_access_group_id=None,
        capability_code="character.view_full",
        effect="allow",
        expected_world_id=fx.world_id,
        granted_by_membership_id=granter,
        character_id=character,
    )


def test_an_add_waits_for_a_grant_made_by_the_member_being_added(
    fx: Fixture, editor: uuid.UUID, group: uuid.UUID
) -> None:
    """S11. The grant, made by the member being added, holds the campaign `FOR UPDATE` and its
    insert took `KEY SHARE` on that member's membership. The add takes the membership
    `NO KEY UPDATE` (compatible) and waits only for the campaign."""
    deputy, _ = _deputy(fx)
    try:
        member = _membership_of(fx, editor)
        grantee = _membership_of(fx, deputy)
        with fx.engine.begin() as setup:
            character = make_character(setup, fx.world_id, name="Granted Character")
        with LockRace(fx.engine) as race:
            grant = race.hold(_grant_by(fx, member, grantee, character))
            add = race.start("add", _add(fx, group, member))
            race.wait_blocked_by(grant, add)
            grant.commit()
            race.join_all()
        assert add.error is None, add.error
        assert _group_rows(fx, group, member) == [True]
    finally:
        _drop_user(fx.engine, deputy)
        with fx.engine.begin() as cleanup:
            cleanup.execute(text("SET LOCAL session_replication_role = replica"))
            cleanup.execute(
                text("DELETE FROM security.resource_grants WHERE campaign_id = :c"),
                {"c": fx.campaign_id},
            )


def test_a_grant_made_by_the_member_being_added_finishes_while_the_add_is_paused(
    fx: Fixture, editor: uuid.UUID, group: uuid.UUID
) -> None:
    """S12. The add holds the member's membership and stops before the campaign. The grant by that
    member takes the campaign `FOR UPDATE`, then `KEY SHARE` on the member's membership for its
    insert: compatible with `NO KEY UPDATE`, so it finishes. With the membership `FOR UPDATE` it
    would wait for the add while the add waited for the campaign, a deadlock."""
    deputy, _ = _deputy(fx)
    try:
        member = _membership_of(fx, editor)
        grantee = _membership_of(fx, deputy)
        with fx.engine.begin() as setup:
            character = make_character(setup, fx.world_id, name="Granted Character")
        with LockRace(fx.engine) as race:
            pause = race.pause(thread_name="add", pattern=ADD_SECOND_LOCK)
            add = race.start("add", _add(fx, group, member))
            pause.wait_reached(add)
            grant = race.start("grant", _grant_by(fx, member, grantee, character))
            race.wait_done(grant, why="the grant is waiting for the add")
            pause.release()
            race.join_all()
        assert grant.error is None, grant.error
        assert add.error is None, add.error
        assert _group_rows(fx, group, member) == [True]
    finally:
        _drop_user(fx.engine, deputy)
        with fx.engine.begin() as cleanup:
            cleanup.execute(text("SET LOCAL session_replication_role = replica"))
            cleanup.execute(
                text("DELETE FROM security.resource_grants WHERE campaign_id = :c"),
                {"c": fx.campaign_id},
            )


# --- 7. role revocation of the added member ---------------------------------------------------------------


def test_a_role_revocation_waits_at_commit_for_an_add_holding_the_campaign(
    fx: Fixture, editor: uuid.UUID, group: uuid.UUID
) -> None:
    """S13. The add stops before its account lock, holding the campaign. The revocation of the
    member's custom role writes its role row at once and needs the campaign `FOR UPDATE` at commit
    (the retention trigger): blocked by the add. Both commit."""
    member = _membership_of(fx, editor)
    with fx.engine.connect() as connection:
        role = connection.execute(
            text(
                "SELECT membership_role_id FROM security.membership_roles "
                "WHERE campaign_membership_id = :m AND revoked_at IS NULL"
            ),
            {"m": member},
        ).scalar_one()
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="add", pattern=ADD_ACCOUNT_LOCK)
        add = race.start("add", _add(fx, group, member))
        pause.wait_reached(add)
        revoke = race.start(
            "revoke",
            lambda c: revoke_membership_role(
                c, membership_role_id=role, campaign_id=fx.campaign_id
            ),
        )
        race.wait_blocked_by(pause, revoke)
        pause.release()
        race.join_all()
    assert add.error is None, add.error
    assert revoke.error is None, revoke.error
    assert _group_rows(fx, group, member) == [True]


# --- 8. crossed adds ------------------------------------------------------------------------------------------


def test_crossed_adds_into_different_groups_do_not_wait_for_each_other(
    fx: Fixture, make_group: Callable[[str], uuid.UUID]
) -> None:
    """S14. The owner adds the second owner to G1 and, meanwhile, the second owner adds the owner
    to G2. The first add is paused before its second family of locks; the second must finish: the
    actor's `KEY SHARE` conflicts with neither `NO KEY UPDATE` nor the campaign `KEY SHARE`."""
    deputy, _ = _deputy(fx)
    try:
        first_group = make_group("Crossed One")
        second_group = make_group("Crossed Two")
        owner = _membership_of(fx, fx.owner)
        other = _membership_of(fx, deputy)
        with LockRace(fx.engine) as race:
            pause = race.pause(thread_name="add-one", pattern=ADD_SECOND_LOCK)
            first = race.start("add-one", _add(fx, first_group, other, by=owner))
            pause.wait_reached(first)
            second = race.start("add-two", _add(fx, second_group, owner, by=other))
            race.wait_done(second, why="the crossed add is waiting for the first")
            pause.release()
            race.join_all()
        assert first.error is None, first.error
        assert second.error is None, second.error
        assert _group_rows(fx, first_group, other) == [True]
        assert _group_rows(fx, second_group, owner) == [True]
    finally:
        _drop_user(fx.engine, deputy)


# --- 9. through the API, with an Idempotency-Key ----------------------------------------------------------------


def test_the_add_endpoint_commits_beside_an_author_and_replays_its_receipt(
    fx: Fixture, editor: uuid.UUID, group: uuid.UUID
) -> None:
    """The endpoint's own locks (the idempotency reservation's foreign keys, then the command, then
    the audit insert's foreign key on the actor's account) around an author paused before its
    campaign lock: 201, one audit row, one receipt, the author's write stands, and a replay of the
    key returns the stored response."""
    member = _membership_of(fx, editor)
    client = _client_for(fx.engine, fx.owner)
    key = f"add-lock-{uuid.uuid4().hex[:8]}"
    url = f"/campaigns/{fx.campaign_id}/access-groups/{group}/members"
    body = {"campaign_membership_ids": [str(member)]}
    try:
        with LockRace(fx.engine) as race:
            pause = race.pause(thread_name="author", pattern=CAMPAIGN_LOCK)
            author = race.start("author", _create_as(fx, editor, "Author beside the endpoint"))
            pause.wait_reached(author)
            request = race.start(
                "add-api",
                lambda _c: client.post(url, json=body, headers={"Idempotency-Key": key}),
            )
            race.wait_blocked_by(pause, request)
            pause.release()
            race.join_all()
        response = request.result
        assert request.error is None, request.error
        assert response.status_code == 201, response.text  # type: ignore[attr-defined]
        assert author.error is None, author.error
        assert _location_count(fx, "Author beside the endpoint") == 1
        assert _group_rows(fx, group, member) == [True]
        assert (
            fx.count(
                "SELECT count(*) FROM audit.change_log WHERE command_name = 'add_access_group_member' "
                "AND changed_fields ->> 'access_group_id' = :g",
                g=str(group),
            )
            == 1
        )
        assert (
            fx.count(
                "SELECT count(*) FROM security.idempotent_requests "
                "WHERE campaign_id = :c AND idempotency_key = :k",
                c=fx.campaign_id,
                k=key,
            )
            == 1
        )
        replay = client.post(url, json=body, headers={"Idempotency-Key": key})
        assert replay.status_code == 201, replay.text
        assert replay.json() == response.json()  # type: ignore[attr-defined]
        assert _group_rows(fx, group, member) == [True]
    finally:
        client.__exit__(None, None, None)
