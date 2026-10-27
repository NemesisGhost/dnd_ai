"""Migration 126 (quest runtime event types): round trip on a throwaway database."""

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

CODES = [
    "quest_activated",
    "quest_completed",
    "quest_suspended",
    "quest_resumed",
    "quest_abandoned",
    "objective_activated",
    "objective_skipped",
]


def _present(connection) -> list[str]:  # type: ignore[no-untyped-def]
    return sorted(
        connection.execute(
            text("SELECT code FROM narrative.event_types WHERE code = ANY(:c)"), {"c": CODES}
        ).scalars()
    )


def test_upgrade_downgrade_and_reupgrade() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "125_quest_gm_notes")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert _present(connection) == []
        _alembic_upgrade(test_url, "126_quest_runtime_events")
        with engine.connect() as connection:
            assert _present(connection) == sorted(CODES)
        downgraded = _alembic(test_url, "downgrade", "125_quest_gm_notes")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert _present(connection) == []
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
