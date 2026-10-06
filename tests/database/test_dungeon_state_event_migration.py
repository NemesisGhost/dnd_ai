"""Migration 128 (dungeon state event type): round trip on a throwaway database."""

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


def _present(connection) -> bool:  # type: ignore[no-untyped-def]
    return bool(
        connection.execute(
            text("SELECT count(*) FROM narrative.event_types WHERE code = 'dungeon_state_changed'")
        ).scalar()
    )


def test_upgrade_downgrade_and_reupgrade() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "127_knowledge_runtime")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert not _present(connection)
        _alembic_upgrade(test_url, "128_dungeon_state_event")
        with engine.connect() as connection:
            assert _present(connection)
        downgraded = _alembic(test_url, "downgrade", "127_knowledge_runtime")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert not _present(connection)
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
