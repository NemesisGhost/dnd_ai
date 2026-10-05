"""Migration 119 (character_build_activated event type): round trip on a throwaway database."""

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


def _has_type(connection) -> bool:  # type: ignore[no-untyped-def]
    count = connection.execute(
        text("SELECT count(*) FROM narrative.event_types WHERE code = 'character_build_activated'")
    ).scalar()
    return bool(count == 1)


def test_upgrade_downgrade_and_reupgrade() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "118_campaign_clock")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert not _has_type(connection)
        _alembic_upgrade(test_url, "119_character_build_activated")
        with engine.connect() as connection:
            assert _has_type(connection)
        downgraded = _alembic(test_url, "downgrade", "118_campaign_clock")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert not _has_type(connection)
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
