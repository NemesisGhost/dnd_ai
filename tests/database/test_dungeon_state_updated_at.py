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
from sqlalchemy import Connection, Engine, text

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


# ---------------------------------------------------------------------------
# Real advancement, proven across genuinely separate transactions
# ---------------------------------------------------------------------------
# The tests above prove the trigger overwrites whatever value a caller
# supplies — but they never change a real state column, so the exit review
# asked for that directly: insert a row, capture its updated_at, mutate an
# actual state column (is_searched, a status lookup, ...) in a separate
# write, and confirm updated_at genuinely moved forward. That can't be
# observed inside one transaction (db_connection's fixture, or any single
# BEGIN) because core.set_updated_at() uses now(), which is transaction
# *start* time — two statements in the same transaction see the same value
# even with a correctly firing trigger. Using postgres_engine's real,
# separately-committed transactions instead gives each write its own
# transaction start time, so the comparison reflects actual trigger
# behavior rather than an artifact of how the test is structured — not a
# sleep-and-compare wall-clock guess, but two genuinely distinct
# transactions the database itself timestamps independently.


def _cleanup_committed_world(engine: Engine, slug: str) -> None:
    with engine.begin() as cleanup:
        params = {"s": slug}
        cleanup.execute(
            text(
                "DELETE FROM core.entities WHERE world_id IN "
                "(SELECT world_id FROM core.worlds WHERE slug = :s)"
            ),
            params,
        )
        cleanup.execute(text("DELETE FROM core.worlds WHERE slug = :s"), params)


class CommittedFixture:
    """Same shape as Fixture above, but built through committed transactions
    on the shared engine rather than db_connection's auto-rollback
    transaction — required so the insert and the later state-changing
    UPDATE are genuinely separate transactions."""

    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.dungeon_id = make_dungeon(connection, self.world_id)
        self.area_id = make_dungeon_area(connection, self.dungeon_id)


def test_location_state_updated_at_advances_on_a_real_state_change(
    postgres_engine: Engine,
) -> None:
    engine = postgres_engine
    slug = f"location-state-advance-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            cf = CommittedFixture(setup, slug)
            setup.execute(
                text(
                    "INSERT INTO campaign.location_state (timeline_id, location_id) "
                    "VALUES (:tl, :l)"
                ),
                {"tl": cf.timeline_id, "l": cf.area_id},
            )
            original = setup.execute(
                text("SELECT updated_at FROM campaign.location_state WHERE location_id = :l"),
                {"l": cf.area_id},
            ).scalar()

        with engine.begin() as mutate:
            mutate.execute(
                text(
                    "UPDATE campaign.location_state SET is_searched = true WHERE location_id = :l"
                ),
                {"l": cf.area_id},
            )

        with engine.connect() as verify:
            after = verify.execute(
                text(
                    "SELECT updated_at, is_searched FROM campaign.location_state "
                    "WHERE location_id = :l"
                ),
                {"l": cf.area_id},
            ).one()
        assert after.is_searched is True
        assert after.updated_at > original, (
            "updated_at did not advance after a real state change in a separate transaction"
        )
    finally:
        _cleanup_committed_world(engine, slug)


def test_area_connection_state_updated_at_advances_on_a_real_state_change(
    postgres_engine: Engine,
) -> None:
    engine = postgres_engine
    slug = f"connection-state-advance-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            cf = CommittedFixture(setup, slug)
            other_area = make_dungeon_area(setup, cf.dungeon_id)
            connection_id = make_area_connection(setup, cf.area_id, other_area)
            open_status = lookup_id(
                setup, "campaign", "connection_statuses", "connection_status_id", "open"
            )
            setup.execute(
                text(
                    "INSERT INTO campaign.area_connection_state "
                    "(timeline_id, area_connection_id, connection_status_id) "
                    "VALUES (:tl, :c, :s)"
                ),
                {"tl": cf.timeline_id, "c": connection_id, "s": open_status},
            )
            original = setup.execute(
                text(
                    "SELECT updated_at FROM campaign.area_connection_state "
                    "WHERE area_connection_id = :c"
                ),
                {"c": connection_id},
            ).scalar()

        with engine.begin() as mutate:
            locked_status = lookup_id(
                mutate, "campaign", "connection_statuses", "connection_status_id", "locked"
            )
            mutate.execute(
                text(
                    "UPDATE campaign.area_connection_state SET connection_status_id = :s "
                    "WHERE area_connection_id = :c"
                ),
                {"s": locked_status, "c": connection_id},
            )

        with engine.connect() as verify:
            after = verify.execute(
                text(
                    "SELECT acs.updated_at, cs.code FROM campaign.area_connection_state acs "
                    "JOIN campaign.connection_statuses cs "
                    "ON cs.connection_status_id = acs.connection_status_id "
                    "WHERE acs.area_connection_id = :c"
                ),
                {"c": connection_id},
            ).one()
        assert after.code == "locked"
        assert after.updated_at > original, (
            "updated_at did not advance after a real state change in a separate transaction"
        )
    finally:
        _cleanup_committed_world(engine, slug)


def test_area_feature_state_updated_at_advances_on_a_real_state_change(
    postgres_engine: Engine,
) -> None:
    engine = postgres_engine
    slug = f"feature-state-advance-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            cf = CommittedFixture(setup, slug)
            feature_id = make_area_feature(setup, cf.area_id)
            setup.execute(
                text(
                    "INSERT INTO campaign.area_feature_state (timeline_id, area_feature_id) "
                    "VALUES (:tl, :ft)"
                ),
                {"tl": cf.timeline_id, "ft": feature_id},
            )
            original = setup.execute(
                text(
                    "SELECT updated_at FROM campaign.area_feature_state WHERE area_feature_id = :ft"
                ),
                {"ft": feature_id},
            ).scalar()

        with engine.begin() as mutate:
            mutate.execute(
                text(
                    "UPDATE campaign.area_feature_state SET is_destroyed = true "
                    "WHERE area_feature_id = :ft"
                ),
                {"ft": feature_id},
            )

        with engine.connect() as verify:
            after = verify.execute(
                text(
                    "SELECT updated_at, is_destroyed FROM campaign.area_feature_state "
                    "WHERE area_feature_id = :ft"
                ),
                {"ft": feature_id},
            ).one()
        assert after.is_destroyed is True
        assert after.updated_at > original, (
            "updated_at did not advance after a real state change in a separate transaction"
        )
    finally:
        _cleanup_committed_world(engine, slug)


def test_hazard_state_updated_at_advances_on_a_real_state_change(
    postgres_engine: Engine,
) -> None:
    engine = postgres_engine
    slug = f"hazard-state-advance-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            cf = CommittedFixture(setup, slug)
            hazard_id = make_area_hazard(setup, cf.area_id)
            armed = lookup_id(setup, "campaign", "hazard_statuses", "hazard_status_id", "armed")
            setup.execute(
                text(
                    "INSERT INTO campaign.hazard_state "
                    "(timeline_id, area_hazard_id, hazard_status_id) VALUES (:tl, :h, :s)"
                ),
                {"tl": cf.timeline_id, "h": hazard_id, "s": armed},
            )
            original = setup.execute(
                text("SELECT updated_at FROM campaign.hazard_state WHERE area_hazard_id = :h"),
                {"h": hazard_id},
            ).scalar()

        with engine.begin() as mutate:
            triggered = lookup_id(
                mutate, "campaign", "hazard_statuses", "hazard_status_id", "triggered"
            )
            mutate.execute(
                text(
                    "UPDATE campaign.hazard_state SET hazard_status_id = :s "
                    "WHERE area_hazard_id = :h"
                ),
                {"s": triggered, "h": hazard_id},
            )

        with engine.connect() as verify:
            after = verify.execute(
                text(
                    "SELECT hs.updated_at, hst.code FROM campaign.hazard_state hs "
                    "JOIN campaign.hazard_statuses hst "
                    "ON hst.hazard_status_id = hs.hazard_status_id "
                    "WHERE hs.area_hazard_id = :h"
                ),
                {"h": hazard_id},
            ).one()
        assert after.code == "triggered"
        assert after.updated_at > original, (
            "updated_at did not advance after a real state change in a separate transaction"
        )
    finally:
        _cleanup_committed_world(engine, slug)


def test_interactable_state_updated_at_advances_on_a_real_state_change(
    postgres_engine: Engine,
) -> None:
    engine = postgres_engine
    slug = f"interactable-state-advance-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            cf = CommittedFixture(setup, slug)
            interactable_id = make_area_interactable(setup, cf.area_id)
            active = lookup_id(
                setup,
                "campaign",
                "interactable_statuses",
                "interactable_status_id",
                "active",
            )
            setup.execute(
                text(
                    "INSERT INTO campaign.interactable_state "
                    "(timeline_id, area_interactable_id, interactable_status_id) "
                    "VALUES (:tl, :i, :s)"
                ),
                {"tl": cf.timeline_id, "i": interactable_id, "s": active},
            )
            original = setup.execute(
                text(
                    "SELECT updated_at FROM campaign.interactable_state "
                    "WHERE area_interactable_id = :i"
                ),
                {"i": interactable_id},
            ).scalar()

        with engine.begin() as mutate:
            activated = lookup_id(
                mutate,
                "campaign",
                "interactable_statuses",
                "interactable_status_id",
                "activated",
            )
            mutate.execute(
                text(
                    "UPDATE campaign.interactable_state SET interactable_status_id = :s "
                    "WHERE area_interactable_id = :i"
                ),
                {"s": activated, "i": interactable_id},
            )

        with engine.connect() as verify:
            after = verify.execute(
                text(
                    "SELECT ist.updated_at, isu.code FROM campaign.interactable_state ist "
                    "JOIN campaign.interactable_statuses isu "
                    "ON isu.interactable_status_id = ist.interactable_status_id "
                    "WHERE ist.area_interactable_id = :i"
                ),
                {"i": interactable_id},
            ).one()
        assert after.code == "activated"
        assert after.updated_at > original, (
            "updated_at did not advance after a real state change in a separate transaction"
        )
    finally:
        _cleanup_committed_world(engine, slug)
