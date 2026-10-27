"""Migration 130 (routes): round trip on a throwaway database."""

import pytest
from sqlalchemy import create_engine, text

from tests.database.test_organization_hierarchy_migration import _alembic
from tests.database.test_phase8_populated_upgrade import (
    _alembic_upgrade,
    _connect_args,
    _drop_database,
    _provision_database,
)

pytestmark = pytest.mark.database


def _state(connection) -> tuple[int, int, int]:  # type: ignore[no-untyped-def]
    table = connection.execute(
        text(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'world' "
            "AND table_name = 'route_relationships'"
        )
    ).scalar()
    lookups = connection.execute(
        text(
            "SELECT (SELECT count(*) FROM world.relationship_types WHERE code = 'route') "
            "+ (SELECT count(*) FROM world.relationship_participant_roles "
            "   WHERE code IN ('origin', 'destination'))"
        )
    ).scalar()
    event = connection.execute(
        text("SELECT count(*) FROM narrative.event_types WHERE code = 'characters_traveled'")
    ).scalar()
    return int(table or 0), int(lookups or 0), int(event or 0)


def test_upgrade_downgrade_and_reupgrade() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "129_relationship_definition")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert _state(connection) == (0, 0, 0)
        _alembic_upgrade(test_url, "130_routes")
        with engine.connect() as connection:
            assert _state(connection) == (1, 3, 1)
        downgraded = _alembic(test_url, "downgrade", "129_relationship_definition")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert _state(connection) == (0, 0, 0)
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
