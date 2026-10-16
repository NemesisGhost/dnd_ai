"""Migration 127 (knowledge runtime): round trip on a throwaway database."""

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

CODES = ["belief_changed", "knowledge_learned", "knowledge_made_public", "knowledge_transferred"]


def _state(connection) -> tuple[list[str], int]:  # type: ignore[no-untyped-def]
    codes = sorted(
        connection.execute(
            text("SELECT code FROM narrative.event_types WHERE code = ANY(:c)"), {"c": CODES}
        ).scalars()
    )
    columns = connection.execute(
        text(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'knowledge' "
            "AND table_name IN ('entity_knowledge', 'public_knowledge') "
            "AND column_name = 'last_event_id'"
        )
    ).scalar()
    return codes, int(columns)


def test_upgrade_downgrade_and_reupgrade() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "126_quest_runtime_events")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert _state(connection) == ([], 0)
        _alembic_upgrade(test_url, "127_knowledge_runtime")
        with engine.connect() as connection:
            assert _state(connection) == (CODES, 2)
        downgraded = _alembic(test_url, "downgrade", "126_quest_runtime_events")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert _state(connection) == ([], 0)
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
