"""Migration 123 (session participants, one session in progress): round trip on a throwaway database."""

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
        connection.execute(text("SELECT to_regclass('campaign.session_participants')")).scalar()
        is not None
    )


def _has_index(connection) -> bool:  # type: ignore[no-untyped-def]
    return (
        connection.execute(
            text("SELECT to_regclass('campaign.ux_sessions_one_in_progress')")
        ).scalar()
        is not None
    )


def test_upgrade_downgrade_and_reupgrade() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "122_session_definition")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert not _has_table(connection) and not _has_index(connection)
        _alembic_upgrade(test_url, "123_session_participants")
        with engine.connect() as connection:
            assert _has_table(connection) and _has_index(connection)
        downgraded = _alembic(test_url, "downgrade", "122_session_definition")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert not _has_table(connection) and not _has_index(connection)
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
