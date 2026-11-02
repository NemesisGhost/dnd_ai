"""Migration 118 (campaign clock): round trip on a throwaway database."""

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


def _has_table(connection) -> bool:  # type: ignore[no-untyped-def]
    return (
        connection.execute(text("SELECT to_regclass('campaign.timeline_clocks')")).scalar()
        is not None
    )


def _event_types(connection) -> set[str]:  # type: ignore[no-untyped-def]
    return {
        str(c)
        for c in connection.execute(
            text("SELECT code FROM narrative.event_types WHERE code LIKE 'time_%'")
        ).scalars()
    }


def test_upgrade_downgrade_and_reupgrade() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "117_entity_revisions")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert not _has_table(connection) and _event_types(connection) == set()
        _alembic_upgrade(test_url, "118_campaign_clock")
        with engine.connect() as connection:
            assert _has_table(connection)
            assert _event_types(connection) == {"time_advanced", "time_corrected"}
        downgraded = _alembic(test_url, "downgrade", "117_entity_revisions")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert not _has_table(connection) and _event_types(connection) == set()
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
