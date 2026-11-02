"""Migration 134 (entity source links): round trip on a throwaway database."""

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

CODES = ("published_reference", "homebrew_document", "session_notes")


def _state(connection) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    table = connection.execute(
        text(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core' "
            "AND table_name = 'entity_source_links'"
        )
    ).scalar()
    types = connection.execute(
        text("SELECT count(*) FROM core.source_types WHERE code = ANY(:codes)"),
        {"codes": list(CODES)},
    ).scalar()
    return int(table or 0), int(types or 0)


def test_upgrade_downgrade_and_reupgrade() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "133_item_runtime_events")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert _state(connection) == (0, 0)
        _alembic_upgrade(test_url, "134_entity_source_links")
        with engine.connect() as connection:
            assert _state(connection) == (1, 3)
        downgraded = _alembic(test_url, "downgrade", "133_item_runtime_events")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert _state(connection) == (0, 0)
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
