"""character.characters, character.npcs, character.player_characters
(revision 017) — Phase 4's central first-time obligation.

Phase 2 could only prove core.enforce_entity_subtype() against a synthetic
table built inside a test transaction. This module is where it is proven
against the real, production-shape class-table inheritance chain:

    core.entities -> character.characters -> character.npcs
                                            -> character.player_characters

Covers the Phase 4 exit criterion verbatim: "A subtype row cannot exist
without its parent core.entities row, cannot use a primary key of its own,
and cannot attach to a parent of the wrong entity type — each rejected by
the database, each with a negative test."
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from tests.factories import (
    make_character,
    make_entity,
    make_ruleset_version,
    make_species,
    make_user,
    make_world,
)

pytestmark = pytest.mark.database


def _entity_type_id(connection: Connection, code: str) -> uuid.UUID:
    value = connection.execute(
        text("SELECT entity_type_id FROM core.entity_types WHERE code = :c"), {"c": code}
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


@pytest.fixture
def world_id(db_connection: Connection) -> uuid.UUID:
    return make_world(db_connection, slug="character-world")


# ---------------------------------------------------------------------------
# The entity_types Phase 4 registers
# ---------------------------------------------------------------------------


def test_character_type_hierarchy_is_registered(db_connection: Connection) -> None:
    rows = (
        db_connection.execute(
            text("""
            SELECT code, parent_entity_type_id, required_subtype_table
            FROM core.entity_types WHERE code IN ('character', 'npc', 'player_character')
        """)
        )
        .mappings()
        .all()
    )
    by_code = {r["code"]: r for r in rows}

    assert by_code["character"]["parent_entity_type_id"] is None
    assert by_code["character"]["required_subtype_table"] == "character.characters"
    assert by_code["npc"]["required_subtype_table"] == "character.npcs"
    assert by_code["player_character"]["required_subtype_table"] == "character.player_characters"


# ---------------------------------------------------------------------------
# NPC and PC share the same mechanical model
# ---------------------------------------------------------------------------


def test_npc_and_player_character_both_extend_characters(
    db_connection: Connection, world_id: uuid.UUID
) -> None:
    """The exit criterion: NPC and PC use the same mechanical model — both
    are, structurally, a character.characters row plus a marker subtype."""
    npc_id = make_character(db_connection, world_id, name="An NPC", entity_type_code="npc")
    db_connection.execute(text("INSERT INTO character.npcs (npc_id) VALUES (:i)"), {"i": npc_id})

    pc_id = make_character(
        db_connection, world_id, name="A PC", entity_type_code="player_character"
    )
    db_connection.execute(
        text("INSERT INTO character.player_characters (player_character_id) VALUES (:i)"),
        {"i": pc_id},
    )

    for character_id in (npc_id, pc_id):
        row = db_connection.execute(
            text(
                "SELECT species_id, size_category FROM character.characters WHERE character_id = :i"
            ),
            {"i": character_id},
        ).one()
        assert row.species_id is not None
        assert row.size_category == "medium"


# ---------------------------------------------------------------------------
# A character need not be an NPC or a PC
# ---------------------------------------------------------------------------


def test_a_bare_character_is_valid_with_no_npc_or_pc_row(
    db_connection: Connection, world_id: uuid.UUID
) -> None:
    """DATABASE_MODEL.md §7.1: future subtypes (companions, familiars, ...)
    reuse character.characters directly. character is not abstract."""
    make_character(db_connection, world_id, name="A Companion")


# ---------------------------------------------------------------------------
# Subtype consistency — the exit criterion, verbatim
# ---------------------------------------------------------------------------


def test_a_subtype_row_cannot_exist_without_its_parent_entity(
    db_connection: Connection,
) -> None:
    """ "cannot exist without its parent core.entities row"."""
    version = make_ruleset_version(db_connection)
    species = make_species(db_connection, version)

    with pytest.raises(IntegrityError):
        db_connection.execute(
            text(
                "INSERT INTO character.characters (character_id, species_id, size_category) "
                "VALUES (:i, :s, 'medium')"
            ),
            {"i": uuid.uuid4(), "s": species},
        )


def test_a_subtype_row_uses_the_parent_entitys_own_uuid(
    db_connection: Connection, world_id: uuid.UUID
) -> None:
    """ "cannot use a primary key of its own": character_id IS entity_id,
    never a fresh UUID."""
    character_id = make_character(db_connection, world_id)

    stored = db_connection.execute(
        text("SELECT character_id FROM character.characters WHERE character_id = :i"),
        {"i": character_id},
    ).scalar()
    assert stored == character_id


def test_npc_row_cannot_attach_to_a_non_npc_entity(
    db_connection: Connection, world_id: uuid.UUID
) -> None:
    """ "cannot attach to a parent of the wrong entity type": a character-typed
    (not npc-typed) entity cannot receive an npcs row."""
    character_id = make_character(db_connection, world_id)

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("INSERT INTO character.npcs (npc_id) VALUES (:i)"), {"i": character_id}
        )
    assert "does not require a row in character.npcs" in str(exc.value)


def test_player_character_row_cannot_attach_to_an_npc_entity(
    db_connection: Connection, world_id: uuid.UUID
) -> None:
    entity_type = _entity_type_id(db_connection, "npc")
    entity_id = make_entity(db_connection, world_id, entity_type, name="An NPC entity")
    species = make_species(db_connection, make_ruleset_version(db_connection))
    db_connection.execute(
        text(
            "INSERT INTO character.characters (character_id, species_id, size_category) "
            "VALUES (:i, :s, 'medium')"
        ),
        {"i": entity_id, "s": species},
    )
    db_connection.execute(text("INSERT INTO character.npcs (npc_id) VALUES (:i)"), {"i": entity_id})

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("INSERT INTO character.player_characters (player_character_id) VALUES (:i)"),
            {"i": entity_id},
        )
    assert "does not require a row in character.player_characters" in str(exc.value)


# ---------------------------------------------------------------------------
# character.characters own constraints
# ---------------------------------------------------------------------------


def test_size_category_must_be_a_recognized_value(
    db_connection: Connection, world_id: uuid.UUID
) -> None:
    entity_type = _entity_type_id(db_connection, "character")
    entity_id = make_entity(db_connection, world_id, entity_type)
    species = make_species(db_connection, make_ruleset_version(db_connection))

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO character.characters (character_id, species_id, size_category) "
                "VALUES (:i, :s, 'colossal')"
            ),
            {"i": entity_id, "s": species},
        )
    assert "ck_characters_size_category" in str(exc.value)


def test_player_character_can_be_linked_to_a_user(
    db_connection: Connection, world_id: uuid.UUID
) -> None:
    user_id = make_user(db_connection, username="a-player")
    character_id = make_character(db_connection, world_id, entity_type_code="player_character")
    db_connection.execute(
        text(
            "INSERT INTO character.player_characters (player_character_id, player_user_id) "
            "VALUES (:i, :u)"
        ),
        {"i": character_id, "u": user_id},
    )

    stored = db_connection.execute(
        text(
            "SELECT player_user_id FROM character.player_characters WHERE player_character_id = :i"
        ),
        {"i": character_id},
    ).scalar()
    assert stored == user_id
