"""character.characters.origin_location_id and
campaign.character_location_history (revision 042).

Closes Phase 4's character-location forward references now that
world.locations exists. Covers: same-world enforcement on
origin_location_id, one open (current) location row per (timeline,
character), and world agreement across timeline/character/location on the
history table — together satisfying Phase 5's "a party can enter and
navigate a multi-room dungeon" exit criterion.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_character,
    make_dungeon,
    make_dungeon_area,
    make_location,
    make_timeline,
    make_world,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.character_id = make_character(connection, self.world_id)
        self.dungeon_id = make_dungeon(connection, self.world_id)
        self.area_a = make_dungeon_area(connection, self.dungeon_id, name="Entry Hall")
        self.area_b = make_dungeon_area(connection, self.dungeon_id, name="Corridor")


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "close-phase4-world")


# ---------------------------------------------------------------------------
# character.characters.origin_location_id
# ---------------------------------------------------------------------------


def test_a_character_can_have_an_origin_location(db_connection: Connection, f: Fixture) -> None:
    homeland = make_location(db_connection, f.world_id, entity_type_code="region", name="Home Vale")
    db_connection.execute(
        text("UPDATE character.characters SET origin_location_id = :l WHERE character_id = :c"),
        {"l": homeland, "c": f.character_id},
    )


def test_origin_location_must_share_the_characters_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="close-phase4-other-world")
    foreign_location = make_location(db_connection, other_world, entity_type_code="region")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE character.characters SET origin_location_id = :l WHERE character_id = :c"),
            {"l": foreign_location, "c": f.character_id},
        )
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# campaign.character_location_history
# ---------------------------------------------------------------------------


def test_a_character_can_enter_a_dungeon_area(db_connection: Connection, f: Fixture) -> None:
    db_connection.execute(
        text(
            "INSERT INTO campaign.character_location_history "
            "(timeline_id, character_id, location_id) VALUES (:tl, :c, :l)"
        ),
        {"tl": f.timeline_id, "c": f.character_id, "l": f.area_a},
    )
    current = db_connection.execute(
        text(
            "SELECT location_id FROM campaign.character_location_history "
            "WHERE timeline_id = :tl AND character_id = :c AND departed_at_world_time_id IS NULL"
        ),
        {"tl": f.timeline_id, "c": f.character_id},
    ).scalar()
    assert current == f.area_a


def test_a_character_can_move_between_dungeon_areas(db_connection: Connection, f: Fixture) -> None:
    """Movement is: close the open row, open a new one — the party navigating
    a multi-room dungeon (Phase 5 exit criterion)."""
    db_connection.execute(
        text(
            "INSERT INTO campaign.character_location_history "
            "(timeline_id, character_id, location_id) VALUES (:tl, :c, :l)"
        ),
        {"tl": f.timeline_id, "c": f.character_id, "l": f.area_a},
    )

    world_time = db_connection.execute(
        text(
            "INSERT INTO core.world_times (world_id, world_time_precision_id, year, sort_key) "
            "VALUES (:w, (SELECT world_time_precision_id FROM core.world_time_precisions "
            "WHERE code = 'exact'), 1000, 1) RETURNING world_time_id"
        ),
        {"w": f.world_id},
    ).scalar()

    db_connection.execute(
        text(
            "UPDATE campaign.character_location_history SET departed_at_world_time_id = :t "
            "WHERE timeline_id = :tl AND character_id = :c AND departed_at_world_time_id IS NULL"
        ),
        {"t": world_time, "tl": f.timeline_id, "c": f.character_id},
    )
    db_connection.execute(
        text(
            "INSERT INTO campaign.character_location_history "
            "(timeline_id, character_id, location_id, arrived_at_world_time_id) "
            "VALUES (:tl, :c, :l, :t)"
        ),
        {"tl": f.timeline_id, "c": f.character_id, "l": f.area_b, "t": world_time},
    )

    current = db_connection.execute(
        text(
            "SELECT location_id FROM campaign.character_location_history "
            "WHERE timeline_id = :tl AND character_id = :c AND departed_at_world_time_id IS NULL"
        ),
        {"tl": f.timeline_id, "c": f.character_id},
    ).scalar()
    assert current == f.area_b

    history_count = db_connection.execute(
        text(
            "SELECT count(*) FROM campaign.character_location_history "
            "WHERE timeline_id = :tl AND character_id = :c"
        ),
        {"tl": f.timeline_id, "c": f.character_id},
    ).scalar()
    assert history_count == 2


def test_only_one_open_location_per_timeline_and_character(
    db_connection: Connection, f: Fixture
) -> None:
    db_connection.execute(
        text(
            "INSERT INTO campaign.character_location_history "
            "(timeline_id, character_id, location_id) VALUES (:tl, :c, :l)"
        ),
        {"tl": f.timeline_id, "c": f.character_id, "l": f.area_a},
    )
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text(
                "INSERT INTO campaign.character_location_history "
                "(timeline_id, character_id, location_id) VALUES (:tl, :c, :l)"
            ),
            {"tl": f.timeline_id, "c": f.character_id, "l": f.area_b},
        )


def test_character_location_history_requires_world_agreement(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="close-phase4-history-other-world")
    other_timeline = make_timeline(db_connection, other_world, is_primary=True)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO campaign.character_location_history "
                "(timeline_id, character_id, location_id) VALUES (:tl, :c, :l)"
            ),
            {"tl": other_timeline, "c": f.character_id, "l": f.area_a},
        )
    assert "mixes worlds" in str(exc.value)
