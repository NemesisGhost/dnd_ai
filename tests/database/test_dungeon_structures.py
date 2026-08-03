"""world.dungeons, .dungeon_areas, .area_connections, .area_features,
.area_hazards, .area_interactables (revision 039).

Covers: a dungeon area must belong to a dungeon-typed parent location, area
connections require world agreement but NOT same-dungeon agreement
(teleportation links may cross dungeons), and that is_hidden is a plain
structural column with no knowledge-domain coupling.
"""

import uuid

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


def test_a_dungeon_can_hold_a_danger_level(db_connection: Connection) -> None:
    world_id = make_world(db_connection, slug="dungeon-structures-world")
    dungeon_id = make_dungeon(db_connection, world_id)
    db_connection.execute(
        text("UPDATE world.dungeons SET danger_level = 7 WHERE dungeon_id = :d"),
        {"d": dungeon_id},
    )


def test_a_dungeon_area_belongs_to_its_dungeon_via_containment(db_connection: Connection) -> None:
    world_id = make_world(db_connection, slug="dungeon-area-parent-world")
    dungeon_id = make_dungeon(db_connection, world_id)
    area_id = make_dungeon_area(db_connection, dungeon_id)

    parent = db_connection.execute(
        text("SELECT parent_location_id FROM world.locations WHERE location_id = :a"),
        {"a": area_id},
    ).scalar()
    assert parent == dungeon_id


def test_a_dungeon_area_must_have_a_parent_location(db_connection: Connection) -> None:
    world_id = make_world(db_connection, slug="dungeon-area-no-parent-world")
    area_id = make_location(db_connection, world_id, entity_type_code="dungeon_area")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("INSERT INTO world.dungeon_areas (dungeon_area_id) VALUES (:a)"), {"a": area_id}
        )
    assert "no parent_location_id" in str(exc.value)


def test_a_dungeon_areas_parent_must_be_a_dungeon(db_connection: Connection) -> None:
    world_id = make_world(db_connection, slug="dungeon-area-wrong-parent-world")
    region_id = make_location(db_connection, world_id, entity_type_code="region")
    area_id = make_location(
        db_connection, world_id, parent_location_id=region_id, entity_type_code="dungeon_area"
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("INSERT INTO world.dungeon_areas (dungeon_area_id) VALUES (:a)"), {"a": area_id}
        )
    assert "not dungeon" in str(exc.value)


def test_areas_in_the_same_dungeon_can_be_connected(db_connection: Connection) -> None:
    world_id = make_world(db_connection, slug="dungeon-connection-world")
    dungeon_id = make_dungeon(db_connection, world_id)
    area_a = make_dungeon_area(db_connection, dungeon_id, name="Entry Hall")
    area_b = make_dungeon_area(db_connection, dungeon_id, name="Corridor")

    make_area_connection(db_connection, area_a, area_b, connection_type_code="door")


def test_a_connection_cannot_link_an_area_to_itself(db_connection: Connection) -> None:
    world_id = make_world(db_connection, slug="dungeon-self-connection-world")
    dungeon_id = make_dungeon(db_connection, world_id)
    area = make_dungeon_area(db_connection, dungeon_id)

    with pytest.raises(IntegrityError) as exc:
        make_area_connection(db_connection, area, area)
    assert "ck_area_connections_not_self_linked" in str(exc.value)


def test_a_connection_requires_both_areas_from_the_same_world(db_connection: Connection) -> None:
    world_a = make_world(db_connection, slug="dungeon-connection-world-a")
    world_b = make_world(db_connection, slug="dungeon-connection-world-b")
    dungeon_a = make_dungeon(db_connection, world_a)
    dungeon_b = make_dungeon(db_connection, world_b)
    area_a = make_dungeon_area(db_connection, dungeon_a)
    area_b = make_dungeon_area(db_connection, dungeon_b)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_area_connection(db_connection, area_a, area_b)
    assert "different worlds" in str(exc.value)


def test_a_teleportation_link_may_cross_dungeons_in_the_same_world(
    db_connection: Connection,
) -> None:
    """docs/DOMAIN_MODEL.md §9.6 names teleportation links crossing dungeons
    as a use case — same-world is required, same-dungeon is not."""
    world_id = make_world(db_connection, slug="dungeon-teleport-world")
    dungeon_a = make_dungeon(db_connection, world_id, name="The Undercroft")
    dungeon_b = make_dungeon(db_connection, world_id, name="The Sky Vault")
    area_a = make_dungeon_area(db_connection, dungeon_a)
    area_b = make_dungeon_area(db_connection, dungeon_b)

    make_area_connection(db_connection, area_a, area_b, connection_type_code="teleportation_link")


def test_a_hidden_connection_is_indistinguishable_from_a_visible_one_except_for_the_flag(
    db_connection: Connection,
) -> None:
    """docs/architecture/DATABASE_MODEL.md §9.3: a hidden feature exists
    independently of whether a party knows about it. is_hidden is a plain
    structural fact, not a knowledge-domain concept."""
    world_id = make_world(db_connection, slug="dungeon-hidden-connection-world")
    dungeon_id = make_dungeon(db_connection, world_id)
    area_a = make_dungeon_area(db_connection, dungeon_id)
    area_b = make_dungeon_area(db_connection, dungeon_id)

    hidden_id = make_area_connection(
        db_connection, area_a, area_b, connection_type_code="secret_door", is_hidden=True
    )

    row = db_connection.execute(
        text("SELECT is_hidden FROM world.area_connections WHERE area_connection_id = :c"),
        {"c": hidden_id},
    ).one()
    assert row.is_hidden is True


def test_a_connection_can_be_marked_conditional_with_a_description(
    db_connection: Connection,
) -> None:
    """docs/PLAN.md §9.2 names conditional routes; revision 047 adds the
    descriptive columns (evaluating the condition is a later-phase concern —
    see that revision's docstring)."""
    world_id = make_world(db_connection, slug="dungeon-conditional-route-world")
    dungeon_id = make_dungeon(db_connection, world_id)
    area_a = make_dungeon_area(db_connection, dungeon_id)
    area_b = make_dungeon_area(db_connection, dungeon_id)

    connection_id = db_connection.execute(
        text("""
            INSERT INTO world.area_connections
                (from_dungeon_area_id, to_dungeon_area_id, connection_type_id,
                 is_conditional, condition_description)
            VALUES (
                :f, :t,
                (SELECT connection_type_id FROM world.connection_types WHERE code = 'portal'),
                true, 'requires the brass key'
            )
            RETURNING area_connection_id
        """),
        {"f": area_a, "t": area_b},
    ).scalar()

    row = db_connection.execute(
        text(
            "SELECT is_conditional, condition_description FROM world.area_connections "
            "WHERE area_connection_id = :c"
        ),
        {"c": connection_id},
    ).one()
    assert row.is_conditional is True
    assert row.condition_description == "requires the brass key"


def test_a_connection_defaults_to_unconditional(db_connection: Connection) -> None:
    world_id = make_world(db_connection, slug="dungeon-unconditional-route-world")
    dungeon_id = make_dungeon(db_connection, world_id)
    area_a = make_dungeon_area(db_connection, dungeon_id)
    area_b = make_dungeon_area(db_connection, dungeon_id)

    connection_id = make_area_connection(db_connection, area_a, area_b)
    is_conditional = db_connection.execute(
        text("SELECT is_conditional FROM world.area_connections WHERE area_connection_id = :c"),
        {"c": connection_id},
    ).scalar()
    assert is_conditional is False


# ---------------------------------------------------------------------------
# Conditional-route column semantics (revision 051)
# ---------------------------------------------------------------------------
# revision 047 added is_conditional/condition_description with no constraint
# tying them together; revision 051 makes the pairing explicit rather than
# leaving both contradictory-looking states silently permitted.


def _insert_connection(
    connection: Connection,
    area_a: object,
    area_b: object,
    *,
    is_conditional: bool,
    condition_description: str | None,
) -> None:
    connection.execute(
        text("""
            INSERT INTO world.area_connections
                (from_dungeon_area_id, to_dungeon_area_id, connection_type_id,
                 is_conditional, condition_description)
            VALUES (
                :f, :t,
                (SELECT connection_type_id FROM world.connection_types WHERE code = 'door'),
                :cond, :desc
            )
        """),
        {"f": area_a, "t": area_b, "cond": is_conditional, "desc": condition_description},
    )


def test_a_conditional_route_without_a_description_is_rejected(
    db_connection: Connection,
) -> None:
    world_id = make_world(db_connection, slug="conditional-route-missing-description")
    dungeon_id = make_dungeon(db_connection, world_id)
    area_a = make_dungeon_area(db_connection, dungeon_id)
    area_b = make_dungeon_area(db_connection, dungeon_id)

    with pytest.raises(IntegrityError) as exc:
        _insert_connection(
            db_connection, area_a, area_b, is_conditional=True, condition_description=None
        )
    assert "ck_area_connections_conditional_description_paired" in str(exc.value)


@pytest.mark.parametrize(
    "blank_description",
    [
        pytest.param("   ", id="spaces_only"),
        pytest.param("\t\t", id="tabs_only"),
        pytest.param("\n\n", id="newlines_only"),
        pytest.param("\r\r", id="carriage_returns_only"),
        pytest.param(" \t\n\r ", id="mixed_whitespace"),
        pytest.param("", id="empty_string"),
    ],
)
def test_a_conditional_route_with_a_blank_description_is_rejected(
    db_connection: Connection, blank_description: str
) -> None:
    """Non-blank, not just non-null — and "blank" means the project's
    complete whitespace rule (revision 055), not merely "not an ordinary
    space": a tab-only, newline-only, carriage-return-only, or mixed
    whitespace-only description must all be rejected exactly like a
    space-only one."""
    world_id = make_world(
        db_connection, slug=f"conditional-route-blank-description-{uuid.uuid4().hex[:8]}"
    )
    dungeon_id = make_dungeon(db_connection, world_id)
    area_a = make_dungeon_area(db_connection, dungeon_id)
    area_b = make_dungeon_area(db_connection, dungeon_id)

    with pytest.raises(IntegrityError) as exc:
        _insert_connection(
            db_connection,
            area_a,
            area_b,
            is_conditional=True,
            condition_description=blank_description,
        )
    assert "ck_area_connections_conditional_description_paired" in str(exc.value)


def test_a_conditional_route_with_whitespace_surrounding_real_text_is_accepted(
    db_connection: Connection,
) -> None:
    """The rule is "contains at least one non-whitespace character," not
    "contains no whitespace at all" — a description padded with whitespace
    around real content must still be accepted."""
    world_id = make_world(db_connection, slug="conditional-route-padded-description")
    dungeon_id = make_dungeon(db_connection, world_id)
    area_a = make_dungeon_area(db_connection, dungeon_id)
    area_b = make_dungeon_area(db_connection, dungeon_id)

    connection_id = db_connection.execute(
        text("""
            INSERT INTO world.area_connections
                (from_dungeon_area_id, to_dungeon_area_id, connection_type_id,
                 is_conditional, condition_description)
            VALUES (
                :f, :t,
                (SELECT connection_type_id FROM world.connection_types WHERE code = 'door'),
                true, '  requires the brass key  '
            )
            RETURNING area_connection_id
        """),
        {"f": area_a, "t": area_b},
    ).scalar()
    description = db_connection.execute(
        text(
            "SELECT condition_description FROM world.area_connections WHERE area_connection_id = :c"
        ),
        {"c": connection_id},
    ).scalar()
    assert description == "  requires the brass key  "


def test_an_unconditional_route_with_a_description_is_rejected(
    db_connection: Connection,
) -> None:
    world_id = make_world(db_connection, slug="conditional-route-stray-description")
    dungeon_id = make_dungeon(db_connection, world_id)
    area_a = make_dungeon_area(db_connection, dungeon_id)
    area_b = make_dungeon_area(db_connection, dungeon_id)

    with pytest.raises(IntegrityError) as exc:
        _insert_connection(
            db_connection,
            area_a,
            area_b,
            is_conditional=False,
            condition_description="requires the brass key",
        )
    assert "ck_area_connections_conditional_description_paired" in str(exc.value)


def test_updating_a_route_to_conditional_without_a_description_is_rejected(
    db_connection: Connection,
) -> None:
    """The constraint must also hold on UPDATE, not just INSERT."""
    world_id = make_world(db_connection, slug="conditional-route-update-missing-description")
    dungeon_id = make_dungeon(db_connection, world_id)
    area_a = make_dungeon_area(db_connection, dungeon_id)
    area_b = make_dungeon_area(db_connection, dungeon_id)
    connection_id = make_area_connection(db_connection, area_a, area_b)

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "UPDATE world.area_connections SET is_conditional = true "
                "WHERE area_connection_id = :c"
            ),
            {"c": connection_id},
        )
    assert "ck_area_connections_conditional_description_paired" in str(exc.value)


def test_updating_a_conditional_route_to_unconditional_clears_the_description(
    db_connection: Connection,
) -> None:
    """The valid way to make a route unconditional: both columns change
    together in the same UPDATE."""
    world_id = make_world(db_connection, slug="conditional-route-update-to-unconditional")
    dungeon_id = make_dungeon(db_connection, world_id)
    area_a = make_dungeon_area(db_connection, dungeon_id)
    area_b = make_dungeon_area(db_connection, dungeon_id)
    connection_id = db_connection.execute(
        text("""
            INSERT INTO world.area_connections
                (from_dungeon_area_id, to_dungeon_area_id, connection_type_id,
                 is_conditional, condition_description)
            VALUES (
                :f, :t,
                (SELECT connection_type_id FROM world.connection_types WHERE code = 'door'),
                true, 'requires the brass key'
            )
            RETURNING area_connection_id
        """),
        {"f": area_a, "t": area_b},
    ).scalar()

    db_connection.execute(
        text(
            "UPDATE world.area_connections "
            "SET is_conditional = false, condition_description = NULL "
            "WHERE area_connection_id = :c"
        ),
        {"c": connection_id},
    )
    row = db_connection.execute(
        text(
            "SELECT is_conditional, condition_description FROM world.area_connections "
            "WHERE area_connection_id = :c"
        ),
        {"c": connection_id},
    ).one()
    assert row.is_conditional is False
    assert row.condition_description is None


def test_features_hazards_and_interactables_belong_to_an_area(db_connection: Connection) -> None:
    world_id = make_world(db_connection, slug="dungeon-children-world")
    dungeon_id = make_dungeon(db_connection, world_id)
    area_id = make_dungeon_area(db_connection, dungeon_id)

    make_area_feature(db_connection, area_id)
    make_area_hazard(db_connection, area_id, is_hidden=True)
    make_area_interactable(db_connection, area_id)

    counts = db_connection.execute(
        text(
            "SELECT "
            "(SELECT count(*) FROM world.area_features WHERE dungeon_area_id = :a), "
            "(SELECT count(*) FROM world.area_hazards WHERE dungeon_area_id = :a), "
            "(SELECT count(*) FROM world.area_interactables WHERE dungeon_area_id = :a)"
        ),
        {"a": area_id},
    ).one()
    assert counts == (1, 1, 1)
