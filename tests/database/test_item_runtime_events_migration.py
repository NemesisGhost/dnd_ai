"""Migration 133 (item runtime event types): round trip on a throwaway database."""

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

CODES = (
    "item_equipped",
    "item_unequipped",
    "item_consumed",
    "item_damaged",
    "item_repaired",
    "item_attuned",
    "item_attunement_ended",
)


def _present(connection) -> int:  # type: ignore[no-untyped-def]
    return int(
        connection.execute(
            text("SELECT count(*) FROM narrative.event_types WHERE code = ANY(:codes)"),
            {"codes": list(CODES)},
        ).scalar()
        or 0
    )


def test_upgrade_downgrade_and_reupgrade() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "132_item_definition_authoring")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert _present(connection) == 0
        _alembic_upgrade(test_url, "133_item_runtime_events")
        with engine.connect() as connection:
            assert _present(connection) == len(CODES)
        downgraded = _alembic(test_url, "downgrade", "132_item_definition_authoring")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert _present(connection) == 0
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
