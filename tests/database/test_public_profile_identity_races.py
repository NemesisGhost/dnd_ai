# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""Publication under concurrent definition edits (P03-A A4a, plan section 12.7).

Every competitor is a real command: `release_character_public_profile` against `update_npc` and
`update_player_character` (the two callers of `update_character_identity`, the only writer of
`species_id` and `size_category`), plus `save_character_public_profile_draft` and a second release.
The release holds the character's `core.entities` row `FOR KEY SHARE`; the edit takes it `FOR
UPDATE`. Each wait is observed through `pg_blocking_pids` as blocked by the intended session, both
orders are run, and no scenario deadlocks.

The release is called as the command, as the existing release races are: the route adds no lock, and
its checks (token, tier, receipt, audit) are covered over HTTP in test_public_profile_identity_api.py.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.character_public_profile import (
    release_character_public_profile,
    save_character_public_profile_draft,
)
from dnd_ai.commands.npcs import update_npc
from dnd_ai.commands.player_characters import update_player_character
from dnd_ai.domain.authoring import StaleWriteError
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_character_public_profile_concurrency import CLOCK, SAVE_UPDATE, do_save
from tests.database.test_character_public_profile_copy import (  # noqa: F401 - fixtures
    entity_version,
    pc,
)
from tests.database.test_character_public_profile_restrictions import npc  # noqa: F401 - fixture
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.lock_race_support import LockRace

pytestmark = pytest.mark.database

KINDS = ["npc", "player_character"]


@pytest.fixture
def subject(request: pytest.FixtureRequest, kind: str) -> uuid.UUID:
    return request.getfixturevalue("npc" if kind == "npc" else "pc")  # type: ignore[no-any-return]


@pytest.fixture(params=KINDS)
def kind(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def seed_flagged_draft(engine: Engine, g: Gate, character: uuid.UUID) -> int:
    with engine.begin() as connection:
        return save_character_public_profile_draft(
            connection,
            campaign_id=g.campaign_id,
            character_id=character,
            actor_user_id=g.o1_user_id,
            expected_row_version=None,
            fields={"public_appearance": "Tall"},
            identity_flags={"publish_species": True, "publish_size": True},
        ).row_version


def do_identity_release(
    g: Gate,
    character: uuid.UUID,
    membership: uuid.UUID,
    version: int,
    character_version: int | None,
) -> Callable[[Connection], Any]:
    return lambda c: release_character_public_profile(
        c,
        campaign_id=g.campaign_id,
        character_id=character,
        actor_membership_id=membership,
        expected_draft_row_version=version,
        release_note=None,
        expected_character_row_version=character_version,
    )


def edit_identity(
    g: Gate, kind: str, character: uuid.UUID, user: uuid.UUID, *, size: str = "large"
) -> Callable[[Connection], Any]:
    """The real `update_npc` / `update_player_character` with the character's current values and a
    new size."""

    def run(connection: Connection) -> Any:
        cur = connection.execute(
            text("""
                SELECT e.canonical_name, e.summary, e.row_version, c.species_id,
                       c.origin_location_id, d.background, d.appearance, d.notes
                FROM core.entities e
                JOIN character.characters c ON c.character_id = e.entity_id
                LEFT JOIN character.character_descriptions d ON d.character_id = e.entity_id
                WHERE e.entity_id = :c
            """),
            {"c": character},
        ).one()
        common: dict[str, Any] = {
            "campaign_id": g.campaign_id,
            "actor_user_id": user,
            "expected_row_version": int(cur.row_version),
            "name": cur.canonical_name,
            "summary": cur.summary,
            "species_id": cur.species_id,
            "size_category": size,
            "origin_location_id": cur.origin_location_id,
            "background": cur.background,
            "appearance": cur.appearance,
            "notes": cur.notes,
        }
        if kind == "npc":
            return update_npc(connection, npc_id=character, **common)
        return update_player_character(connection, player_character_id=character, **common)

    return run


def released(engine: Engine, g: Gate, character: uuid.UUID) -> list[Any]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT version_number, released_size_category, identity_entity_row_version "
                    "FROM campaign.character_public_profile_releases "
                    "WHERE campaign_id = :c AND character_id = :ch ORDER BY version_number"
                ),
                {"c": g.campaign_id, "ch": character},
            )
        )


def live_size(engine: Engine, character: uuid.UUID) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text("SELECT size_category FROM character.characters WHERE character_id = :c"),
                {"c": character},
            ).scalar_one()
        )


def test_an_identity_edit_that_commits_first_makes_the_old_token_stale_and_writes_no_release(
    postgres_engine: Engine, g: Gate, m: Members, kind: str, subject: uuid.UUID
) -> None:
    c = subject
    version = seed_flagged_draft(postgres_engine, g, c)
    token = entity_version(postgres_engine, c)
    with LockRace(postgres_engine) as race:
        updating = race.hold(edit_identity(g, kind, c, m.gm_user_id))
        releasing = race.start("release", do_identity_release(g, c, g.o1, version, token))
        race.wait_blocked_by(updating, releasing)  # at the entity row the edit holds FOR UPDATE
        updating.commit()
        race.join_all()
    assert isinstance(releasing.error, StaleWriteError), releasing.describe()
    assert released(postgres_engine, g, c) == []
    assert entity_version(postgres_engine, c) > token
    assert live_size(postgres_engine, c) == "large"


def test_a_release_that_holds_the_entity_first_snapshots_the_old_values_and_the_edit_waits(
    postgres_engine: Engine, g: Gate, m: Members, kind: str, subject: uuid.UUID
) -> None:
    c = subject
    version = seed_flagged_draft(postgres_engine, g, c)
    token = entity_version(postgres_engine, c)
    old_size = live_size(postgres_engine, c)
    assert old_size != "large"
    with LockRace(postgres_engine) as race:
        # Paused after its last lock wait (the draft row), holding the entity row FOR KEY SHARE.
        pause = race.pause(thread_name="release", pattern=CLOCK)
        releasing = race.start("release", do_identity_release(g, c, g.o1, version, token))
        pause.wait_reached(releasing)
        updating = race.start("update", edit_identity(g, kind, c, m.gm_user_id))
        race.wait_blocked_by(pause, updating)  # the edit waits for the release
        pause.release()
        race.join_all()
    assert releasing.error is None and updating.error is None, (
        releasing.describe(),
        updating.describe(),
    )
    [row] = released(postgres_engine, g, c)
    assert row.released_size_category == old_size  # the old value, with the old version
    assert row.identity_entity_row_version == token
    assert live_size(postgres_engine, c) == "large"  # the edit committed after
    assert entity_version(postgres_engine, c) > token


def test_two_flagged_releases_of_one_draft_and_character_version_make_one_release(
    postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:
    c = npc
    version = seed_flagged_draft(postgres_engine, g, c)
    token = entity_version(postgres_engine, c)
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="first", pattern=CLOCK)
        first = race.start("first", do_identity_release(g, c, g.o1, version, token))
        pause.wait_reached(first)
        second = race.start("second", do_identity_release(g, c, g.o2, version, token))
        race.wait_blocked_by(pause, second)  # on the draft row the first holds FOR UPDATE
        pause.release()
        race.join_all()
    assert first.error is None and second.error is None, (first.describe(), second.describe())
    assert first.result.created is True
    assert second.result.created is False  # the same release, never a second snapshot
    assert second.result.character_public_profile_release_id == (
        first.result.character_public_profile_release_id
    )
    assert second.result.identity_entity_row_version == token
    assert len(released(postgres_engine, g, c)) == 1


def test_a_flag_toggle_that_commits_first_makes_a_release_of_the_previous_draft_version_stale(
    postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:
    c = npc
    version = seed_flagged_draft(postgres_engine, g, c)
    token = entity_version(postgres_engine, c)
    toggling = lambda conn: save_character_public_profile_draft(  # noqa: E731
        conn,
        campaign_id=g.campaign_id,
        character_id=c,
        actor_user_id=g.o1_user_id,
        expected_row_version=version,
        fields={},
        identity_flags={"publish_size": False},
    )
    with LockRace(postgres_engine) as race:
        saving = race.hold(toggling)
        releasing = race.start("release", do_identity_release(g, c, g.o1, version, token))
        race.wait_blocked_by(saving, releasing)  # at the draft row the save holds FOR UPDATE
        saving.commit()
        race.join_all()
    assert isinstance(releasing.error, StaleWriteError), releasing.describe()
    assert released(postgres_engine, g, c) == []


def test_a_draft_save_and_an_identity_edit_never_wait_on_each_other(
    postgres_engine: Engine, g: Gate, m: Members, npc: uuid.UUID
) -> None:
    """A save takes the entity `FOR SHARE`, the edit `FOR UPDATE`: they order at that row, and a
    pending release does not change it (no new lock, no new order)."""
    c = npc
    version = seed_flagged_draft(postgres_engine, g, c)
    with LockRace(postgres_engine) as race:
        pause = race.pause(thread_name="save", pattern=SAVE_UPDATE)
        saving = race.start("save", do_save(g, c, g.o1_user_id, version, public_summary="s"))
        pause.wait_reached(saving)  # holds the entity FOR SHARE and the draft FOR UPDATE
        updating = race.start("update", edit_identity(g, "npc", c, m.gm_user_id))
        race.wait_blocked_by(pause, updating)
        pause.release()
        race.join_all()
    assert saving.error is None and updating.error is None, (saving.describe(), updating.describe())
