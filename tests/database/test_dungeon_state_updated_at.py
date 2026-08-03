"""updated_at maintenance on the five dungeon timeline-state tables (revision 046).

Revision 040 gave each of these tables an updated_at column but never
attached core.set_updated_at() to any of them, so the column silently never
advanced past its creation-time default. This file proves all five now
behave like every other mutable table in the schema.

Asserted by writing a deliberately wrong updated_at and checking the trigger
replaces it, rather than by expecting the timestamp to advance between two
statements — core.set_updated_at() uses now(), which is *transaction start*
time in PostgreSQL, so two statements inside the one transaction the
db_connection fixture runs would otherwise produce the same value even with
a correctly firing trigger (see
tests/database/test_core_lookups_and_security.py::test_updated_at_trigger_overrides_supplied_value,
the pattern this file reuses).
"""

import uuid

import pytest
from sqlalchemy import Connection, text

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


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.dungeon_id = make_dungeon(connection, self.world_id)
        self.area_id = make_dungeon_area(connection, self.dungeon_id)


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "dungeon-state-updated-at-world")


def _assert_updated_at_overridden(
    connection: Connection, table: str, where_column: str, where_value: uuid.UUID
) -> None:
    connection.execute(
        text(
            f"UPDATE campaign.{table} SET updated_at = TIMESTAMPTZ '2000-01-01' "
            f"WHERE {where_column} = :v"
        ),
        {"v": where_value},
    )
    after = connection.execute(
        text(f"SELECT updated_at FROM campaign.{table} WHERE {where_column} = :v"),
        {"v": where_value},
    ).scalar()
    txn_now = connection.execute(text("SELECT now()")).scalar()
    assert after == txn_now, (
        f"core.set_updated_at() did not fire on campaign.{table} — updated_at kept the "
        "value supplied by the caller instead of being set to now()."
    )


def test_location_state_updated_at_is_maintained(db_connection: Connection, f: Fixture) -> None:
    db_connection.execute(
        text("INSERT INTO campaign.location_state (timeline_id, location_id) VALUES (:tl, :l)"),
        {"tl": f.timeline_id, "l": f.area_id},
    )
    _assert_updated_at_overridden(db_connection, "location_state", "location_id", f.area_id)


def test_area_connection_state_updated_at_is_maintained(
    db_connection: Connection, f: Fixture
) -> None:
    other_area = make_dungeon_area(db_connection, f.dungeon_id)
    connection_id = make_area_connection(db_connection, f.area_id, other_area)
    open_status = lookup_id(
        db_connection, "campaign", "connection_statuses", "connection_status_id", "open"
    )
    db_connection.execute(
        text(
            "INSERT INTO campaign.area_connection_state "
            "(timeline_id, area_connection_id, connection_status_id) VALUES (:tl, :c, :s)"
        ),
        {"tl": f.timeline_id, "c": connection_id, "s": open_status},
    )
    _assert_updated_at_overridden(
        db_connection, "area_connection_state", "area_connection_id", connection_id
    )


def test_area_feature_state_updated_at_is_maintained(db_connection: Connection, f: Fixture) -> None:
    feature_id = make_area_feature(db_connection, f.area_id)
    db_connection.execute(
        text(
            "INSERT INTO campaign.area_feature_state (timeline_id, area_feature_id) "
            "VALUES (:tl, :ft)"
        ),
        {"tl": f.timeline_id, "ft": feature_id},
    )
    _assert_updated_at_overridden(
        db_connection, "area_feature_state", "area_feature_id", feature_id
    )


def test_hazard_state_updated_at_is_maintained(db_connection: Connection, f: Fixture) -> None:
    hazard_id = make_area_hazard(db_connection, f.area_id)
    armed = lookup_id(db_connection, "campaign", "hazard_statuses", "hazard_status_id", "armed")
    db_connection.execute(
        text(
            "INSERT INTO campaign.hazard_state (timeline_id, area_hazard_id, hazard_status_id) "
            "VALUES (:tl, :h, :s)"
        ),
        {"tl": f.timeline_id, "h": hazard_id, "s": armed},
    )
    _assert_updated_at_overridden(db_connection, "hazard_state", "area_hazard_id", hazard_id)


def test_interactable_state_updated_at_is_maintained(db_connection: Connection, f: Fixture) -> None:
    interactable_id = make_area_interactable(db_connection, f.area_id)
    active = lookup_id(
        db_connection, "campaign", "interactable_statuses", "interactable_status_id", "active"
    )
    db_connection.execute(
        text(
            "INSERT INTO campaign.interactable_state "
            "(timeline_id, area_interactable_id, interactable_status_id) VALUES (:tl, :i, :s)"
        ),
        {"tl": f.timeline_id, "i": interactable_id, "s": active},
    )
    _assert_updated_at_overridden(
        db_connection, "interactable_state", "area_interactable_id", interactable_id
    )
