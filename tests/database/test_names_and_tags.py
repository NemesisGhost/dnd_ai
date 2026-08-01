"""Constraint tests for revision 005 — names, name types, tags, entity tags.

Positive and negative per docs/DATABASE_CONVENTIONS.md §32.1. Everything runs
inside the fixture's transaction and rolls back.
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import lookup_id, make_entity, make_entity_type, make_world, make_world_entity

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


def _name_type_id(connection: Connection, code: str) -> uuid.UUID:
    return lookup_id(connection, "core", "name_types", "name_type_id", code)


def _add_name(
    connection: Connection,
    entity_id: uuid.UUID,
    name: str,
    *,
    type_code: str = "common",
    is_primary: bool = False,
) -> None:
    connection.execute(
        text("""
            INSERT INTO core.entity_names (entity_id, name_type_id, name, is_primary)
            VALUES (:e, :t, :n, :p)
        """),
        {"e": entity_id, "t": _name_type_id(connection, type_code), "n": name, "p": is_primary},
    )


# ---------------------------------------------------------------------------
# core.name_types — seeded vocabulary
# ---------------------------------------------------------------------------


def test_seeded_name_types_cover_the_documented_vocabulary(db_connection: Connection) -> None:
    """DOMAIN_MODEL.md §4.4 plus `mistaken` from DATABASE_MODEL.md §5.4."""
    codes = {r[0] for r in db_connection.execute(text("SELECT code FROM core.name_types"))}
    assert codes == {
        "canonical",
        "common",
        "title",
        "nickname",
        "alias",
        "secret_identity",
        "former_name",
        "translated_name",
        "disguise",
        "mistaken",
    }


# ---------------------------------------------------------------------------
# core.entity_names
# ---------------------------------------------------------------------------


def test_entity_can_have_many_names(db_connection: Connection) -> None:
    entity = make_world_entity(db_connection, "many-names")
    _add_name(db_connection, entity, "The Grey Wanderer", type_code="common")
    _add_name(db_connection, entity, "Mithrandir", type_code="translated_name")
    _add_name(db_connection, entity, "Stormcrow", type_code="nickname")

    count = db_connection.execute(
        text("SELECT count(*) FROM core.entity_names WHERE entity_id = :e"), {"e": entity}
    ).scalar()
    assert count == 3


def test_entity_may_have_one_primary_name(db_connection: Connection) -> None:
    entity = make_world_entity(db_connection, "one-primary")
    _add_name(db_connection, entity, "Primary", is_primary=True)
    _add_name(db_connection, entity, "Secondary", is_primary=False)


def test_entity_cannot_have_two_primary_names(db_connection: Connection) -> None:
    """The partial unique index — only `is_primary` rows are constrained."""
    entity = make_world_entity(db_connection, "two-primary")
    _add_name(db_connection, entity, "First", is_primary=True)
    with pytest.raises(IntegrityError):
        _add_name(db_connection, entity, "Second", is_primary=True)


def test_two_entities_may_each_have_a_primary_name(db_connection: Connection) -> None:
    """The index is per entity, not global — the mistake a plain UNIQUE would make."""
    first = make_world_entity(db_connection, "primary-a")
    second = make_world_entity(db_connection, "primary-b")
    _add_name(db_connection, first, "A", is_primary=True)
    _add_name(db_connection, second, "B", is_primary=True)


def test_entity_names_reject_empty_name(db_connection: Connection) -> None:
    entity = make_world_entity(db_connection, "empty-name-tag")
    with pytest.raises(IntegrityError):
        _add_name(db_connection, entity, "")


def test_deleting_entity_cascades_to_its_names(db_connection: Connection) -> None:
    entity = make_world_entity(db_connection, "cascade-names")
    _add_name(db_connection, entity, "Doomed")
    db_connection.execute(text("DELETE FROM core.entities WHERE entity_id = :e"), {"e": entity})
    remaining = db_connection.execute(
        text("SELECT count(*) FROM core.entity_names WHERE entity_id = :e"), {"e": entity}
    ).scalar()
    assert remaining == 0


def test_name_type_in_use_cannot_be_deleted(db_connection: Connection) -> None:
    entity = make_world_entity(db_connection, "nametype-restrict")
    _add_name(db_connection, entity, "Held", type_code="alias")
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text("DELETE FROM core.name_types WHERE name_type_id = :t"),
            {"t": _name_type_id(db_connection, "alias")},
        )


# ---------------------------------------------------------------------------
# core.tags
# ---------------------------------------------------------------------------


def test_platform_tag_codes_are_unique(db_connection: Connection) -> None:
    db_connection.execute(
        text(
            "INSERT INTO core.tags (world_id, code, display_name) VALUES (NULL, 'undead', 'Undead')"
        )
    )
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text(
                "INSERT INTO core.tags (world_id, code, display_name) "
                "VALUES (NULL, 'undead', 'Undead Again')"
            )
        )


def test_two_worlds_may_define_the_same_tag_code(db_connection: Connection) -> None:
    """World-owned tags are scoped per world, so codes may repeat across them."""
    first = make_world(db_connection, slug="tagworld-a")
    second = make_world(db_connection, slug="tagworld-b")
    for world in (first, second):
        db_connection.execute(
            text(
                "INSERT INTO core.tags (world_id, code, display_name) "
                "VALUES (:w, 'faction', 'Faction')"
            ),
            {"w": world},
        )


def test_one_world_cannot_define_a_tag_code_twice(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="tagworld-dupe")
    db_connection.execute(
        text(
            "INSERT INTO core.tags (world_id, code, display_name) VALUES (:w, 'faction', 'Faction')"
        ),
        {"w": world},
    )
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text(
                "INSERT INTO core.tags (world_id, code, display_name) "
                "VALUES (:w, 'faction', 'Faction Again')"
            ),
            {"w": world},
        )


# ---------------------------------------------------------------------------
# core.entity_tags — including the cross-world guard
# ---------------------------------------------------------------------------


def test_platform_tag_applies_to_any_world(db_connection: Connection) -> None:
    entity = make_world_entity(db_connection, "platform-tagged")
    tag = db_connection.execute(
        text(
            "INSERT INTO core.tags (world_id, code, display_name) "
            "VALUES (NULL, 'legendary', 'Legendary') RETURNING tag_id"
        )
    ).scalar()
    db_connection.execute(
        text("INSERT INTO core.entity_tags (entity_id, tag_id) VALUES (:e, :t)"),
        {"e": entity, "t": tag},
    )


def test_world_tag_applies_to_an_entity_in_that_world(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="same-world-tag")
    etype = make_entity_type(db_connection, "same_world_type")
    entity = make_entity(db_connection, world, etype)
    tag = db_connection.execute(
        text(
            "INSERT INTO core.tags (world_id, code, display_name) "
            "VALUES (:w, 'local', 'Local') RETURNING tag_id"
        ),
        {"w": world},
    ).scalar()
    db_connection.execute(
        text("INSERT INTO core.entity_tags (entity_id, tag_id) VALUES (:e, :t)"),
        {"e": entity, "t": tag},
    )


def test_world_tag_cannot_be_applied_across_worlds(db_connection: Connection) -> None:
    """The invariant core.enforce_entity_tag_world() exists for.

    Cannot be a foreign key, because tags.world_id is nullable for platform tags.
    """
    tag_world = make_world(db_connection, slug="tag-owner-world")
    other_world = make_world(db_connection, slug="other-world")
    etype = make_entity_type(db_connection, "cross_world_type")
    foreign_entity = make_entity(db_connection, other_world, etype)

    tag = db_connection.execute(
        text(
            "INSERT INTO core.tags (world_id, code, display_name) "
            "VALUES (:w, 'private', 'Private') RETURNING tag_id"
        ),
        {"w": tag_world},
    ).scalar()

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("INSERT INTO core.entity_tags (entity_id, tag_id) VALUES (:e, :t)"),
            {"e": foreign_entity, "t": tag},
        )
    assert "belongs to world" in str(exc.value)


def test_entity_cannot_carry_the_same_tag_twice(db_connection: Connection) -> None:
    entity = make_world_entity(db_connection, "dupe-tag")
    tag = db_connection.execute(
        text(
            "INSERT INTO core.tags (world_id, code, display_name) "
            "VALUES (NULL, 'repeated', 'Repeated') RETURNING tag_id"
        )
    ).scalar()
    db_connection.execute(
        text("INSERT INTO core.entity_tags (entity_id, tag_id) VALUES (:e, :t)"),
        {"e": entity, "t": tag},
    )
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text("INSERT INTO core.entity_tags (entity_id, tag_id) VALUES (:e, :t)"),
            {"e": entity, "t": tag},
        )


def test_deleting_tag_removes_its_assignments(db_connection: Connection) -> None:
    entity = make_world_entity(db_connection, "cascade-tag")
    tag = db_connection.execute(
        text(
            "INSERT INTO core.tags (world_id, code, display_name) "
            "VALUES (NULL, 'temporary', 'Temporary') RETURNING tag_id"
        )
    ).scalar()
    db_connection.execute(
        text("INSERT INTO core.entity_tags (entity_id, tag_id) VALUES (:e, :t)"),
        {"e": entity, "t": tag},
    )
    db_connection.execute(text("DELETE FROM core.tags WHERE tag_id = :t"), {"t": tag})
    remaining = db_connection.execute(
        text("SELECT count(*) FROM core.entity_tags WHERE tag_id = :t"), {"t": tag}
    ).scalar()
    assert remaining == 0
