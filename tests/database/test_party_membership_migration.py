"""Migration 121 (party membership events): round trip on a throwaway database."""

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


def _state(connection) -> tuple[set[str], set[str]]:  # type: ignore[no-untyped-def]
    columns = {
        str(c)
        for c in connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'campaign' AND table_name = 'party_memberships'"
            )
        ).scalars()
    }
    types = {
        str(c)
        for c in connection.execute(
            text("SELECT code FROM narrative.event_types WHERE code LIKE 'party_member_%'")
        ).scalars()
    }
    return columns, types


def test_upgrade_downgrade_and_reupgrade() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "120_party_definition")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            columns, types = _state(connection)
            assert "joined_event_id" not in columns and types == set()
        _alembic_upgrade(test_url, "121_party_membership_events")
        with engine.connect() as connection:
            columns, types = _state(connection)
            assert {"joined_event_id", "left_event_id"} <= columns
            assert types == {"party_member_joined", "party_member_left"}
        downgraded = _alembic(test_url, "downgrade", "120_party_definition")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            columns, types = _state(connection)
            assert "joined_event_id" not in columns and types == set()
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
