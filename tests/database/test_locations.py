"""world.locations, .settlements, .buildings (revision 038).

Covers: class-table-inheritance subtype enforcement for the location
hierarchy, parent_location_id containment and same-world enforcement, and
that leaf location types (plane, continent, ...) require no subtype row.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import lookup_id, make_entity, make_location, make_world

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


def test_a_bare_location_needs_no_subtype_row(db_connection: Connection) -> None:
    """A plane/continent/region/... is a location with no dedicated subtype
    table — core.enforce_entity_subtype() only requires world.locations."""
    world_id = make_world(db_connection, slug="locations-world")
    make_location(db_connection, world_id, entity_type_code="plane", name="The Material Plane")


def test_a_realm_location_can_be_created(db_connection: Connection) -> None:
    """docs/DOMAIN_MODEL.md §9.1 lists 'realm' among the location subtypes;
    revision 038 omitted it by oversight and revision 047 closes the gap."""
    world_id = make_world(db_connection, slug="locations-realm-world")
    make_location(db_connection, world_id, entity_type_code="realm", name="The Sundered Realm")


def test_a_settlement_row_with_population_succeeds(db_connection: Connection) -> None:
    world_id = make_world(db_connection, slug="locations-settlement-ok-world")
    settlement_id = make_location(
        db_connection, world_id, entity_type_code="settlement", name="Rivertown"
    )
    db_connection.execute(
        text("INSERT INTO world.settlements (settlement_id, population) VALUES (:s, 500)"),
        {"s": settlement_id},
    )


def test_a_settlement_row_for_a_bare_location_entity_is_rejected(db_connection: Connection) -> None:
    world_id = make_world(db_connection, slug="locations-settlement-mismatch-world")
    location_id = make_location(db_connection, world_id, entity_type_code="location")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("INSERT INTO world.settlements (settlement_id) VALUES (:l)"), {"l": location_id}
        )
    assert "does not require a row in" in str(exc.value)


def test_a_building_can_record_its_use(db_connection: Connection) -> None:
    world_id = make_world(db_connection, slug="locations-building-world")
    building_id = make_location(db_connection, world_id, entity_type_code="building")
    db_connection.execute(
        text("INSERT INTO world.buildings (building_id, building_use) VALUES (:b, 'tavern')"),
        {"b": building_id},
    )


def test_a_location_can_contain_another(db_connection: Connection) -> None:
    world_id = make_world(db_connection, slug="locations-containment-world")
    region_id = make_location(db_connection, world_id, entity_type_code="region", name="Vale")
    settlement_id = make_location(
        db_connection,
        world_id,
        parent_location_id=region_id,
        entity_type_code="settlement",
        name="Rivertown",
    )

    parent = db_connection.execute(
        text("SELECT parent_location_id FROM world.locations WHERE location_id = :s"),
        {"s": settlement_id},
    ).scalar()
    assert parent == region_id


def test_a_location_cannot_be_its_own_parent(db_connection: Connection) -> None:
    world_id = make_world(db_connection, slug="locations-self-parent-world")
    location_type_id = lookup_id(
        db_connection, "core", "entity_types", "entity_type_id", "location"
    )
    entity_id = make_entity(db_connection, world_id, location_type_id)

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("INSERT INTO world.locations (location_id, parent_location_id) VALUES (:l, :l)"),
            {"l": entity_id},
        )
    assert "ck_locations_not_own_parent" in str(exc.value)


def test_a_location_cannot_be_contained_in_a_location_from_another_world(
    db_connection: Connection,
) -> None:
    world_a = make_world(db_connection, slug="locations-parent-world-a")
    world_b = make_world(db_connection, slug="locations-parent-world-b")
    region_in_a = make_location(db_connection, world_a, entity_type_code="region")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_location(
            db_connection, world_b, parent_location_id=region_in_a, entity_type_code="settlement"
        )
    assert "belongs to world" in str(exc.value)
