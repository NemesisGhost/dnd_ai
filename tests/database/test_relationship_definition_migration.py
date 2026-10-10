"""Migration 129 (relationship versioning and lifecycle): round trip on a throwaway database."""

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


def _columns(connection) -> int:  # type: ignore[no-untyped-def]
    return int(
        connection.execute(
            text(
                "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'world' "
                "AND table_name = 'relationships' AND column_name IN "
                "('row_version', 'lifecycle_status_id', 'archived_at', 'created_by_user_id')"
            )
        ).scalar()
        or 0
    )


def test_upgrade_downgrade_and_reupgrade() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "128_dungeon_state_event")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert _columns(connection) == 0
        _alembic_upgrade(test_url, "129_relationship_definition")
        with engine.connect() as connection:
            assert _columns(connection) == 4
        downgraded = _alembic(test_url, "downgrade", "128_dungeon_state_event")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert _columns(connection) == 0
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
