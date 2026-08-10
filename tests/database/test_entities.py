"""Constraint tests for revision 004 — worlds, entity types, entities, sources.

Positive and negative per docs/DATABASE_CONVENTIONS.md §32.1. Everything runs
inside the fixture's transaction and rolls back.

Test data is built through helpers rather than repeated inline, but note these
are raw inserts: §32.3 asks for construction through the same commands
production uses, and those commands do not exist yet (the application layer
arrives in a later phase). These tests are also specifically about database
enforcement — the constraints themselves — which is the exception §32.3 allows.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import make_entity, make_entity_type, make_user, make_world, status_id

pytestmark = pytest.mark.database


# ---------------------------------------------------------------------------
# core.worlds
# ---------------------------------------------------------------------------


def test_world_can_be_created(db_connection: Connection) -> None:
    assert make_world(db_connection) is not None


def test_world_rejects_duplicate_slug(db_connection: Connection) -> None:
    make_world(db_connection, slug="dupe-world")
    with pytest.raises(IntegrityError):
        make_world(db_connection, slug="dupe-world")


@pytest.mark.parametrize("bad_slug", ["Uppercase", "has_underscore", "9-leading-digit", ""])
def test_world_rejects_malformed_slug(db_connection: Connection, bad_slug: str) -> None:
    with pytest.raises(IntegrityError):
        make_world(db_connection, slug=bad_slug)


def test_world_requires_a_real_lifecycle_status(db_connection: Connection) -> None:
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text("""
                INSERT INTO core.worlds (name, slug, lifecycle_status_id)
                VALUES ('X', 'bad-status', gen_random_uuid())
            """)
        )


def test_lifecycle_status_in_use_cannot_be_deleted(db_connection: Connection) -> None:
    """ON DELETE RESTRICT — a status cannot vanish from under the worlds using it."""
    make_world(db_connection, slug="restrict-world")
    status = status_id(db_connection, "lifecycle_statuses", "active")
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text("DELETE FROM core.lifecycle_statuses WHERE lifecycle_status_id = :s"),
            {"s": status},
        )


# ---------------------------------------------------------------------------
# core.entity_types
# ---------------------------------------------------------------------------


def test_entity_type_can_have_a_parent(db_connection: Connection) -> None:
    parent = make_entity_type(db_connection, "parent_type")
    child = make_entity_type(db_connection, "child_type", parent_id=parent)
    assert child is not None


def test_entity_type_cannot_be_its_own_parent(db_connection: Connection) -> None:
    type_id = make_entity_type(db_connection, "self_parent")
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text(
                "UPDATE core.entity_types SET parent_entity_type_id = entity_type_id "
                "WHERE entity_type_id = :t"
            ),
            {"t": type_id},
        )


@pytest.mark.parametrize("bad_table", ["noschema", "Bad.Case", "a.b.c", "sch ema.tbl"])
def test_entity_type_rejects_unqualified_subtype_table(
    db_connection: Connection, bad_table: str
) -> None:
    with pytest.raises(IntegrityError):
        make_entity_type(db_connection, "bad_subtype", subtype_table=bad_table)


def test_entity_type_accepts_qualified_subtype_table(db_connection: Connection) -> None:
    assert make_entity_type(
        db_connection, "ok_subtype", subtype_table="character.npcs", subtype_pk_column="npc_id"
    )


def test_entity_type_in_use_cannot_be_deleted(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="etype-restrict")
    etype = make_entity_type(db_connection, "in_use_type")
    make_entity(db_connection, world, etype)
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text("DELETE FROM core.entity_types WHERE entity_type_id = :t"), {"t": etype}
        )


# ---------------------------------------------------------------------------
# core.entities
# ---------------------------------------------------------------------------


def test_entity_can_be_created_with_full_provenance(db_connection: Connection) -> None:
    """The Phase 2 exit criterion: a world and an entity, with provenance."""
    world = make_world(db_connection, slug="provenance-world")
    etype = make_entity_type(db_connection, "provenanced_type")
    user = make_user(db_connection, "Author")
    source = db_connection.execute(
        text("""
            INSERT INTO core.sources (world_id, source_type_id, title, created_by_user_id)
            VALUES (
                :world,
                (SELECT source_type_id FROM core.source_types WHERE code = 'gm_entry'),
                'Session 1 notes',
                :user
            )
            RETURNING source_id
        """),
        {"world": world, "user": user},
    ).scalar()

    row = db_connection.execute(
        text("""
            INSERT INTO core.entities
                (world_id, entity_type_id, canonical_name, canon_status_id,
                 lifecycle_status_id, source_id, created_by_user_id)
            VALUES (:world, :etype, 'Provenanced Thing', :canon, :lifecycle, :source, :user)
            RETURNING entity_id, source_id, created_by_user_id, canon_status_id
        """),
        {
            "world": world,
            "etype": etype,
            "canon": status_id(db_connection, "canon_statuses", "canon"),
            "lifecycle": status_id(db_connection, "lifecycle_statuses", "active"),
            "source": source,
            "user": user,
        },
    ).one()

    assert row.entity_id is not None
    assert row.source_id == source
    assert row.created_by_user_id == user


def test_entity_requires_a_world(db_connection: Connection) -> None:
    etype = make_entity_type(db_connection, "worldless_type")
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text("""
                INSERT INTO core.entities
                    (world_id, entity_type_id, canonical_name, canon_status_id,
                     lifecycle_status_id)
                VALUES (gen_random_uuid(), :etype, 'Orphan', :canon, :lifecycle)
            """),
            {
                "etype": etype,
                "canon": status_id(db_connection, "canon_statuses", "draft"),
                "lifecycle": status_id(db_connection, "lifecycle_statuses", "active"),
            },
        )


def test_entity_rejects_unseeded_canon_status(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="bad-canon")
    etype = make_entity_type(db_connection, "bad_canon_type")
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text("""
                INSERT INTO core.entities
                    (world_id, entity_type_id, canonical_name, canon_status_id,
                     lifecycle_status_id)
                VALUES (:world, :etype, 'X', gen_random_uuid(), :lifecycle)
            """),
            {
                "world": world,
                "etype": etype,
                "lifecycle": status_id(db_connection, "lifecycle_statuses", "active"),
            },
        )


def test_entity_rejects_empty_canonical_name(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="empty-name")
    etype = make_entity_type(db_connection, "empty_name_type")
    with pytest.raises(IntegrityError):
        make_entity(db_connection, world, etype, name="")


def test_world_with_entities_cannot_be_deleted(db_connection: Connection) -> None:
    """ON DELETE RESTRICT — entities are archived, not silently mass-deleted."""
    world = make_world(db_connection, slug="restrict-delete")
    etype = make_entity_type(db_connection, "restrict_type")
    make_entity(db_connection, world, etype)
    with pytest.raises(IntegrityError):
        db_connection.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": world})


def test_deleting_source_nulls_the_reference_rather_than_the_entity(
    db_connection: Connection,
) -> None:
    world = make_world(db_connection, slug="source-setnull")
    etype = make_entity_type(db_connection, "setnull_type")
    source = db_connection.execute(
        text("""
            INSERT INTO core.sources (world_id, source_type_id, title)
            VALUES (
                :world,
                (SELECT source_type_id FROM core.source_types WHERE code = 'gm_entry'),
                'Doomed source'
            )
            RETURNING source_id
        """),
        {"world": world},
    ).scalar()
    entity = db_connection.execute(
        text("""
            INSERT INTO core.entities
                (world_id, entity_type_id, canonical_name, canon_status_id,
                 lifecycle_status_id, source_id)
            VALUES (:world, :etype, 'Survivor', :canon, :lifecycle, :source)
            RETURNING entity_id
        """),
        {
            "world": world,
            "etype": etype,
            "canon": status_id(db_connection, "canon_statuses", "draft"),
            "lifecycle": status_id(db_connection, "lifecycle_statuses", "active"),
            "source": source,
        },
    ).scalar()

    db_connection.execute(text("DELETE FROM core.sources WHERE source_id = :s"), {"s": source})

    remaining = db_connection.execute(
        text("SELECT source_id FROM core.entities WHERE entity_id = :e"), {"e": entity}
    ).scalar()
    assert remaining is None, "entity should survive its source being deleted"


# ---------------------------------------------------------------------------
# core.sources
# ---------------------------------------------------------------------------


def test_source_may_be_global(db_connection: Connection) -> None:
    """A rulebook is not world-specific — world_id is nullable on purpose."""
    source = db_connection.execute(
        text("""
            INSERT INTO core.sources (world_id, source_type_id, title)
            VALUES (
                NULL,
                (SELECT source_type_id FROM core.source_types WHERE code = 'rulebook'),
                'Player Handbook'
            )
            RETURNING source_id
        """)
    ).scalar()
    assert source is not None


def test_deleting_world_cascades_to_its_sources(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="cascade-sources")
    db_connection.execute(
        text("""
            INSERT INTO core.sources (world_id, source_type_id, title)
            VALUES (
                :world,
                (SELECT source_type_id FROM core.source_types WHERE code = 'gm_entry'),
                'World-scoped note'
            )
        """),
        {"world": world},
    )
    db_connection.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": world})
    remaining = db_connection.execute(
        text("SELECT count(*) FROM core.sources WHERE world_id = :w"), {"w": world}
    ).scalar()
    assert remaining == 0


# ---------------------------------------------------------------------------
# core.enforce_entity_subtype()
# ---------------------------------------------------------------------------
#
# No real subtype table exists until Phase 4, so these build a synthetic one
# inside the test transaction. That is the point of the function being
# centralized (§7.4): it is table-agnostic, so it can be proven before the
# first real subtype exists rather than after.


def _make_subtype_table(connection: Connection, name: str, pk: str) -> str:
    """Create a throwaway subtype table wired to the shared enforcement trigger."""
    connection.execute(
        text(f"""
            CREATE TABLE core.{name} (
                {pk} UUID PRIMARY KEY REFERENCES core.entities(entity_id) ON DELETE CASCADE
            )
        """)
    )
    connection.execute(
        text(f"""
            CREATE TRIGGER tr_{name}_enforce_subtype
            AFTER INSERT OR UPDATE ON core.{name}
            FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_subtype('{pk}')
        """)
    )
    return f"core.{name}"


def test_subtype_row_accepted_when_entity_type_requires_that_table(
    db_connection: Connection,
) -> None:
    table = _make_subtype_table(db_connection, "tst_widgets", "widget_id")
    world = make_world(db_connection, slug="subtype-ok")
    etype = make_entity_type(
        db_connection, "widget", subtype_table=table, subtype_pk_column="widget_id"
    )
    entity = make_entity(db_connection, world, etype)

    db_connection.execute(
        text("INSERT INTO core.tst_widgets (widget_id) VALUES (:e)"), {"e": entity}
    )


def test_subtype_row_rejected_when_entity_type_does_not_require_it(
    db_connection: Connection,
) -> None:
    """The negative half — the invariant this function exists for."""
    _make_subtype_table(db_connection, "tst_widgets", "widget_id")
    world = make_world(db_connection, slug="subtype-bad")
    wrong_type = make_entity_type(db_connection, "not_a_widget")
    entity = make_entity(db_connection, world, wrong_type)

    with pytest.raises((IntegrityError, InternalError, ProgrammingError)) as exc:
        db_connection.execute(
            text("INSERT INTO core.tst_widgets (widget_id) VALUES (:e)"), {"e": entity}
        )
    assert "does not require a row in" in str(exc.value)


def test_subtype_row_accepted_via_inherited_type(db_connection: Connection) -> None:
    """A multi-level chain: the table is required by an ANCESTOR of the type.

    An entity of type `npc` has rows in character.characters and character.npcs;
    the characters table is named by the parent type, not the entity's own.
    """
    table = _make_subtype_table(db_connection, "tst_characters", "character_id")
    world = make_world(db_connection, slug="subtype-inherited")
    parent = make_entity_type(
        db_connection, "tst_character", subtype_table=table, subtype_pk_column="character_id"
    )
    child = make_entity_type(db_connection, "tst_npc", parent_id=parent)
    entity = make_entity(db_connection, world, child)

    db_connection.execute(
        text("INSERT INTO core.tst_characters (character_id) VALUES (:e)"), {"e": entity}
    )


def test_subtype_row_rejected_when_parent_entity_missing(db_connection: Connection) -> None:
    """A subtype row whose entity_id has no core.entities row.

    The foreign key catches this before the trigger does, which is the correct
    order — but assert it is caught at all.
    """
    _make_subtype_table(db_connection, "tst_widgets", "widget_id")
    with pytest.raises((IntegrityError, InternalError, ProgrammingError)):
        db_connection.execute(
            text("INSERT INTO core.tst_widgets (widget_id) VALUES (gen_random_uuid())")
        )
