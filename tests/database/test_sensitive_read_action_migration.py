"""Migration 116 seeds the `sensitive_read` audit action (checkpoint 15.2A-3).

Single-step upgrade/downgrade on a throwaway database, plus the conditional
downgrade policy shared with revision 103: it succeeds when nothing references
the action and refuses (changing nothing) once preview audit history exists.
"""

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


def _has_action(connection) -> bool:  # type: ignore[no-untyped-def]
    return bool(
        connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM audit.change_actions WHERE code = 'sensitive_read')")
        ).scalar()
    )


def test_upgrade_seeds_the_action_and_downgrade_removes_it_when_unreferenced() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "115_reporting_role_boundary")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert not _has_action(connection)
        _alembic_upgrade(test_url, "116_sensitive_read_action")
        with engine.connect() as connection:
            assert _has_action(connection)
        downgraded = _alembic(test_url, "downgrade", "115_reporting_role_boundary")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert not _has_action(connection)
        _alembic_upgrade(test_url, "head")
        with engine.connect() as connection:
            assert _has_action(connection)
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def test_downgrade_refuses_when_preview_audit_history_exists() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "116_sensitive_read_action")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.begin() as connection:
            connection.execute(
                text("""
                    INSERT INTO audit.change_log
                        (change_action_id, schema_name, table_name, actor_service, command_name)
                    VALUES ((SELECT change_action_id FROM audit.change_actions
                             WHERE code = 'sensitive_read'),
                            'narrative', 'quests', 'test', 'preview_quest')
                """)
            )
        blocked = _alembic(test_url, "downgrade", "115_reporting_role_boundary")
        assert blocked.returncode != 0
        assert "durable 'sensitive_read'" in blocked.stderr + blocked.stdout
        with engine.connect() as connection:
            assert _has_action(connection)
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
