"""Migration 120 (party versioning and lifecycle): populated round trip on a throwaway database."""

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


def _columns(connection) -> set[str]:  # type: ignore[no-untyped-def]
    return {
        str(c)
        for c in connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'campaign' AND table_name = 'parties'"
            )
        ).scalars()
    }


def test_existing_parties_become_active_and_the_round_trip_is_clean() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "119_character_build_activated")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.begin() as connection:
            world = connection.execute(
                text(
                    "INSERT INTO core.worlds (name, slug, lifecycle_status_id) VALUES "
                    "('Old World', 'old-world', (SELECT lifecycle_status_id "
                    "FROM core.lifecycle_statuses WHERE code = 'active')) RETURNING world_id"
                )
            ).scalar()
            connection.execute(
                text("INSERT INTO campaign.parties (world_id, name) VALUES (:w, 'Old Party')"),
                {"w": world},
            )
            assert "row_version" not in _columns(connection)
        _alembic_upgrade(test_url, "120_party_definition")
        with engine.connect() as connection:
            assert {"row_version", "lifecycle_status_id", "archived_at", "created_by_user_id"} <= (
                _columns(connection)
            )
            row = connection.execute(
                text(
                    "SELECT p.row_version, ls.code, p.created_by_user_id FROM campaign.parties p "
                    "JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = p.lifecycle_status_id"
                )
            ).one()
            assert (row.row_version, row.code, row.created_by_user_id) == (1, "active", None)
        downgraded = _alembic(test_url, "downgrade", "119_character_build_activated")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert "row_version" not in _columns(connection)
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
