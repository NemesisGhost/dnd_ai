# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""Lock-order races for the legacy copy (P03-A A2b-2, plan sections 9.6 and 9.8).

Every competitor is the real command: `update_npc`, `save_character_public_profile_draft`,
`release_character_public_profile`, `end_world_membership` and `set_world_role`. The copy takes the
world row `FOR SHARE`, the caller's role rows, the campaign `KEY SHARE`, the character's entity `FOR
SHARE`, reads the entity's `row_version` and then the description, and finally locks the draft `FOR
UPDATE`. Each wait is observed through `pg_blocking_pids` as blocked by the intended session
(`LockRace.wait_blocked_by`); a command that finished before it blocked is reported as it ended; and
the pauses, holds and workers are cleaned up before teardown. Both winners are run for each pair.

The commands write no audit row (the route does), so "audit state" here is that no command wrote
one; the audit rows of a successful route copy are asserted in the HTTP tests.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.character_public_profile import (
    copy_legacy_text_to_public_profile_draft,
)
from dnd_ai.commands.world_memberships import end_world_membership, set_world_role
from dnd_ai.domain.authoring import StaleWriteError, WorldAuthorityRequiredError
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_character_public_profile_api import (  # noqa: F401 - fixtures by name
    release_rows,
)
from tests.database.test_character_public_profile_concurrency import (
    CLOCK,
    SAVE_UPDATE,
    do_release,
    do_save,
)
from tests.database.test_character_public_profile_copy import (  # noqa: F401 - fixtures
    FULL,
    NEW_SOURCE,
    SRC_APPEARANCE,
    audit_dump,
    copy,
    entity_version,
    source_npc,
    update_source,
)
from tests.database.test_character_public_profile_restrictions import (  # noqa: F401 - fixtures
    npc,
    row,
)
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.lock_race_support import LockRace
from tests.r01_support import fixture_plan

pytestmark = pytest.mark.database

ENTITY_VERSION_READ = r"SELECT row_version FROM core\.entities WHERE entity_id"
COPY_UPDATE = r"UPDATE campaign\.character_public_profiles SET"


def do_copy(
    g: Gate, character: uuid.UUID, user: uuid.UUID, expected: int | None, field: str = "background"
) -> Callable[[Connection], Any]:
    return lambda c: copy_legacy_text_to_public_profile_draft(
        c,
        campaign_id=g.campaign_id,
        character_id=character,
        actor_user_id=user,
        expected_row_version=expected,
        source_field=field,
        plan=fixture_plan(c, g.campaign_id),
    )


def _world_roles(engine: Engine, g: Gate, user: uuid.UUID) -> list[str]:
    with engine.connect() as connection:
        return [
            str(r[0])
            for r in connection.execute(
                text(
                    "SELECT r.code FROM security.world_memberships w "
                    "JOIN security.world_roles r ON r.world_role_id = w.world_role_id "
                    "WHERE w.world_id = :w AND w.user_id = :u AND w.ended_at IS NULL"
                ),
                {"w": g.world_id, "u": user},
            )
        ]


def _audit_rows(engine: Engine, g: Gate) -> int:
    return audit_dump(engine, g).count("copy_legacy_text_to_public_profile_draft")


# --- a copy against update_npc on the same character ----------------------------------------------------------


def test_an_update_that_commits_first_is_copied_whole_text_and_version_together(
    postgres_engine: Engine, g: Gate, m: Members, source_npc: uuid.UUID
) -> None:
    c = source_npc
    before_version = entity_version(postgres_engine, c)
    with LockRace(postgres_engine) as race:
        updating = race.hold(update_source(g, c, m.gm_user_id, background=NEW_SOURCE))
        copying = race.start("copy", do_copy(g, c, m.gm_user_id, None))
        race.wait_blocked_by(updating, copying)  # at the entity row the update holds FOR UPDATE
        updating.commit()
        race.join_all()
    assert copying.error is None and copying.result.row_version == 1
    after = row(postgres_engine, g, c)
    assert after["public_background"] == NEW_SOURCE  # the committed text...
    assert (
        after["background_source"] == entity_version(postgres_engine, c) > before_version
    )  # ...and its version
    assert after["background_watermark"] == 1
    assert _audit_rows(postgres_engine, g) == 0


def test_a_copy_that_holds_the_entity_first_records_the_old_text_with_the_old_version(
    postgres_engine: Engine, g: Gate, m: Members, source_npc: uuid.UUID
) -> None:
    c = source_npc
    before_version = entity_version(postgres_engine, c)
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="copy", pattern=ENTITY_VERSION_READ)
        copying = race.start("copy", do_copy(g, c, m.gm_user_id, None))
        pause.wait_reached(copying)  # holds the entity FOR SHARE, has read nothing yet
        updating = race.start("update", update_source(g, c, m.gm_user_id, background=NEW_SOURCE))
        race.wait_blocked_by(pause, updating)
        pause.release()
        race.join_all()
    assert copying.error is None and updating.error is None
    first = row(postgres_engine, g, c)
    assert first["public_background"] == FULL  # never a mix with the newer version
    assert first["background_source"] == before_version
    # A later copy reads the new pair.
    with postgres_engine.begin() as connection:
        again = do_copy(g, c, m.gm_user_id, 1)(connection)
    assert again.row_version == 2
    second = row(postgres_engine, g, c)
    assert second["public_background"] == NEW_SOURCE
    assert second["background_source"] == entity_version(postgres_engine, c) > before_version
    assert second["background_watermark"] == 2


# --- a copy against a save and against a release on the same draft --------------------------------------------


def _drafted(engine: Engine, g: Gate, m: Members, c: uuid.UUID) -> None:
    """A copied background at draft version 1."""
    with engine.begin() as connection:
        do_copy(g, c, m.gm_user_id, None)(connection)


def test_a_save_holding_the_draft_makes_a_copy_with_the_same_token_stale(
    postgres_engine: Engine, g: Gate, m: Members, source_npc: uuid.UUID
) -> None:
    c = source_npc
    _drafted(postgres_engine, g, m, c)
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="save", pattern=SAVE_UPDATE)
        saving = race.start("save", do_save(g, c, m.gm_user_id, 1, public_appearance="saved A"))
        pause.wait_reached(saving)  # holds the draft FOR UPDATE
        copying = race.start("copy", do_copy(g, c, m.gm_user_id, 1, "appearance"))
        race.wait_blocked_by(pause, copying)
        pause.release()
        race.join_all()
    assert saving.error is None and isinstance(copying.error, StaleWriteError)
    after = row(postgres_engine, g, c)
    assert after["public_appearance"] == "saved A" and after["appearance_origin"] == "authored"
    assert after["appearance_source"] is None and after["appearance_watermark"] is None
    assert after["row_version"] == 2 and _audit_rows(postgres_engine, g) == 0


def test_a_copy_holding_the_draft_makes_a_save_with_the_same_token_stale(
    postgres_engine: Engine, g: Gate, m: Members, source_npc: uuid.UUID
) -> None:
    c = source_npc
    _drafted(postgres_engine, g, m, c)
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="copy", pattern=COPY_UPDATE)
        copying = race.start("copy", do_copy(g, c, m.gm_user_id, 1, "appearance"))
        pause.wait_reached(copying)  # holds the draft FOR UPDATE
        saving = race.start("save", do_save(g, c, m.gm_user_id, 1, public_appearance="saved A"))
        race.wait_blocked_by(pause, saving)
        pause.release()
        race.join_all()
    assert copying.error is None and isinstance(saving.error, StaleWriteError)
    after = row(postgres_engine, g, c)
    assert after["public_appearance"] == SRC_APPEARANCE
    assert after["appearance_origin"] == "legacy_appearance" and after["appearance_watermark"] == 2
    assert after["row_version"] == 2 and _audit_rows(postgres_engine, g) == 0


def test_a_release_holding_the_draft_covers_the_earlier_text_and_the_copy_restricts_the_new(
    postgres_engine: Engine, g: Gate, m: Members, source_npc: uuid.UUID
) -> None:
    c = source_npc
    _drafted(postgres_engine, g, m, c)
    with postgres_engine.begin() as connection:  # a later source edit the copy will pick up
        update_source(g, c, m.gm_user_id, background=NEW_SOURCE)(connection)
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="release", pattern=CLOCK)
        releasing = race.start("release", do_release(g, c, g.o2, 1))
        pause.wait_reached(releasing)  # holds the draft FOR UPDATE
        copying = race.start("copy", do_copy(g, c, m.gm_user_id, 1))
        race.wait_blocked_by(pause, copying)
        pause.release()
        race.join_all()
    assert releasing.error is None and releasing.result.created is True
    assert copying.error is None and copying.result.row_version == 2
    assert [r["public_background"] for r in release_rows(postgres_engine, g, c)] == [FULL]
    after = row(postgres_engine, g, c)
    assert after["public_background"] == NEW_SOURCE
    assert after["background_watermark"] == 2 > releasing.result.from_draft_row_version


def test_a_copy_holding_the_draft_makes_a_release_of_the_earlier_version_stale(
    postgres_engine: Engine, g: Gate, m: Members, source_npc: uuid.UUID
) -> None:
    c = source_npc
    _drafted(postgres_engine, g, m, c)
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="copy", pattern=COPY_UPDATE)
        copying = race.start("copy", do_copy(g, c, m.gm_user_id, 1, "background"))
        pause.wait_reached(copying)
        releasing = race.start("release", do_release(g, c, g.o2, 1))
        race.wait_blocked_by(pause, releasing)
        pause.release()
        race.join_all()
    assert copying.error is None and copying.result.row_version == 2
    assert isinstance(releasing.error, StaleWriteError)  # it never saw the new copy
    assert release_rows(postgres_engine, g, c) == []
    assert row(postgres_engine, g, c)["background_watermark"] == 2


# --- the copier's world role against a copy, both winners and both kinds of change ---------------------------------


def _end(g: Gate, user: uuid.UUID) -> Callable[[Connection], Any]:
    return lambda c: end_world_membership(c, world_id=g.world_id, user_id=user)


def _downgrade(g: Gate, user: uuid.UUID) -> Callable[[Connection], Any]:
    return lambda c: set_world_role(c, world_id=g.world_id, user_id=user, role_code="world_reader")


@pytest.mark.parametrize("change", [_end, _downgrade], ids=["end", "downgrade"])
def test_a_role_change_that_commits_first_refuses_the_copy_and_writes_nothing(
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    source_npc: uuid.UUID,
    change: Callable[[Gate, uuid.UUID], Callable[[Connection], Any]],
) -> None:
    c = source_npc
    with LockRace(postgres_engine) as race:
        changing = race.hold(change(g, m.gm_user_id))
        copying = race.start("copy", do_copy(g, c, m.gm_user_id, None))
        race.wait_blocked_by(changing, copying)  # at the world row, before any capability is judged
        changing.commit()
        race.join_all()
    assert isinstance(copying.error, WorldAuthorityRequiredError)  # judged afresh after the wait
    assert "world_editor" not in _world_roles(postgres_engine, g, m.gm_user_id)
    with postgres_engine.connect() as connection:
        drafts = connection.execute(
            text("SELECT count(*) FROM campaign.character_public_profiles")
        ).scalar_one()
    assert drafts == 0 and _audit_rows(postgres_engine, g) == 0


@pytest.mark.parametrize("change", [_end, _downgrade], ids=["end", "downgrade"])
def test_a_copy_in_flight_commits_before_a_role_change_that_waits_for_the_world_row(
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    source_npc: uuid.UUID,
    change: Callable[[Gate, uuid.UUID], Callable[[Connection], Any]],
) -> None:
    c = source_npc
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="copy", pattern=ENTITY_VERSION_READ)
        copying = race.start("copy", do_copy(g, c, m.gm_user_id, None))
        pause.wait_reached(copying)  # holds the world FOR SHARE and has judged the capability
        changing = race.start("change", change(g, m.gm_user_id))
        race.wait_blocked_by(pause, changing)
        pause.release()
        race.join_all()
    assert copying.error is None and changing.error is None
    after = row(postgres_engine, g, c)
    assert after["public_background"] == FULL and after["background_watermark"] == 1
    assert "world_editor" not in _world_roles(postgres_engine, g, m.gm_user_id)
    # The next copy by the same caller is refused: the committed copy stands, new ones do not.
    with postgres_engine.begin() as connection, pytest.raises(WorldAuthorityRequiredError):
        do_copy(g, c, m.gm_user_id, 1)(connection)
