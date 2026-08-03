"""campaign.location_state, .area_connection_state, .area_feature_state,
.hazard_state, .interactable_state (revision 040).

Covers: one current row per (timeline, target), the world-agreement guard on
each of the five tables, and that state can change (satisfying Phase 5's
"actions can alter dungeon state" exit criterion).
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    lookup_id,
    make_area_connection,
    make_area_feature,
    make_area_hazard,
    make_area_interactable,
    make_dungeon,
    make_dungeon_area,
    make_timeline,
    make_world,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.dungeon_id = make_dungeon(connection, self.world_id)
        self.area_id = make_dungeon_area(connection, self.dungeon_id)


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "dungeon-state-world")


def test_a_location_can_be_marked_searched(db_connection: Connection, f: Fixture) -> None:
    db_connection.execute(
        text(
            "INSERT INTO campaign.location_state (timeline_id, location_id, is_searched) "
            "VALUES (:tl, :l, true)"
        ),
        {"tl": f.timeline_id, "l": f.area_id},
    )
    is_searched = db_connection.execute(
        text(
            "SELECT is_searched FROM campaign.location_state "
            "WHERE timeline_id = :tl AND location_id = :l"
        ),
        {"tl": f.timeline_id, "l": f.area_id},
    ).scalar()
    assert is_searched is True


def test_location_state_requires_world_agreement(db_connection: Connection, f: Fixture) -> None:
    other_world = make_world(db_connection, slug="dungeon-state-other-world")
    other_timeline = make_timeline(db_connection, other_world, is_primary=True)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("INSERT INTO campaign.location_state (timeline_id, location_id) VALUES (:tl, :l)"),
            {"tl": other_timeline, "l": f.area_id},
        )
    assert "belongs to world" in str(exc.value)


def test_a_connection_can_change_status(db_connection: Connection, f: Fixture) -> None:
    other_area = make_dungeon_area(db_connection, f.dungeon_id)
    connection_id = make_area_connection(db_connection, f.area_id, other_area)
    open_status = lookup_id(
        db_connection, "campaign", "connection_statuses", "connection_status_id", "open"
    )
    locked_status = lookup_id(
        db_connection, "campaign", "connection_statuses", "connection_status_id", "locked"
    )

    db_connection.execute(
        text(
            "INSERT INTO campaign.area_connection_state "
            "(timeline_id, area_connection_id, connection_status_id) VALUES (:tl, :c, :s)"
        ),
        {"tl": f.timeline_id, "c": connection_id, "s": locked_status},
    )
    db_connection.execute(
        text(
            "UPDATE campaign.area_connection_state SET connection_status_id = :s "
            "WHERE timeline_id = :tl AND area_connection_id = :c"
        ),
        {"tl": f.timeline_id, "c": connection_id, "s": open_status},
    )

    current = db_connection.execute(
        text(
            "SELECT connection_status_id FROM campaign.area_connection_state "
            "WHERE timeline_id = :tl AND area_connection_id = :c"
        ),
        {"tl": f.timeline_id, "c": connection_id},
    ).scalar()
    assert current == open_status


def test_area_connection_state_requires_world_agreement(
    db_connection: Connection, f: Fixture
) -> None:
    other_area = make_dungeon_area(db_connection, f.dungeon_id)
    connection_id = make_area_connection(db_connection, f.area_id, other_area)
    status = lookup_id(
        db_connection, "campaign", "connection_statuses", "connection_status_id", "open"
    )
    other_world = make_world(db_connection, slug="dungeon-connection-state-other-world")
    other_timeline = make_timeline(db_connection, other_world, is_primary=True)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO campaign.area_connection_state "
                "(timeline_id, area_connection_id, connection_status_id) VALUES (:tl, :c, :s)"
            ),
            {"tl": other_timeline, "c": connection_id, "s": status},
        )
    assert "belongs to world" in str(exc.value)


def test_a_feature_can_be_marked_destroyed(db_connection: Connection, f: Fixture) -> None:
    feature_id = make_area_feature(db_connection, f.area_id)
    db_connection.execute(
        text(
            "INSERT INTO campaign.area_feature_state (timeline_id, area_feature_id, is_destroyed) "
            "VALUES (:tl, :ft, true)"
        ),
        {"tl": f.timeline_id, "ft": feature_id},
    )


def test_a_hazard_can_transition_status(db_connection: Connection, f: Fixture) -> None:
    hazard_id = make_area_hazard(db_connection, f.area_id, is_hidden=True)
    armed = lookup_id(db_connection, "campaign", "hazard_statuses", "hazard_status_id", "armed")
    disarmed = lookup_id(
        db_connection, "campaign", "hazard_statuses", "hazard_status_id", "disarmed"
    )

    db_connection.execute(
        text(
            "INSERT INTO campaign.hazard_state (timeline_id, area_hazard_id, hazard_status_id) "
            "VALUES (:tl, :h, :s)"
        ),
        {"tl": f.timeline_id, "h": hazard_id, "s": armed},
    )
    db_connection.execute(
        text(
            "UPDATE campaign.hazard_state SET hazard_status_id = :s "
            "WHERE timeline_id = :tl AND area_hazard_id = :h"
        ),
        {"tl": f.timeline_id, "h": hazard_id, "s": disarmed},
    )

    current = db_connection.execute(
        text(
            "SELECT hazard_status_id FROM campaign.hazard_state "
            "WHERE timeline_id = :tl AND area_hazard_id = :h"
        ),
        {"tl": f.timeline_id, "h": hazard_id},
    ).scalar()
    assert current == disarmed


def test_hazard_state_requires_world_agreement(db_connection: Connection, f: Fixture) -> None:
    hazard_id = make_area_hazard(db_connection, f.area_id)
    status = lookup_id(db_connection, "campaign", "hazard_statuses", "hazard_status_id", "armed")
    other_world = make_world(db_connection, slug="dungeon-hazard-state-other-world")
    other_timeline = make_timeline(db_connection, other_world, is_primary=True)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO campaign.hazard_state "
                "(timeline_id, area_hazard_id, hazard_status_id) VALUES (:tl, :h, :s)"
            ),
            {"tl": other_timeline, "h": hazard_id, "s": status},
        )
    assert "belongs to world" in str(exc.value)


def test_an_interactable_can_be_activated(db_connection: Connection, f: Fixture) -> None:
    interactable_id = make_area_interactable(db_connection, f.area_id)
    activated = lookup_id(
        db_connection, "campaign", "interactable_statuses", "interactable_status_id", "activated"
    )

    db_connection.execute(
        text(
            "INSERT INTO campaign.interactable_state "
            "(timeline_id, area_interactable_id, interactable_status_id) VALUES (:tl, :i, :s)"
        ),
        {"tl": f.timeline_id, "i": interactable_id, "s": activated},
    )


def test_interactable_state_requires_world_agreement(db_connection: Connection, f: Fixture) -> None:
    interactable_id = make_area_interactable(db_connection, f.area_id)
    status = lookup_id(
        db_connection, "campaign", "interactable_statuses", "interactable_status_id", "active"
    )
    other_world = make_world(db_connection, slug="dungeon-interactable-state-other-world")
    other_timeline = make_timeline(db_connection, other_world, is_primary=True)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO campaign.interactable_state "
                "(timeline_id, area_interactable_id, interactable_status_id) VALUES (:tl, :i, :s)"
            ),
            {"tl": other_timeline, "i": interactable_id, "s": status},
        )
    assert "belongs to world" in str(exc.value)


def test_only_one_current_state_row_per_timeline_and_target(
    db_connection: Connection, f: Fixture
) -> None:
    db_connection.execute(
        text("INSERT INTO campaign.location_state (timeline_id, location_id) VALUES (:tl, :l)"),
        {"tl": f.timeline_id, "l": f.area_id},
    )
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text("INSERT INTO campaign.location_state (timeline_id, location_id) VALUES (:tl, :l)"),
            {"tl": f.timeline_id, "l": f.area_id},
        )


def test_two_timelines_can_hold_independent_state_for_the_same_location(
    db_connection: Connection, f: Fixture
) -> None:
    """Two campaigns on the same timeline share dungeon state; two different
    timelines (e.g. a branch) do not — this is what makes that possible."""
    branch_timeline = make_timeline(db_connection, f.world_id, name="Branch")

    db_connection.execute(
        text(
            "INSERT INTO campaign.location_state (timeline_id, location_id, is_searched) "
            "VALUES (:tl, :l, true)"
        ),
        {"tl": f.timeline_id, "l": f.area_id},
    )
    db_connection.execute(
        text(
            "INSERT INTO campaign.location_state (timeline_id, location_id, is_searched) "
            "VALUES (:tl, :l, false)"
        ),
        {"tl": branch_timeline, "l": f.area_id},
    )

    rows = {
        r[0]: r[1]
        for r in db_connection.execute(
            text(
                "SELECT timeline_id, is_searched FROM campaign.location_state "
                "WHERE location_id = :l"
            ),
            {"l": f.area_id},
        )
    }
    assert rows[f.timeline_id] is True
    assert rows[branch_timeline] is False
