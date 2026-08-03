"""character.characters.origin_location_id (revision 042).

Closes Phase 4's origin_location_id forward reference now that
world.locations exists. Covers same-world enforcement.

campaign.character_location_history — also introduced by revision 042 — is
covered in depth by tests/database/test_character_location_temporal_integrity.py
(revision 043 upgraded it to the full ADR 0010 interval contract, which
superseded this file's original, now-removed coverage of it) and by the
tests/scenario/test_dungeon_navigation.py multi-room navigation scenario.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import make_character, make_location, make_timeline, make_world

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.character_id = make_character(connection, self.world_id)


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "close-phase4-world")


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
