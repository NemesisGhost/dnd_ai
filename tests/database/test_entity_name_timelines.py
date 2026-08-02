"""Timeline scoping for core.entity_names (revision 012).

Closes the deferral revision 005 recorded: a name may be global (NULL
timeline_id, valid regardless of which timeline is being viewed) or scoped to
a same-world timeline, for a name that only exists after some historical
event. Proves the Phase 3 exit criterion: "An entity name may remain
world-global or be scoped to a same-world timeline; a cross-world timeline
reference is rejected by the database."
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import lookup_id, make_timeline, make_world, make_world_entity

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


def _name_type_id(connection: Connection, code: str = "common") -> uuid.UUID:
    return lookup_id(connection, "core", "name_types", "name_type_id", code)


def _add_name(
    connection: Connection,
    entity_id: uuid.UUID,
    name: str,
    *,
    timeline_id: uuid.UUID | None = None,
) -> None:
    connection.execute(
        text("""
            INSERT INTO core.entity_names (entity_id, name_type_id, name, timeline_id)
            VALUES (:e, :t, :n, :tl)
        """),
        {"e": entity_id, "t": _name_type_id(connection), "n": name, "tl": timeline_id},
    )


def test_a_name_defaults_to_global(db_connection: Connection) -> None:
    entity = make_world_entity(db_connection, "global-name")
    _add_name(db_connection, entity, "The Wanderer")

    timeline_id = db_connection.execute(
        text("SELECT timeline_id FROM core.entity_names WHERE entity_id = :e"), {"e": entity}
    ).scalar()
    assert timeline_id is None


def test_a_name_can_be_scoped_to_a_same_world_timeline(db_connection: Connection) -> None:
    entity = make_world_entity(db_connection, "scoped-name")
    entity_world = db_connection.execute(
        text("SELECT world_id FROM core.entities WHERE entity_id = :e"), {"e": entity}
    ).scalar()
    timeline = make_timeline(db_connection, entity_world, name="After the Fall")

    _add_name(db_connection, entity, "The Broken One", timeline_id=timeline)

    stored = db_connection.execute(
        text("SELECT timeline_id FROM core.entity_names WHERE entity_id = :e"), {"e": entity}
    ).scalar()
    assert stored == timeline


def test_a_name_scoped_to_another_worlds_timeline_is_rejected(db_connection: Connection) -> None:
    entity = make_world_entity(db_connection, "cross-world-name")
    other_world = make_world(db_connection, slug="name-timeline-other-world")
    foreign_timeline = make_timeline(db_connection, other_world, name="Elsewhere")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _add_name(db_connection, entity, "Impossible Name", timeline_id=foreign_timeline)
    assert "belongs to world" in str(exc.value)


def test_deleting_a_timeline_cascades_to_the_names_it_scopes(db_connection: Connection) -> None:
    entity = make_world_entity(db_connection, "cascade-name")
    entity_world = db_connection.execute(
        text("SELECT world_id FROM core.entities WHERE entity_id = :e"), {"e": entity}
    ).scalar()
    timeline = make_timeline(db_connection, entity_world, name="Temporary")
    _add_name(db_connection, entity, "Only In This Branch", timeline_id=timeline)

    db_connection.execute(
        text("DELETE FROM campaign.timelines WHERE timeline_id = :t"), {"t": timeline}
    )

    count = db_connection.execute(
        text("SELECT count(*) FROM core.entity_names WHERE entity_id = :e"), {"e": entity}
    ).scalar()
    assert count == 0
