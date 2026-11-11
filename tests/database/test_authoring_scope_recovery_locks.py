# ruff: noqa: F811 - the imported fixture is used by parameter name
"""`lock_authoring_scope` against administrative recovery and its other campaign-row neighbours
(DEF-014, P03-A plan section 6).

`lock_authoring_scope` holds the author's membership `FOR SHARE` and then the campaign row.
`recover_campaign_access_manager` holds the campaign row `FOR NO KEY UPDATE` and then asks for the
membership it promotes `FOR UPDATE`. With the campaign taken `FOR SHARE` the two waited on each
other (SQLSTATE 40P01). The helper now takes the campaign `FOR KEY SHARE`, which still conflicts
with every `FOR UPDATE` taker (archive, settings, the retention trigger, resource-grant writes)
but not with recovery's `FOR NO KEY UPDATE`.

Every scenario is made deterministic with real PostgreSQL locks. Where a command must stop between
two of its own statements, `LockRace` (tests/lock_race_support.py) holds it there with a `before_cursor_execute` listener on
that command's thread. A wait is observed through `pg_blocking_pids` (the intended session,
followed along the queue), a request that finishes or fails before it blocks is reported as that,
and on exit, success or failure, every pause and held lock is released and every worker joined
before fixture teardown. No scenario relies on a longer timeout.
"""

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from sqlalchemy import Connection, text

from dnd_ai.commands.access_grants import create_resource_grant
from dnd_ai.commands.campaigns import archive_campaign, update_campaign
from dnd_ai.commands.memberships import end_campaign_membership, revoke_membership_role
from dnd_ai.commands.recovery import recover_campaign_access_manager
from dnd_ai.domain.authoring import CampaignArchivedError, CampaignNotAuthorizedError
from tests.database.test_content_authoring_concurrency import (  # noqa: F401 - fixture by name
    Fixture,
    _create_as,
    _deputy,
    _drop_user,
    fx,
)
from tests.factories import (
    lookup_id,
    make_character,
    make_membership_role,
    make_role,
    make_role_capability,
    make_system_role_assignment,
    make_user,
)
from tests.lock_race_support import LockRace, Worker

pytestmark = pytest.mark.database

# The helper's campaign statement, whichever lock mode it names.
CAMPAIGN_LOCK = r"FROM campaign\.campaigns WHERE campaign_id = \S+ FOR (KEY )?SHARE"
# The membership statement of recovery, after it holds the campaign row.
RECOVERY_MEMBERSHIP = r"FROM security\.campaign_memberships WHERE .* FOR UPDATE"
# The first statement of `lock_authoring_scope` after it holds the campaign row.
AFTER_CAMPAIGN_LOCK = r"FROM core\.lifecycle_statuses"


def _start(race: LockRace, operation: Callable[[Connection], object], name: str) -> Worker:
    return race.start(name, operation)


# --- fixtures ---------------------------------------------------------------------------------


def _world_editor(fx: Fixture, user: uuid.UUID) -> None:
    """Shared canon needs a world role as well as the campaign role (ADR 0020)."""
    with fx.engine.begin() as setup:
        setup.execute(
            text("""
                INSERT INTO security.world_memberships
                    (world_id, user_id, world_role_id, membership_status_id)
                VALUES (:w, :u,
                        (SELECT world_role_id FROM security.world_roles WHERE code = 'world_editor'),
                        (SELECT membership_status_id FROM security.membership_statuses
                         WHERE code = 'active'))
            """),
            {"w": fx.world_id, "u": user},
        )


def _membership_of(fx: Fixture, user: uuid.UUID) -> uuid.UUID:
    with fx.engine.connect() as connection:
        value = connection.execute(
            text(
                "SELECT campaign_membership_id FROM security.campaign_memberships "
                "WHERE campaign_id = :c AND user_id = :u AND ended_at IS NULL"
            ),
            {"c": fx.campaign_id, "u": user},
        ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


@pytest.fixture
def editor(fx: Fixture) -> Iterator[uuid.UUID]:
    """A member whose only campaign role is a custom one with `canon.edit`: an author who is not
    an owner, so recovery has an owner role to give them."""
    with fx.engine.begin() as setup:
        user = make_user(setup, "Recovery Editor")
        membership = setup.execute(
            text("""
                INSERT INTO security.campaign_memberships
                    (campaign_id, user_id, membership_status_id, joined_at)
                VALUES (:c, :u, (SELECT membership_status_id FROM security.membership_statuses
                                 WHERE code = 'active'), now())
                RETURNING campaign_membership_id
            """),
            {"c": fx.campaign_id, "u": user},
        ).scalar()
        role = make_role(setup, campaign_id=fx.campaign_id)
        make_role_capability(
            setup, role, lookup_id(setup, "security", "capabilities", "capability_id", "canon.edit")
        )
        make_role_capability(
            setup,
            role,
            lookup_id(setup, "security", "capabilities", "capability_id", "campaign.view"),
        )
        make_membership_role(setup, membership, role)
    _world_editor(fx, user)
    yield user
    _drop_user(fx.engine, user)
    with fx.engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM security.role_capabilities WHERE role_id = :r"), {"r": role}
        )
        cleanup.execute(text("DELETE FROM security.roles WHERE role_id = :r"), {"r": role})


@pytest.fixture
def stranded(fx: Fixture) -> Iterator[uuid.UUID]:
    """Strands the campaign the ordinary way and returns an administrator's user id. The
    creator's owner assignment becomes finite (which the retention trigger allows while the
    deputy's is not), then the deputy's account is archived, leaving no active non-expiring
    access manager, so recovery may run while the creator can still author."""
    deputy, _ = _deputy(fx)
    with fx.engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE security.membership_roles SET expires_at = now() + interval '1 day'
                WHERE revoked_at IS NULL AND membership_role_id IN (
                    SELECT mr.membership_role_id FROM security.membership_roles mr
                    JOIN security.campaign_memberships cm
                      ON cm.campaign_membership_id = mr.campaign_membership_id
                    WHERE cm.campaign_id = :c AND cm.user_id = :u)
            """),
            {"c": fx.campaign_id, "u": fx.owner},
        )
    with fx.engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE security.users SET lifecycle_status_id = (
                    SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived')
                WHERE user_id = :u
            """),
            {"u": deputy},
        )
        admin = make_user(connection, "Recovery Admin")
        make_system_role_assignment(connection, admin, "admin")
    yield admin
    _drop_user(fx.engine, deputy)
    with fx.engine.begin() as cleanup:
        cleanup.execute(
            text("DELETE FROM security.user_system_roles WHERE user_id = :u"), {"u": admin}
        )
        cleanup.execute(text("DELETE FROM security.users WHERE user_id = :u"), {"u": admin})


def _recover(fx: Fixture, admin: uuid.UUID, user: uuid.UUID) -> Callable[[Connection], Any]:
    return lambda c: recover_campaign_access_manager(
        c, admin_user_id=admin, campaign_id=fx.campaign_id, new_user_id=user, reason="Recover"
    )


def _location_count(fx: Fixture, name: str) -> int:
    return fx.count("SELECT count(*) FROM core.entities WHERE canonical_name = :n", n=name)


def _owner_roles(fx: Fixture, user: uuid.UUID) -> int:
    return fx.count(
        """
        SELECT count(*) FROM security.membership_roles mr
        JOIN security.campaign_memberships cm
          ON cm.campaign_membership_id = mr.campaign_membership_id
        JOIN security.roles r ON r.role_id = mr.role_id
        WHERE cm.campaign_id = :c AND cm.user_id = :u AND r.code = 'campaign_owner'
          AND mr.revoked_at IS NULL AND mr.expires_at IS NULL
        """,
        c=fx.campaign_id,
        u=user,
    )


# --- 1 and 2. recovery against an authoring write by the member it promotes --------------------


def test_recovery_waits_for_an_author_paused_before_its_campaign_lock_and_both_commit(
    fx: Fixture, editor: uuid.UUID, stranded: uuid.UUID
) -> None:
    """The reproduced DEF-014 case. The author holds its membership and stops just before the
    campaign statement; recovery takes the campaign and queues for that membership. Released, the
    author asks for the campaign: `FOR SHARE` waited for recovery (a deadlock), `FOR KEY SHARE`
    does not."""
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="author", pattern=CAMPAIGN_LOCK)
        author = _start(race, _create_as(fx, editor, "Beside recovery"), "author")
        pause.wait_reached(author)
        recovery = _start(race, _recover(fx, stranded, editor), "recovery")
        race.wait_blocked_by(pause, recovery)
        pause.release()
        race.join_all()
    assert author.error is None, author.error
    assert recovery.error is None, recovery.error
    assert _location_count(fx, "Beside recovery") == 1
    assert _owner_roles(fx, editor) == 1


def test_an_author_completes_while_recovery_is_paused_after_its_campaign_lock(
    fx: Fixture, editor: uuid.UUID, stranded: uuid.UUID
) -> None:
    """Recovery holds the campaign `FOR NO KEY UPDATE` and stops before its membership statement.
    The author must run to completion meanwhile: that is what `FOR KEY SHARE` allows and
    `FOR SHARE` did not. Then recovery resumes and commits."""
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="recovery", pattern=RECOVERY_MEMBERSHIP)
        recovery = _start(race, _recover(fx, stranded, editor), "recovery")
        pause.wait_reached(recovery)
        author = _start(race, _create_as(fx, editor, "During recovery"), "author")
        race.wait_done(author, why="the author is waiting for recovery's campaign lock")
        pause.release()
        race.join_all()
    assert author.error is None, author.error
    assert recovery.error is None, recovery.error
    assert _location_count(fx, "During recovery") == 1
    assert _owner_roles(fx, editor) == 1


# --- 3. archive and settings still serialize with an author --------------------------------------


@pytest.mark.parametrize("operation", ["archive", "settings"])
def test_a_campaign_archive_or_settings_edit_waits_for_an_author_that_holds_the_campaign(
    fx: Fixture, operation: str
) -> None:
    """The author stops just after taking the campaign `FOR KEY SHARE`. The archive (or settings
    edit), which takes the campaign `FOR UPDATE`, must queue behind it: blocked by the author's own
    session. The author's write then stands, and the campaign operation commits after."""

    def campaign_operation(c: Connection) -> Any:
        if operation == "archive":
            return archive_campaign(
                c,
                campaign_id=fx.campaign_id,
                actor_user_id=fx.owner,
                expected_row_version=fx.campaign_version,
            )
        return update_campaign(
            c,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            expected_row_version=fx.campaign_version,
            name="Renamed during authoring",
            description=None,
        )

    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="author", pattern=AFTER_CAMPAIGN_LOCK, after=CAMPAIGN_LOCK)
        author = _start(race, _create_as(fx, fx.owner, "Before the campaign change"), "author")
        pause.wait_reached(author)
        change = _start(race, campaign_operation, "campaign-change")
        race.wait_blocked_by(pause, change)
        pause.release()
        race.join_all()
    assert author.error is None, author.error
    assert change.error is None, change.error
    assert _location_count(fx, "Before the campaign change") == 1
    state = fx.count(
        "SELECT count(*) FROM campaign.campaigns WHERE campaign_id = :c AND "
        + (
            "lifecycle_status_id = (SELECT lifecycle_status_id FROM core.lifecycle_statuses "
            "WHERE code = 'archived')"
            if operation == "archive"
            else "name = 'Renamed during authoring'"
        ),
        c=fx.campaign_id,
    )
    assert state == 1


def test_an_author_started_during_an_archive_is_refused(fx: Fixture) -> None:
    """The other order: the archive holds the campaign `FOR UPDATE`; an author queues at its
    campaign `FOR KEY SHARE` (observed as blocked by the archiver) and, once the archive commits,
    reads the archived status and is refused with nothing written."""
    from tests.database.test_content_authoring_concurrency import observed_race

    out = observed_race(
        fx.engine,
        lambda c: archive_campaign(
            c,
            campaign_id=fx.campaign_id,
            actor_user_id=fx.owner,
            expected_row_version=fx.campaign_version,
        ),
        _create_as(fx, fx.owner, "Too late again"),
    )
    assert isinstance(out["error"], CampaignArchivedError)
    assert _location_count(fx, "Too late again") == 0


# --- 4. role loss ---------------------------------------------------------------------------------


def test_revoking_a_built_in_owner_role_waits_for_an_author_past_the_campaign_lock(
    fx: Fixture,
) -> None:
    """The deputy is a built-in owner. The deputy stops after taking its role and membership rows
    `FOR SHARE` and the campaign `FOR KEY SHARE`. The revocation queues at the role row (blocked by
    the author); released, the author's write stands. The revocation's deferred retention trigger
    then takes the campaign `FOR UPDATE` at commit, which must not deadlock with the author."""
    deputy, role = _deputy(fx)
    try:
        with LockRace(fx.engine) as race:
            pause = race.pause(
                thread_name="author", pattern=AFTER_CAMPAIGN_LOCK, after=CAMPAIGN_LOCK
            )
            author = _start(race, _create_as(fx, deputy, "Before the role loss"), "author")
            pause.wait_reached(author)
            revoke = _start(
                race,
                lambda c: revoke_membership_role(
                    c, membership_role_id=role, campaign_id=fx.campaign_id
                ),
                "revoke",
            )
            race.wait_blocked_by(pause, revoke)
            pause.release()
            race.join_all()
        assert author.error is None, author.error
        assert revoke.error is None, revoke.error
        assert _location_count(fx, "Before the role loss") == 1
    finally:
        _drop_user(fx.engine, deputy)


def test_an_author_whose_built_in_owner_role_is_being_revoked_is_refused(fx: Fixture) -> None:
    """The other order, with the wait observed on the revoker's session: the author queues at its
    role-row lock and, once the revocation commits, is refused with nothing written."""
    from tests.database.test_content_authoring_concurrency import observed_race

    deputy, role = _deputy(fx)
    try:
        out = observed_race(
            fx.engine,
            lambda c: revoke_membership_role(
                c, membership_role_id=role, campaign_id=fx.campaign_id
            ),
            _create_as(fx, deputy, "After the role loss"),
        )
        assert isinstance(out["error"], CampaignNotAuthorizedError)
        assert _location_count(fx, "After the role loss") == 0
    finally:
        _drop_user(fx.engine, deputy)


# --- 5. membership end -------------------------------------------------------------------------------


def test_ending_a_membership_waits_for_its_authors_in_flight_write_and_the_write_stands(
    fx: Fixture,
) -> None:
    deputy, _ = _deputy(fx)
    ended_by = _membership_of(fx, fx.owner)
    target = _membership_of(fx, deputy)
    try:
        with LockRace(fx.engine) as race:
            pause = race.pause(
                thread_name="author", pattern=AFTER_CAMPAIGN_LOCK, after=CAMPAIGN_LOCK
            )
            author = _start(race, _create_as(fx, deputy, "Before the end"), "author")
            pause.wait_reached(author)
            end = _start(
                race,
                lambda c: end_campaign_membership(
                    c,
                    campaign_membership_id=target,
                    campaign_id=fx.campaign_id,
                    ended_by_membership_id=ended_by,
                ),
                "end",
            )
            race.wait_blocked_by(pause, end)
            pause.release()
            race.join_all()
        assert author.error is None, author.error
        assert end.error is None, end.error
        assert _location_count(fx, "Before the end") == 1
        assert (
            fx.count(
                "SELECT count(*) FROM security.campaign_memberships "
                "WHERE campaign_membership_id = :m AND ended_at IS NOT NULL",
                m=target,
            )
            == 1
        )
    finally:
        _drop_user(fx.engine, deputy)


def test_an_author_whose_membership_is_being_ended_is_refused_and_writes_nothing(
    fx: Fixture,
) -> None:
    from tests.database.test_content_authoring_concurrency import observed_race

    deputy, _ = _deputy(fx)
    ended_by = _membership_of(fx, fx.owner)
    target = _membership_of(fx, deputy)
    try:
        out = observed_race(
            fx.engine,
            lambda c: end_campaign_membership(
                c,
                campaign_membership_id=target,
                campaign_id=fx.campaign_id,
                ended_by_membership_id=ended_by,
            ),
            _create_as(fx, deputy, "After the end"),
        )
        assert isinstance(out["error"], CampaignNotAuthorizedError)
        assert _location_count(fx, "After the end") == 0
    finally:
        _drop_user(fx.engine, deputy)


# --- account deactivation ----------------------------------------------------------------------------


def _deactivate(user: uuid.UUID) -> Callable[[Connection], Any]:
    """The application has no command that deactivates an account; the account row is the only
    thing the helper's account lock guards, so a direct update is the competing writer."""
    return lambda c: c.execute(
        text("""
            UPDATE security.users SET lifecycle_status_id = (
                SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived')
            WHERE user_id = :u
        """),
        {"u": user},
    )


def test_account_deactivation_waits_for_an_in_flight_author_and_the_write_stands(
    fx: Fixture,
) -> None:
    deputy, _ = _deputy(fx)
    try:
        with LockRace(fx.engine) as race:
            pause = race.pause(
                thread_name="author", pattern=AFTER_CAMPAIGN_LOCK, after=CAMPAIGN_LOCK
            )
            author = _start(race, _create_as(fx, deputy, "Before deactivation"), "author")
            pause.wait_reached(author)
            deactivation = _start(race, _deactivate(deputy), "deactivation")
            race.wait_blocked_by(pause, deactivation)
            pause.release()
            race.join_all()
        assert author.error is None, author.error
        assert deactivation.error is None, deactivation.error
        assert _location_count(fx, "Before deactivation") == 1
    finally:
        _drop_user(fx.engine, deputy)


def test_an_author_whose_account_is_being_deactivated_is_refused(fx: Fixture) -> None:
    from tests.database.test_content_authoring_concurrency import observed_race

    deputy, _ = _deputy(fx)
    try:
        out = observed_race(
            fx.engine, _deactivate(deputy), _create_as(fx, deputy, "After deactivation")
        )
        assert isinstance(out["error"], CampaignNotAuthorizedError)
        assert _location_count(fx, "After deactivation") == 0
    finally:
        _drop_user(fx.engine, deputy)


# --- 6. a deny is still ordered -------------------------------------------------------------------------


def test_an_author_waits_for_an_in_flight_deny_grant_on_the_campaign_row(fx: Fixture) -> None:
    """`create_resource_grant` takes the campaign `FOR UPDATE`; an author must queue behind it at
    its campaign `FOR KEY SHARE` (blocked by the granter's session). This protects the ordering
    D8's deny re-check will rely on; it asserts the wait and that both commit, not what an
    authoring command makes of a per-character deny."""
    from tests.database.test_content_authoring_concurrency import observed_race

    deputy, _ = _deputy(fx)
    granter = _membership_of(fx, fx.owner)
    grantee = _membership_of(fx, deputy)
    with fx.engine.begin() as setup:
        character = make_character(setup, fx.world_id, name="Denied Character")
    try:
        out = observed_race(
            fx.engine,
            lambda c: create_resource_grant(
                c,
                campaign_id=fx.campaign_id,
                grantee_campaign_membership_id=grantee,
                grantee_access_group_id=None,
                capability_code="character.view_full",
                effect="deny",
                expected_world_id=fx.world_id,
                granted_by_membership_id=granter,
                character_id=character,
            ),
            _create_as(fx, deputy, "Beside a deny"),
        )
        assert "error" not in out, out
        assert _location_count(fx, "Beside a deny") == 1
        assert (
            fx.count(
                "SELECT count(*) FROM security.resource_grants "
                "WHERE campaign_id = :c AND effect = 'deny' AND revoked_at IS NULL",
                c=fx.campaign_id,
            )
            == 1
        )
    finally:
        with fx.engine.begin() as cleanup:
            cleanup.execute(text("SET LOCAL session_replication_role = replica"))
            cleanup.execute(
                text("DELETE FROM security.resource_grants WHERE campaign_id = :c"),
                {"c": fx.campaign_id},
            )
        _drop_user(fx.engine, deputy)
