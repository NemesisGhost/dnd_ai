"""Migration 125 (quest GM notes): round trip on a throwaway database."""

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


def _has_column(connection) -> bool:  # type: ignore[no-untyped-def]
    return bool(
        connection.execute(
            text(
                "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'narrative' "
                "AND table_name = 'quests' AND column_name = 'gm_notes'"
            )
        ).scalar()
    )


def test_upgrade_downgrade_and_reupgrade() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "124_event_corrections")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert not _has_column(connection)
        _alembic_upgrade(test_url, "125_quest_gm_notes")
        with engine.connect() as connection:
            assert _has_column(connection)
        downgraded = _alembic(test_url, "downgrade", "124_event_corrections")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert not _has_column(connection)
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
