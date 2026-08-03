"""Dungeon structural invariants remain valid after mutation (revision 044).

Revision 039's dungeon-structure rules were only validated at the moment a
row was first written. This file proves each one is now also revalidated on
UPDATE, so previously-valid data cannot be mutated into an invalid state:
connection endpoints and area assignments are immutable once set, location
containment rejects cycles of any length, and a dungeon area's parent is
re-checked whenever it changes via world.locations directly.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_area_connection,
    make_area_feature,
    make_area_hazard,
    make_area_interactable,
    make_dungeon,
    make_dungeon_area,
    make_location,
    make_world,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


# ---------------------------------------------------------------------------
# Immutable connection endpoints
# ---------------------------------------------------------------------------


def test_a_connections_endpoints_are_immutable(db_connection: Connection) -> None:
    world_id = make_world(db_connection, slug="mutation-safety-connection-world")
    dungeon_id = make_dungeon(db_connection, world_id)
    area_a = make_dungeon_area(db_connection, dungeon_id, name="A")
    area_b = make_dungeon_area(db_connection, dungeon_id, name="B")
    area_c = make_dungeon_area(db_connection, dungeon_id, name="C")
    connection_id = make_area_connection(db_connection, area_a, area_b)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE world.area_connections SET from_dungeon_area_id = :c "
                "WHERE area_connection_id = :id"
            ),
            {"c": area_c, "id": connection_id},
        )
    assert "immutable" in str(exc.value)


def test_moving_both_connection_endpoints_to_another_world_together_is_rejected(
    db_connection: Connection,
) -> None:
    """The exact scenario the review flagged: repointing both endpoints at
    once to areas in a different world, which would otherwise leave
    existing timeline-state/knowledge rows referencing the wrong world."""
    world_a = make_world(db_connection, slug="mutation-safety-connection-world-a")
    world_b = make_world(db_connection, slug="mutation-safety-connection-world-b")
    dungeon_a = make_dungeon(db_connection, world_a)
    dungeon_b = make_dungeon(db_connection, world_b)
    area_a1 = make_dungeon_area(db_connection, dungeon_a, name="A1")
    area_a2 = make_dungeon_area(db_connection, dungeon_a, name="A2")
    area_b1 = make_dungeon_area(db_connection, dungeon_b, name="B1")
    area_b2 = make_dungeon_area(db_connection, dungeon_b, name="B2")
    connection_id = make_area_connection(db_connection, area_a1, area_a2)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE world.area_connections "
                "SET from_dungeon_area_id = :f, to_dungeon_area_id = :t "
                "WHERE area_connection_id = :id"
            ),
            {"f": area_b1, "t": area_b2, "id": connection_id},
        )
    assert "immutable" in str(exc.value)


def test_a_connections_non_identity_columns_remain_mutable(db_connection: Connection) -> None:
    """Immutability is scoped to endpoints — is_hidden, description, and the
    other descriptive columns must stay editable."""
    world_id = make_world(db_connection, slug="mutation-safety-connection-mutable-world")
    dungeon_id = make_dungeon(db_connection, world_id)
    area_a = make_dungeon_area(db_connection, dungeon_id, name="A")
    area_b = make_dungeon_area(db_connection, dungeon_id, name="B")
    connection_id = make_area_connection(db_connection, area_a, area_b, is_hidden=False)

    db_connection.execute(
        text(
            "UPDATE world.area_connections SET is_hidden = true, description = 'now secret' "
            "WHERE area_connection_id = :id"
        ),
        {"id": connection_id},
    )
    row = db_connection.execute(
        text(
            "SELECT is_hidden, description FROM world.area_connections "
            "WHERE area_connection_id = :id"
        ),
        {"id": connection_id},
    ).one()
    assert row.is_hidden is True
    assert row.description == "now secret"


# ---------------------------------------------------------------------------
# Immutable dungeon_area_id on features, hazards, interactables
# ---------------------------------------------------------------------------


def test_a_feature_cannot_be_reassigned_to_another_area(db_connection: Connection) -> None:
    world_id = make_world(db_connection, slug="mutation-safety-feature-world")
    dungeon_id = make_dungeon(db_connection, world_id)
    area_a = make_dungeon_area(db_connection, dungeon_id, name="A")
    area_b = make_dungeon_area(db_connection, dungeon_id, name="B")
    feature_id = make_area_feature(db_connection, area_a)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE world.area_features SET dungeon_area_id = :a WHERE area_feature_id = :id"),
            {"a": area_b, "id": feature_id},
        )
    assert "immutable" in str(exc.value)


def test_a_hazard_cannot_be_reassigned_to_an_area_in_another_world(
    db_connection: Connection,
) -> None:
    world_a = make_world(db_connection, slug="mutation-safety-hazard-world-a")
    world_b = make_world(db_connection, slug="mutation-safety-hazard-world-b")
    dungeon_a = make_dungeon(db_connection, world_a)
    dungeon_b = make_dungeon(db_connection, world_b)
    area_a = make_dungeon_area(db_connection, dungeon_a)
    area_b = make_dungeon_area(db_connection, dungeon_b)
    hazard_id = make_area_hazard(db_connection, area_a)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE world.area_hazards SET dungeon_area_id = :a WHERE area_hazard_id = :id"),
            {"a": area_b, "id": hazard_id},
        )
    assert "immutable" in str(exc.value)


def test_an_interactable_cannot_be_reassigned_to_another_area(db_connection: Connection) -> None:
    world_id = make_world(db_connection, slug="mutation-safety-interactable-world")
    dungeon_id = make_dungeon(db_connection, world_id)
    area_a = make_dungeon_area(db_connection, dungeon_id, name="A")
    area_b = make_dungeon_area(db_connection, dungeon_id, name="B")
    interactable_id = make_area_interactable(db_connection, area_a)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE world.area_interactables SET dungeon_area_id = :a "
                "WHERE area_interactable_id = :id"
            ),
            {"a": area_b, "id": interactable_id},
        )
    assert "immutable" in str(exc.value)


# ---------------------------------------------------------------------------
# Dungeon-area parent rule, revalidated on UPDATE
# ---------------------------------------------------------------------------


def test_changing_a_dungeon_areas_parent_to_a_non_dungeon_is_rejected(
    db_connection: Connection,
) -> None:
    world_id = make_world(db_connection, slug="mutation-safety-reparent-world")
    dungeon_id = make_dungeon(db_connection, world_id)
    area_id = make_dungeon_area(db_connection, dungeon_id)
    region_id = make_location(db_connection, world_id, entity_type_code="region")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE world.locations SET parent_location_id = :r WHERE location_id = :a"),
            {"r": region_id, "a": area_id},
        )
    assert "not dungeon" in str(exc.value)


def test_clearing_a_dungeon_areas_parent_is_rejected(db_connection: Connection) -> None:
    world_id = make_world(db_connection, slug="mutation-safety-clear-parent-world")
    dungeon_id = make_dungeon(db_connection, world_id)
    area_id = make_dungeon_area(db_connection, dungeon_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE world.locations SET parent_location_id = NULL WHERE location_id = :a"),
            {"a": area_id},
        )
    assert "cannot be cleared" in str(exc.value)


def test_reparenting_a_dungeon_area_to_another_dungeon_is_accepted(
    db_connection: Connection,
) -> None:
    world_id = make_world(db_connection, slug="mutation-safety-valid-reparent-world")
    dungeon_a = make_dungeon(db_connection, world_id, name="Old Dungeon")
    dungeon_b = make_dungeon(db_connection, world_id, name="New Dungeon")
    area_id = make_dungeon_area(db_connection, dungeon_a)

    db_connection.execute(
        text("UPDATE world.locations SET parent_location_id = :d WHERE location_id = :a"),
        {"d": dungeon_b, "a": area_id},
    )
    parent = db_connection.execute(
        text("SELECT parent_location_id FROM world.locations WHERE location_id = :a"),
        {"a": area_id},
    ).scalar()
    assert parent == dungeon_b


def test_a_non_dungeon_area_location_may_still_be_freely_reparented(
    db_connection: Connection,
) -> None:
    """The dungeon-parent rule must not leak onto ordinary locations."""
    world_id = make_world(db_connection, slug="mutation-safety-ordinary-reparent-world")
    region_a = make_location(db_connection, world_id, entity_type_code="region", name="Region A")
    region_b = make_location(db_connection, world_id, entity_type_code="region", name="Region B")
    settlement_id = make_location(
        db_connection, world_id, parent_location_id=region_a, entity_type_code="settlement"
    )

    db_connection.execute(
        text("UPDATE world.locations SET parent_location_id = :r WHERE location_id = :s"),
        {"r": region_b, "s": settlement_id},
    )
    parent = db_connection.execute(
        text("SELECT parent_location_id FROM world.locations WHERE location_id = :s"),
        {"s": settlement_id},
    ).scalar()
    assert parent == region_b


# ---------------------------------------------------------------------------
# Containment cycles of any length
# ---------------------------------------------------------------------------


def test_a_two_node_cycle_is_rejected(db_connection: Connection) -> None:
    world_id = make_world(db_connection, slug="mutation-safety-two-cycle-world")
    region_a = make_location(db_connection, world_id, entity_type_code="region", name="A")
    region_b = make_location(
        db_connection, world_id, parent_location_id=region_a, entity_type_code="region", name="B"
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE world.locations SET parent_location_id = :b WHERE location_id = :a"),
            {"b": region_b, "a": region_a},
        )
    assert "cycle" in str(exc.value)


def test_a_multi_node_cycle_is_rejected(db_connection: Connection) -> None:
    """A -> B -> C, then attempting C -> A closes a three-node cycle."""
    world_id = make_world(db_connection, slug="mutation-safety-multi-cycle-world")
    region_a = make_location(db_connection, world_id, entity_type_code="region", name="A")
    region_b = make_location(
        db_connection, world_id, parent_location_id=region_a, entity_type_code="region", name="B"
    )
    region_c = make_location(
        db_connection, world_id, parent_location_id=region_b, entity_type_code="region", name="C"
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE world.locations SET parent_location_id = :c WHERE location_id = :a"),
            {"c": region_c, "a": region_a},
        )
    assert "cycle" in str(exc.value)


def test_valid_reparenting_that_does_not_create_a_cycle_is_accepted(
    db_connection: Connection,
) -> None:
    world_id = make_world(db_connection, slug="mutation-safety-valid-cycle-check-world")
    region_a = make_location(db_connection, world_id, entity_type_code="region", name="A")
    region_b = make_location(db_connection, world_id, entity_type_code="region", name="B")
    district = make_location(
        db_connection,
        world_id,
        parent_location_id=region_a,
        entity_type_code="district",
        name="District",
    )

    db_connection.execute(
        text("UPDATE world.locations SET parent_location_id = :b WHERE location_id = :d"),
        {"b": region_b, "d": district},
    )
    parent = db_connection.execute(
        text("SELECT parent_location_id FROM world.locations WHERE location_id = :d"),
        {"d": district},
    ).scalar()
    assert parent == region_b


def test_a_location_still_cannot_be_its_own_direct_parent(db_connection: Connection) -> None:
    """The zero-depth case of the same cycle rule, exercised through UPDATE
    rather than the ck_locations_not_own_parent CHECK covered elsewhere."""
    world_id = make_world(db_connection, slug="mutation-safety-direct-self-parent-world")
    region_a = make_location(db_connection, world_id, entity_type_code="region", name="A")

    with pytest.raises(CONSTRAINT_ERRORS):
        db_connection.execute(
            text("UPDATE world.locations SET parent_location_id = :a WHERE location_id = :a"),
            {"a": region_a},
        )
