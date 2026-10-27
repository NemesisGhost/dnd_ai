"""Migration 140 (CP-9b): `narrative.clock_advance_details` on throwaway databases.

Covers a fresh upgrade, a populated upgrade (existing advances keep their events and get no
guessed marker) and the documented downgrade.
"""

import pytest
from sqlalchemy import Connection, create_engine, text

from dnd_ai.commands.events import _insert_event_row
from dnd_ai.commands.world_time import create_calendar, create_world_time
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_organization_hierarchy_migration import _alembic
from tests.database.test_phase8_populated_upgrade import (
    _alembic_upgrade,
    _connect_args,
    _drop_database,
    _provision_database,
)
from tests.factories import make_user

pytestmark = pytest.mark.database


def _table_present(connection: Connection) -> bool:
    return (
        connection.execute(text("SELECT to_regclass('narrative.clock_advance_details')")).scalar()
        is not None
    )


def _functions(connection: Connection) -> int:
    return int(
        connection.execute(
            text("SELECT count(*) FROM pg_proc WHERE proname LIKE 'enforce_clock_advance_detail%'")
        ).scalar()
        or 0
    )


def _event_count(connection: Connection, event_id: object) -> int:
    return int(
        connection.execute(
            text("SELECT count(*) FROM narrative.events WHERE event_id = :e"), {"e": event_id}
        ).scalar()
        or 0
    )


def test_populated_upgrade_and_documented_downgrade() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "139_inventory_capability")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.begin() as connection:
            assert not _table_present(connection)
            owner = make_user(connection, "Migration Owner")
            world = make_authored_world(connection, owner_user_id=owner, name="Migration World")
            campaign_id = make_authored_campaign(connection, world, name="Migration Campaign")
            calendar = create_calendar(
                connection,
                world_id=world.world_id,
                actor_user_id=owner,
                name="Cal",
                description=None,
                days_per_week=None,
                epoch_label=None,
                months=[("Only", 100)],
            )
            year = create_world_time(
                connection,
                campaign_id=campaign_id,
                actor_user_id=owner,
                calendar_id=calendar.calendar_id,
                year=1,
            ).world_time_id
            timeline_id = connection.execute(
                text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
                {"c": campaign_id},
            ).scalar()
            earlier_advance = _insert_event_row(
                connection,
                world_id=world.world_id,
                timeline_id=timeline_id,
                world_time_id=year,
                event_type_code="time_advanced",
                name="An earlier advance",
                campaign_id=campaign_id,
            )
        _alembic_upgrade(test_url, "140_clock_advance_details")
        with engine.begin() as connection:
            assert _table_present(connection) and _functions(connection) == 2
            # Populated upgrade: the earlier advance survives with no guessed marker.
            assert _event_count(connection, earlier_advance) == 1
            assert (
                connection.execute(
                    text("SELECT count(*) FROM narrative.clock_advance_details")
                ).scalar()
                == 0
            )
            connection.execute(
                text(
                    "INSERT INTO narrative.clock_advance_details (event_id, member_explanation) "
                    "VALUES (:e, 'kept')"
                ),
                {"e": earlier_advance},
            )
        downgraded = _alembic(test_url, "downgrade", "139_inventory_capability")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.begin() as connection:
            assert not _table_present(connection) and _functions(connection) == 0
            # Documented loss: the explanation is gone, the event stays.
            assert _event_count(connection, earlier_advance) == 1
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def test_a_fresh_database_upgrades_to_head_with_the_table_and_no_drift() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "head")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert _table_present(connection)
            columns = connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'narrative' AND table_name = 'clock_advance_details'"
                )
            ).scalars()
            assert set(columns) == {"event_id", "member_explanation", "created_at"}
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
