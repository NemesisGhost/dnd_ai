"""Migration 124 (event corrections): round trip on a throwaway database."""

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


def _present(connection) -> tuple[bool, bool]:  # type: ignore[no-untyped-def]
    table = connection.execute(text("SELECT to_regclass('narrative.event_corrections')")).scalar()
    trigger = connection.execute(
        text("SELECT count(*) FROM pg_trigger WHERE tgname = 'ctr_events_status_has_correction'")
    ).scalar()
    return table is not None, bool(trigger)


def test_upgrade_downgrade_and_reupgrade() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "123_session_participants")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert _present(connection) == (False, False)
        _alembic_upgrade(test_url, "124_event_corrections")
        with engine.connect() as connection:
            assert _present(connection) == (True, True)
        downgraded = _alembic(test_url, "downgrade", "123_session_participants")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert _present(connection) == (False, False)
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
