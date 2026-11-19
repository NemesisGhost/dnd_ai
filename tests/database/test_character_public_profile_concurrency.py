# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""Lock-order races for the public-profile commands (P03-A A2a, plan section 5.8, criterion 6).

The commands run on their own connections and threads under `LockRace`
(tests/lock_race_support.py): a `before_cursor_execute` listener stops one command between two of
its own statements, or a held uncommitted command stands in for a competitor, and every wait is
observed through `pg_blocking_pids` as blocked by the intended session. Nothing relies on a longer
timeout, and every pause and hold is released and every worker joined before fixture teardown.

The release takes: reveal-authority rows, the caller's membership `FOR SHARE`, the campaign `KEY
SHARE`, the character's entity `KEY SHARE`, then the draft `FOR UPDATE`, and re-judges its authority
at a fresh instant after the last wait. The save takes `lock_authoring_scope`'s locks, the
character's entity `FOR SHARE`, then the draft `FOR UPDATE`.
"""

import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.access_grants import create_resource_grant
from dnd_ai.commands.access_groups import add_access_group_members, create_access_group
from dnd_ai.commands.character_public_profile import (
    release_character_public_profile,
    save_character_public_profile_draft,
)
from dnd_ai.commands.character_reveal import revoke_character_reveal_delegation
from dnd_ai.commands.memberships import revoke_membership_role, transfer_campaign_ownership
from dnd_ai.domain.authoring import CampaignNotAuthorizedError, StaleWriteError
from dnd_ai.domain.public_profiles import (
    CharacterRevealRequiredError,
    PublicProfileCharacterNotActiveError,
    PublicProfileEditDeniedError,
    PublicProfileNotFoundError,
)
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_character_public_profile_api import (  # noqa: F401 - fixtures by name
    APPEARANCE,
    Prof,
    counts,
    draft_row,
    prof,
    release_rows,
)
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.lock_race_support import LockRace
from tests.r01_support import fixture_plan

pytestmark = pytest.mark.database

CLOCK = r"SELECT clock_timestamp\(\)"
SAVE_UPDATE = r"UPDATE campaign\.character_public_profiles SET"
RELEASE_CAMPAIGN = r"FROM campaign\.campaigns WHERE campaign_id = \S+ FOR KEY SHARE"
SAVE_CAMPAIGN = r"FROM campaign\.campaigns WHERE campaign_id = \S+ FOR KEY SHARE"
ADD_SECOND_LOCK = (
    r"FROM security\.campaign_memberships cm JOIN .* FOR UPDATE OF cm"
    r"|FROM campaign\.campaigns c JOIN .* FOR KEY SHARE OF c"
)


# --- operations -------------------------------------------------------------------------------------


def do_save(
    g: Gate, character: uuid.UUID, user: uuid.UUID, expected: int | None, **fields: str | None
) -> Callable[[Connection], Any]:
    return lambda c: save_character_public_profile_draft(
        c,
        campaign_id=g.campaign_id,
        character_id=character,
        actor_user_id=user,
        expected_row_version=expected,
        fields=dict(fields),
        plan=fixture_plan(c, g.campaign_id),
    )


def do_release(
    g: Gate, character: uuid.UUID, membership: uuid.UUID, version: int
) -> Callable[[Connection], Any]:
    return lambda c: release_character_public_profile(
        c,
        campaign_id=g.campaign_id,
        character_id=character,
        actor_membership_id=membership,
        expected_draft_row_version=version,
        release_note=None,
        plan=fixture_plan(c, g.campaign_id),
    )


def seed(engine: Engine, g: Gate, character: uuid.UUID, text_value: str = APPEARANCE) -> None:
    with engine.begin() as connection:
        save_character_public_profile_draft(
            connection,
            campaign_id=g.campaign_id,
            character_id=character,
            actor_user_id=g.o1_user_id,
            expected_row_version=None,
            fields={"public_appearance": text_value},
            plan=fixture_plan(connection, g.campaign_id),
        )


def nothing_written_beyond(engine: Engine, g: Gate, before: tuple[int, int, int, int]) -> None:
    drafts, releases, _audit, revisions = counts(engine, g)
    assert (drafts, releases, revisions) == (before[0], before[1], before[3])


# --- saves ------------------------------------------------------------------------------------------


def test_two_saves_with_one_token_commit_one_and_the_second_is_stale(
    postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    seed(postgres_engine, g, c)
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="first", pattern=SAVE_UPDATE)
        first = race.start("first", do_save(g, c, g.o1_user_id, 1, public_appearance="first"))
        pause.wait_reached(first)  # holds the draft FOR UPDATE
        second = race.start("second", do_save(g, c, g.o1_user_id, 1, public_appearance="second"))
        race.wait_blocked_by(pause, second)
        pause.release()
        race.join_all()
    assert first.error is None and first.result.row_version == 2
    assert isinstance(second.error, StaleWriteError)
    assert draft_row(postgres_engine, g, c) == {
        "row_version": 2, "public_appearance": "first", "public_background": None,
    }  # fmt: skip


def test_two_first_saves_one_creates_and_the_other_loses_the_unique_index_race(
    postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    with LockRace(postgres_engine) as race:
        creator = race.hold(do_save(g, c, g.o1_user_id, None, public_appearance="created"))
        loser = race.start("loser", do_save(g, c, g.o1_user_id, None, public_appearance="lost"))
        race.wait_blocked_by(creator, loser)
        creator.commit()
        race.join_all()
    assert isinstance(loser.error, StaleWriteError)
    assert draft_row(postgres_engine, g, c) == {
        "row_version": 1, "public_appearance": "created", "public_background": None,
    }  # fmt: skip


def test_a_release_in_flight_does_not_make_a_waiting_save_stale(
    postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    """The release holds the draft `FOR UPDATE` but never writes it, so a save made against the same
    version proceeds when the release commits and the release holds the earlier content."""
    c = prof.character_id
    seed(postgres_engine, g, c)
    with LockRace(postgres_engine) as race:
        releasing = race.hold(do_release(g, c, g.o1, 1))
        saving = race.start("save", do_save(g, c, g.o1_user_id, 1, public_appearance="after"))
        race.wait_blocked_by(releasing, saving)
        releasing.commit()
        race.join_all()
    assert saving.error is None and saving.result.row_version == 2
    assert [r["public_appearance"] for r in release_rows(postgres_engine, g, c)] == [APPEARANCE]


def test_a_save_that_commits_first_makes_the_release_of_the_old_version_stale(
    postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    seed(postgres_engine, g, c)
    with LockRace(postgres_engine) as race:
        saving = race.hold(do_save(g, c, g.o1_user_id, 1, public_appearance="newer"))
        releasing = race.start("release", do_release(g, c, g.o1, 1))
        race.wait_blocked_by(saving, releasing)
        saving.commit()
        race.join_all()
    assert isinstance(releasing.error, StaleWriteError)
    assert release_rows(postgres_engine, g, c) == []


# --- two releases of one draft version ---------------------------------------------------------------


def test_an_owner_and_a_delegated_gm_releasing_one_version_write_exactly_one_release(
    postgres_engine: Engine, g: Gate, m: Members, prof: Prof
) -> None:
    c = prof.character_id
    seed(postgres_engine, g, c)
    with LockRace(postgres_engine) as race:
        owner = race.hold(do_release(g, c, g.o1, 1))
        gm = race.start("gm", do_release(g, c, m.gm, 1))
        race.wait_blocked_by(owner, gm)
        owner.commit()
        race.join_all()
    assert gm.error is None and gm.result.created is False
    rows = release_rows(postgres_engine, g, c)
    assert len(rows) == 1 and rows[0]["authority_source_code"] == "owner"
    assert gm.result.version_number == 1 and gm.result.authority_source_code == "owner"


# --- the delegation and the gm role against a release, both orders -------------------------------------


def _revoke_delegation(g: Gate, m: Members) -> Callable[[Connection], Any]:
    return lambda c: revoke_character_reveal_delegation(
        c,
        campaign_id=g.campaign_id,
        actor_membership_id=g.o1,
        grantee_campaign_membership_id=m.gm,
        reason="Race revocation",
    )


def test_a_release_in_flight_finishes_before_the_delegation_is_revoked(
    postgres_engine: Engine, g: Gate, m: Members, prof: Prof
) -> None:
    c = prof.character_id
    seed(postgres_engine, g, c)
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="release", pattern=CLOCK)
        releasing = race.start("release", do_release(g, c, m.gm, 1))
        pause.wait_reached(releasing)
        revoking = race.start("revoke", _revoke_delegation(g, m))
        race.wait_blocked_by(pause, revoking)
        pause.release()
        race.join_all()
    assert releasing.error is None and releasing.result.authority_source_code == "delegation"
    assert revoking.error is None and revoking.result.revoked is True
    assert len(release_rows(postgres_engine, g, c)) == 1


def test_a_release_that_waited_for_a_delegation_revocation_is_refused_and_writes_nothing(
    postgres_engine: Engine, g: Gate, m: Members, prof: Prof
) -> None:
    c = prof.character_id
    seed(postgres_engine, g, c)
    before = counts(postgres_engine, g)
    with LockRace(postgres_engine) as race:
        revoking = race.hold(_revoke_delegation(g, m))
        releasing = race.start("release", do_release(g, c, m.gm, 1))
        race.wait_blocked_by(revoking, releasing)
        revoking.commit()
        race.join_all()
    assert isinstance(releasing.error, CharacterRevealRequiredError)
    assert counts(postgres_engine, g) == before
    assert release_rows(postgres_engine, g, c) == []


def _revoke_gm_role(g: Gate, m: Members) -> Callable[[Connection], Any]:
    return lambda connection: revoke_membership_role(
        connection, membership_role_id=m.gm_role, campaign_id=g.campaign_id
    )


def test_a_release_in_flight_finishes_before_the_gm_role_is_revoked(
    postgres_engine: Engine, g: Gate, m: Members, prof: Prof
) -> None:
    """The revocation queues on the gm assignment the release holds `FOR SHARE`."""
    c = prof.character_id
    seed(postgres_engine, g, c)
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="release", pattern=CLOCK)
        releasing = race.start("release", do_release(g, c, m.gm, 1))
        pause.wait_reached(releasing)
        revoking = race.start("revoke", _revoke_gm_role(g, m))
        race.wait_blocked_by(pause, revoking)
        pause.release()
        race.join_all()
    assert releasing.error is None and revoking.error is None
    assert len(release_rows(postgres_engine, g, c)) == 1


def test_a_release_that_waited_for_the_loss_of_the_gm_role_is_refused_and_writes_nothing(
    postgres_engine: Engine, g: Gate, m: Members, prof: Prof
) -> None:
    c = prof.character_id
    seed(postgres_engine, g, c)
    before = counts(postgres_engine, g)
    with LockRace(postgres_engine) as race:
        revoking = race.hold(_revoke_gm_role(g, m))
        releasing = race.start("release", do_release(g, c, m.gm, 1))
        race.wait_blocked_by(revoking, releasing)
        revoking.commit()
        race.join_all()
    assert isinstance(releasing.error, CharacterRevealRequiredError)
    assert counts(postgres_engine, g) == before
    assert release_rows(postgres_engine, g, c) == []


# --- ownership transfer ----------------------------------------------------------------------------------


def _relinquish_to(g: Gate, target: uuid.UUID) -> Callable[[Connection], Any]:
    return lambda c: transfer_campaign_ownership(
        c,
        campaign_id=g.campaign_id,
        actor_membership_id=g.o1,
        target_campaign_membership_id=target,
        relinquish_own_ownership=True,
    )


def test_a_relinquishing_transfer_by_the_releasing_owner_waits_for_the_release(
    postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    seed(postgres_engine, g, c)
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="release", pattern=CLOCK)
        releasing = race.start("release", do_release(g, c, g.o1, 1))
        pause.wait_reached(releasing)
        transfer = race.start("transfer", _relinquish_to(g, g.o2))
        race.wait_blocked_by(pause, transfer)
        pause.release()
        race.join_all()
    assert releasing.error is None and transfer.error is None
    rows = release_rows(postgres_engine, g, c)
    assert len(rows) == 1 and rows[0]["released_by_membership_id"] == g.o1
    # The release outlives the relinquished authority. The former owner can release nothing more,
    # not even retry the version they released: a retry needs current authority too.
    for expected in (1, 2):
        with LockRace(postgres_engine) as race:
            late = race.start("late", do_release(g, c, g.o1, expected))
            race.join_all()
        assert isinstance(late.error, CharacterRevealRequiredError)
    assert len(release_rows(postgres_engine, g, c)) == 1


def test_a_relinquishing_transfer_to_a_releasing_gm_waits_at_the_gms_membership(
    postgres_engine: Engine, g: Gate, m: Members, prof: Prof
) -> None:
    c = prof.character_id
    seed(postgres_engine, g, c)
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="release", pattern=CLOCK)
        releasing = race.start("release", do_release(g, c, m.gm, 1))
        pause.wait_reached(releasing)
        transfer = race.start("transfer", _relinquish_to(g, m.gm))
        race.wait_blocked_by(pause, transfer)
        pause.release()
        race.join_all()
    assert releasing.error is None and releasing.result.authority_source_code == "delegation"
    assert transfer.error is None


def test_a_release_that_waited_for_a_transfer_to_the_gm_is_refused_not_misattributed(
    postgres_engine: Engine, g: Gate, m: Members, prof: Prof
) -> None:
    """The GM read their delegation, then waited at their membership while an owner assignment was
    made. The source changed under the locks it was read with, so the release is refused (fail
    closed); a retry resolves the new source freshly."""
    c = prof.character_id
    seed(postgres_engine, g, c)
    before = counts(postgres_engine, g)
    with LockRace(postgres_engine) as race:
        transfer = race.hold(_relinquish_to(g, m.gm))
        releasing = race.start("release", do_release(g, c, m.gm, 1))
        race.wait_blocked_by(transfer, releasing)
        transfer.commit()
        race.join_all()
    assert isinstance(releasing.error, CharacterRevealRequiredError)
    nothing_written_beyond(postgres_engine, g, before)
    with LockRace(postgres_engine) as race:
        retry = race.start("retry", do_release(g, c, m.gm, 1))
        race.join_all()
    assert retry.error is None and retry.result.authority_source_code == "owner"


# --- expiry during a wait ---------------------------------------------------------------------------------


def test_an_owner_assignment_that_expires_during_the_release_wait_is_refused_with_nothing_written(
    postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    seed(postgres_engine, g, c)
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.membership_roles "
                "SET expires_at = clock_timestamp() + interval '4 seconds' "
                "WHERE membership_role_id = :r"
            ),
            {"r": g.o1_role},
        )
    before = counts(postgres_engine, g)
    with LockRace(postgres_engine) as race:
        saving = race.hold(do_save(g, c, g.o2_user_id, 1, public_appearance="holding"))
        releasing = race.start("release", do_release(g, c, g.o1, 1))
        race.wait_blocked_by(saving, releasing)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            with postgres_engine.connect() as connection:
                if connection.execute(
                    text(
                        "SELECT clock_timestamp() > expires_at FROM security.membership_roles "
                        "WHERE membership_role_id = :r"
                    ),
                    {"r": g.o1_role},
                ).scalar_one():
                    break
            time.sleep(0.2)
        saving.commit()
        race.join_all()
    assert isinstance(releasing.error, CharacterRevealRequiredError)
    drafts, releases, _audit, revisions = counts(postgres_engine, g)
    assert (drafts, releases, revisions) == (before[0], 0, before[3])


# --- the character ---------------------------------------------------------------------------------------


def _archive_character(character: uuid.UUID) -> Callable[[Connection], Any]:
    """No character archive command exists yet; this takes the lock the lifecycle commands take on
    an entity (`FOR UPDATE`) and writes the archived status, which is what an archive does."""

    def archive(connection: Connection) -> None:
        connection.execute(
            text("SELECT 1 FROM core.entities WHERE entity_id = :c FOR UPDATE"), {"c": character}
        ).all()
        connection.execute(
            text(
                "UPDATE core.entities SET lifecycle_status_id = "
                "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') "
                "WHERE entity_id = :c"
            ),
            {"c": character},
        )

    return archive


def test_archiving_the_character_and_a_release_serialize_in_both_orders(
    postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    first, second = prof.character_id, prof.other_character_id
    seed(postgres_engine, g, first)
    seed(postgres_engine, g, second)
    # The release first: the archive waits for the release's entity KEY SHARE; the release commits.
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="release", pattern=CLOCK)
        releasing = race.start("release", do_release(g, first, g.o1, 1))
        pause.wait_reached(releasing)
        archive = race.start("archive", _archive_character(first))
        race.wait_blocked_by(pause, archive)
        pause.release()
        race.join_all()
    assert releasing.error is None and archive.error is None
    assert len(release_rows(postgres_engine, g, first)) == 1
    # The archive first: the release waits at the entity, then reads the archived state and refuses.
    before = counts(postgres_engine, g)
    with LockRace(postgres_engine) as race:
        archiving_hold = race.hold(_archive_character(second))
        refused = race.start("release", do_release(g, second, g.o1, 1))
        race.wait_blocked_by(archiving_hold, refused)
        archiving_hold.commit()
        race.join_all()
    assert isinstance(refused.error, PublicProfileCharacterNotActiveError)
    nothing_written_beyond(postgres_engine, g, before)
    with postgres_engine.begin() as connection:  # leave the character active for teardown
        connection.execute(
            text(
                "UPDATE core.entities SET lifecycle_status_id = "
                "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active') "
                "WHERE entity_id = ANY(:c)"
            ),
            {"c": [first, second]},
        )


# --- a resource grant to the releaser naming the character ---------------------------------------------------


def _grant_to(g: Gate, grantee: uuid.UUID, character: uuid.UUID) -> Callable[[Connection], Any]:
    return lambda c: create_resource_grant(
        c,
        campaign_id=g.campaign_id,
        grantee_campaign_membership_id=grantee,
        grantee_access_group_id=None,
        capability_code="character.view_full",
        effect="allow",
        expected_world_id=g.world_id,
        granted_by_membership_id=g.o2,
        character_id=character,
    )


def test_a_grant_to_the_releaser_naming_the_character_and_a_release_do_not_deadlock(
    postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    """`create_resource_grant` locks the grantee's membership, then the campaign, then the target
    entity. The release takes membership, campaign, entity in that order too, so the pair serialize
    at the membership in both orders; with the entity before the membership they would deadlock."""
    first, second = prof.character_id, prof.other_character_id
    seed(postgres_engine, g, first)
    seed(postgres_engine, g, second)
    with LockRace(postgres_engine) as race:  # the release first
        pause = race.pause(thread_name="release", pattern=CLOCK)
        releasing = race.start("release", do_release(g, first, g.o1, 1))
        pause.wait_reached(releasing)
        grant = race.start("grant", _grant_to(g, g.o1, first))
        race.wait_blocked_by(pause, grant)
        pause.release()
        race.join_all()
    assert releasing.error is None and grant.error is None
    with LockRace(postgres_engine) as race:  # the grant first
        granting = race.hold(_grant_to(g, g.o1, second))
        releasing = race.start("release", do_release(g, second, g.o1, 1))
        race.wait_blocked_by(granting, releasing)
        granting.commit()
        race.join_all()
    assert releasing.error is None
    assert len(release_rows(postgres_engine, g, first)) == 1
    assert len(release_rows(postgres_engine, g, second)) == 1


# --- adding the releaser or the author to an access group that carries a whole-character deny -----------------


def _group_with_a_whole_character_deny(
    engine: Engine, g: Gate, character: uuid.UUID, name: str
) -> uuid.UUID:
    with engine.begin() as connection:
        group = create_access_group(
            connection, campaign_id=g.campaign_id, name=name, description=None
        ).access_group_id
        create_resource_grant(
            connection,
            campaign_id=g.campaign_id,
            grantee_campaign_membership_id=None,
            grantee_access_group_id=group,
            capability_code="campaign.view",
            effect="deny",
            expected_world_id=g.world_id,
            granted_by_membership_id=g.o2,
            entity_id=character,
        )
    return group


def _add_to_group(g: Gate, group: uuid.UUID, member: uuid.UUID) -> Callable[[Connection], Any]:
    return lambda c: add_access_group_members(
        c,
        access_group_id=group,
        campaign_membership_ids=(member,),
        campaign_id=g.campaign_id,
        added_by_membership_id=g.o2,
    )


def test_adding_the_releaser_to_a_denying_group_and_the_release_serialize_in_both_orders(
    postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    """The release holds the releaser's membership `FOR SHARE`, which conflicts with the add's
    `FOR NO KEY UPDATE` (P1): the first to reach the membership goes first, neither deadlocks, and an
    add that commits first puts its group deny in the release's fresh re-resolve."""
    first, second = prof.character_id, prof.other_character_id
    seed(postgres_engine, g, first)
    seed(postgres_engine, g, second)
    group_one = _group_with_a_whole_character_deny(postgres_engine, g, first, "Denies One")
    group_two = _group_with_a_whole_character_deny(postgres_engine, g, second, "Denies Two")

    # Release first: paused after its membership lock, before its campaign lock.
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="release", pattern=RELEASE_CAMPAIGN)
        releasing = race.start("release", do_release(g, first, g.o1, 1))
        pause.wait_reached(releasing)
        adding = race.start("add", _add_to_group(g, group_one, g.o1))
        race.wait_blocked_by(pause, adding)
        pause.release()
        race.join_all()
    assert releasing.error is None and adding.error is None
    assert len(release_rows(postgres_engine, g, first)) == 1

    # Add first: paused after its membership locks. The release waits at the membership, then
    # re-resolves with the group deny in force: 404, no release row, no audit row.
    before = counts(postgres_engine, g)
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="add", pattern=ADD_SECOND_LOCK)
        adding = race.start("add", _add_to_group(g, group_two, g.o1))
        pause.wait_reached(adding)
        releasing = race.start("release", do_release(g, second, g.o1, 1))
        race.wait_blocked_by(pause, releasing)
        pause.release()
        race.join_all()
    assert adding.error is None
    assert isinstance(releasing.error, PublicProfileNotFoundError)
    assert release_rows(postgres_engine, g, second) == []
    nothing_written_beyond(postgres_engine, g, before)


def test_adding_the_author_to_a_denying_group_and_a_save_serialize_in_both_orders(
    postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    first, second = prof.character_id, prof.other_character_id
    seed(postgres_engine, g, first)
    seed(postgres_engine, g, second)
    group_one = _group_with_a_whole_character_deny(postgres_engine, g, first, "Save Denies One")
    group_two = _group_with_a_whole_character_deny(postgres_engine, g, second, "Save Denies Two")

    # The save first, paused before its campaign lock: the add queues at the membership.
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="save", pattern=SAVE_CAMPAIGN)
        saving = race.start("save", do_save(g, first, g.o1_user_id, 1, public_appearance="kept"))
        pause.wait_reached(saving)
        adding = race.start("add", _add_to_group(g, group_one, g.o1))
        race.wait_blocked_by(pause, adding)
        pause.release()
        race.join_all()
    assert saving.error is None and adding.error is None
    assert draft_row(postgres_engine, g, first)["public_appearance"] == "kept"  # type: ignore[index]

    # The add first: the save waits at the membership, then sees the deny: 404, nothing written.
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="add", pattern=ADD_SECOND_LOCK)
        adding = race.start("add", _add_to_group(g, group_two, g.o1))
        pause.wait_reached(adding)
        saving = race.start("save", do_save(g, second, g.o1_user_id, 1, public_appearance="lost"))
        race.wait_blocked_by(pause, saving)
        pause.release()
        race.join_all()
    assert adding.error is None
    assert isinstance(saving.error, PublicProfileNotFoundError)
    assert draft_row(postgres_engine, g, second)["public_appearance"] == APPEARANCE  # type: ignore[index]


# --- losing the role the save needs -------------------------------------------------------------------------


def test_a_save_that_waited_for_the_loss_of_canon_edit_is_refused_and_writes_nothing(
    postgres_engine: Engine, g: Gate, m: Members, prof: Prof
) -> None:
    c = prof.character_id
    seed(postgres_engine, g, c)
    with postgres_engine.connect() as connection:
        ast_role = connection.execute(
            text(
                "SELECT membership_role_id FROM security.membership_roles "
                "WHERE campaign_membership_id = :m AND revoked_at IS NULL"
            ),
            {"m": m.ast},
        ).scalar_one()
    before = counts(postgres_engine, g)
    with LockRace(postgres_engine) as race:
        revoking = race.hold(
            lambda conn: revoke_membership_role(
                conn, membership_role_id=ast_role, campaign_id=g.campaign_id
            )
        )
        saving = race.start("save", do_save(g, c, m.ast_user_id, 1, public_appearance="denied"))
        race.wait_blocked_by(revoking, saving)
        revoking.commit()
        race.join_all()
    assert isinstance(saving.error, CampaignNotAuthorizedError)
    assert counts(postgres_engine, g) == before


# --- creating the deny itself, against a save and a release (A2a-R, DEF-018) -------------------------------------
#
# The deny is created with the application's own command (`create_resource_grant`, or the HTTP route
# when the audit row is part of what is checked), no longer a raw INSERT. The grant locks the grantee's
# membership `FOR UPDATE` (or the group), the campaign `FOR UPDATE`, the account and the character's
# entity `FOR UPDATE`, in that order. A membership grantee serializes with the save and the release at
# the membership (`FOR SHARE` from `lock_authoring_scope` and from the release); a group grantee at the
# campaign row (their `KEY SHARE`). Neither order forms a cycle, and the command that waited re-resolves
# its access afterwards, so it sees a deny that committed during the wait.


def _deny(
    g: Gate,
    capability: str,
    character: uuid.UUID,
    *,
    member: uuid.UUID | None = None,
    group: uuid.UUID | None = None,
) -> Callable[[Connection], Any]:
    return lambda c: create_resource_grant(
        c,
        campaign_id=g.campaign_id,
        grantee_campaign_membership_id=member,
        grantee_access_group_id=group,
        capability_code=capability,
        effect="deny",
        expected_world_id=g.world_id,
        granted_by_membership_id=g.o2,
        entity_id=character,
    )


def _http_deny(
    client_factory: Callable[[uuid.UUID], Any],
    g: Gate,
    capability: str,
    character: uuid.UUID,
    *,
    member: uuid.UUID | None = None,
    group: uuid.UUID | None = None,
) -> Callable[[Connection], Any]:
    def run(_connection: Connection) -> Any:
        request: dict[str, object] = {
            "capability_code": capability,
            "effect": "deny",
            "entity_id": str(character),
        }
        if member is not None:
            request["grantee_campaign_membership_id"] = str(member)
        if group is not None:
            request["grantee_access_group_id"] = str(group)
        with client_factory(g.o2_user_id) as client:
            return client.post(f"/campaigns/{g.campaign_id}/resource-grants", json=request)

    return run


def _group_holding_the_owner(engine: Engine, g: Gate, name: str) -> uuid.UUID:
    with engine.begin() as connection:
        group = create_access_group(
            connection, campaign_id=g.campaign_id, name=name, description=None
        ).access_group_id
        add_access_group_members(
            connection,
            access_group_id=group,
            campaign_membership_ids=(g.o1,),
            campaign_id=g.campaign_id,
            added_by_membership_id=g.o2,
        )
    return group


def _grantee(engine: Engine, g: Gate, kind: str, name: str) -> dict[str, uuid.UUID]:
    if kind == "member":
        return {"member": g.o1}
    return {"group": _group_holding_the_owner(engine, g, name)}


def _grant_audit_count(engine: Engine, g: Gate) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM audit.change_log "
                    "WHERE world_id = :w AND command_name = 'create_resource_grant'"
                ),
                {"w": g.world_id},
            ).scalar_one()
        )


def _live_denies(engine: Engine, g: Gate, capability: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("""
                    SELECT count(*) FROM security.resource_grants rg
                    JOIN security.capabilities c ON c.capability_id = rg.capability_id
                    WHERE rg.campaign_id = :c AND rg.effect = 'deny' AND rg.revoked_at IS NULL
                      AND c.code = :cap
                """),
                {"c": g.campaign_id, "cap": capability},
            ).scalar_one()
        )


@pytest.mark.parametrize("grantee_kind", ["member", "group"])
@pytest.mark.parametrize("operation", ["release", "save"])
def test_a_whole_character_deny_created_while_the_command_runs_waits_and_both_commit(
    client_factory: Callable[[uuid.UUID], Any],
    postgres_engine: Engine,
    g: Gate,
    prof: Prof,
    operation: str,
    grantee_kind: str,
) -> None:
    """Command first: the deny's creation waits for the command and then commits, so the command
    succeeded under the access it began with and the next one is refused."""
    c = prof.character_id
    seed(postgres_engine, g, c)
    grantee = _grantee(postgres_engine, g, grantee_kind, f"First {operation}")
    with LockRace(postgres_engine) as race:
        if operation == "release":
            pause = race.pause(thread_name="command", pattern=CLOCK)
            command = race.start("command", do_release(g, c, g.o1, 1))
        else:
            pause = race.pause(thread_name="command", pattern=SAVE_UPDATE)
            command = race.start(
                "command", do_save(g, c, g.o1_user_id, 1, public_appearance="saved first")
            )
        pause.wait_reached(command)
        denial = race.start("denial", _http_deny(client_factory, g, "campaign.view", c, **grantee))
        race.wait_blocked_by(pause, denial)
        pause.release()
        race.join_all()
    assert command.error is None, command.error
    assert denial.error is None and denial.result.status_code == 201, denial.result.text
    assert _live_denies(postgres_engine, g, "campaign.view") == 1
    assert _grant_audit_count(postgres_engine, g) == 1
    if operation == "release":
        assert len(release_rows(postgres_engine, g, c)) == 1
    else:
        assert draft_row(postgres_engine, g, c)["public_appearance"] == "saved first"  # type: ignore[index]
    # The deny now applies to the next command, resolved fresh.
    before = counts(postgres_engine, g)
    with LockRace(postgres_engine) as race:
        again = race.start(
            "again",
            do_release(g, c, g.o1, 2)
            if operation == "release"
            else do_save(g, c, g.o1_user_id, 2, public_appearance="x"),
        )
        race.join_all()
    assert isinstance(again.error, PublicProfileNotFoundError)
    nothing_written_beyond(postgres_engine, g, before)


@pytest.mark.parametrize("grantee_kind", ["member", "group"])
@pytest.mark.parametrize("operation", ["release", "save"])
def test_a_command_that_waited_for_a_whole_character_deny_is_refused_with_nothing_written(
    postgres_engine: Engine,
    g: Gate,
    prof: Prof,
    operation: str,
    grantee_kind: str,
) -> None:
    """Deny first (created and held uncommitted): the command queues behind it, then resolves its
    access afresh after the wait and finds the character removed: 404, nothing written."""
    c = prof.character_id
    seed(postgres_engine, g, c)
    grantee = _grantee(postgres_engine, g, grantee_kind, f"Held {operation}")
    before = counts(postgres_engine, g)
    with LockRace(postgres_engine) as race:
        holding = race.hold(_deny(g, "campaign.view", c, **grantee))
        command = race.start(
            "command",
            do_release(g, c, g.o1, 1)
            if operation == "release"
            else do_save(g, c, g.o1_user_id, 1, public_appearance="never"),
        )
        race.wait_blocked_by(holding, command)
        holding.commit()
        race.join_all()
    assert isinstance(command.error, PublicProfileNotFoundError)
    nothing_written_beyond(postgres_engine, g, before)
    assert draft_row(postgres_engine, g, c)["public_appearance"] == APPEARANCE  # type: ignore[index]
    assert _live_denies(postgres_engine, g, "campaign.view") == 1


def test_a_canon_edit_deny_created_around_a_save_applies_to_the_next_save_only(
    client_factory: Callable[[uuid.UUID], Any],
    postgres_engine: Engine,
    g: Gate,
    prof: Prof,
) -> None:
    c = prof.character_id
    seed(postgres_engine, g, c)
    # Save first: the deny waits, the save commits, the deny then commits.
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="save", pattern=SAVE_UPDATE)
        saving = race.start("save", do_save(g, c, g.o1_user_id, 1, public_appearance="two"))
        pause.wait_reached(saving)
        denial = race.start("denial", _http_deny(client_factory, g, "canon.edit", c, member=g.o1))
        race.wait_blocked_by(pause, denial)
        pause.release()
        race.join_all()
    assert saving.error is None and saving.result.row_version == 2
    assert denial.error is None and denial.result.status_code == 201
    assert _grant_audit_count(postgres_engine, g) == 1
    with LockRace(postgres_engine) as race:
        later = race.start("later", do_save(g, c, g.o1_user_id, 2, public_appearance="three"))
        race.join_all()
    assert isinstance(later.error, PublicProfileEditDeniedError)
    assert draft_row(postgres_engine, g, c)["public_appearance"] == "two"  # type: ignore[index]


def test_a_save_that_waited_for_a_canon_edit_deny_is_refused_and_a_release_still_succeeds(
    postgres_engine: Engine,
    g: Gate,
    prof: Prof,
) -> None:
    c = prof.character_id
    seed(postgres_engine, g, c)
    before = counts(postgres_engine, g)
    with LockRace(postgres_engine) as race:
        holding = race.hold(_deny(g, "canon.edit", c, member=g.o1))
        saving = race.start("save", do_save(g, c, g.o1_user_id, 1, public_appearance="never"))
        race.wait_blocked_by(holding, saving)
        holding.commit()
        race.join_all()
    assert isinstance(saving.error, PublicProfileEditDeniedError)
    nothing_written_beyond(postgres_engine, g, before)
    with LockRace(postgres_engine) as race:
        releasing = race.start("release", do_release(g, c, g.o1, 1))
        race.join_all()
    assert releasing.error is None and releasing.result.created is True
