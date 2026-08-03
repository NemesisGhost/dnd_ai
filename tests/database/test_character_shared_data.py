"""character.character_descriptions, .character_languages, .character_senses,
.character_movements (revision 019).
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from tests.factories import make_character, make_ruleset_version_for_world, make_world

pytestmark = pytest.mark.database


@pytest.fixture
def world_id(db_connection: Connection) -> uuid.UUID:
    return make_world(db_connection, slug="shared-data-world")


@pytest.fixture
def character_id(db_connection: Connection, world_id: uuid.UUID) -> uuid.UUID:
    return make_character(db_connection, world_id)


def test_a_character_may_have_a_description(
    db_connection: Connection, character_id: uuid.UUID
) -> None:
    db_connection.execute(
        text(
            "INSERT INTO character.character_descriptions (character_id, background) "
            "VALUES (:c, 'Raised in a small village.')"
        ),
        {"c": character_id},
    )


def test_a_character_may_know_more_than_one_language(
    db_connection: Connection, character_id: uuid.UUID, world_id: uuid.UUID
) -> None:
    version = make_ruleset_version_for_world(db_connection, world_id)
    for code in ("common", "elvish"):
        language = db_connection.execute(
            text(
                "INSERT INTO rules.languages (ruleset_version_id, code, display_name) "
                "VALUES (:v, :c, :c) RETURNING language_id"
            ),
            {"v": version, "c": code},
        ).scalar()
        db_connection.execute(
            text(
                "INSERT INTO character.character_languages (character_id, language_id) "
                "VALUES (:c, :l)"
            ),
            {"c": character_id, "l": language},
        )

    count = db_connection.execute(
        text("SELECT count(*) FROM character.character_languages WHERE character_id = :c"),
        {"c": character_id},
    ).scalar()
    assert count == 2


def test_sense_range_must_be_positive(db_connection: Connection, character_id: uuid.UUID) -> None:
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_senses (character_id, sense_type, range_feet) "
                "VALUES (:c, 'darkvision', 0)"
            ),
            {"c": character_id},
        )
    assert "ck_character_senses_range_positive" in str(exc.value)


def test_a_character_cannot_have_two_ranges_for_the_same_sense(
    db_connection: Connection, character_id: uuid.UUID
) -> None:
    db_connection.execute(
        text(
            "INSERT INTO character.character_senses (character_id, sense_type, range_feet) "
            "VALUES (:c, 'darkvision', 60)"
        ),
        {"c": character_id},
    )
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text(
                "INSERT INTO character.character_senses (character_id, sense_type, range_feet) "
                "VALUES (:c, 'darkvision', 120)"
            ),
            {"c": character_id},
        )


def test_movement_speed_must_be_positive(
    db_connection: Connection, character_id: uuid.UUID
) -> None:
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.character_movements (character_id, movement_type, speed_feet) "
                "VALUES (:c, 'walk', 0)"
            ),
            {"c": character_id},
        )
    assert "ck_character_movements_speed_positive" in str(exc.value)


def test_a_character_may_have_more_than_one_movement_mode(
    db_connection: Connection, character_id: uuid.UUID
) -> None:
    for movement_type, speed in (("walk", 30), ("fly", 60)):
        db_connection.execute(
            text(
                "INSERT INTO character.character_movements (character_id, movement_type, speed_feet) "
                "VALUES (:c, :t, :s)"
            ),
            {"c": character_id, "t": movement_type, "s": speed},
        )

    count = db_connection.execute(
        text("SELECT count(*) FROM character.character_movements WHERE character_id = :c"),
        {"c": character_id},
    ).scalar()
    assert count == 2
