"""Migration 132 (item definition authoring): seeds, world scope and round trip."""

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


def _definitions(connection) -> int:  # type: ignore[no-untyped-def]
    return int(
        connection.execute(text("SELECT count(*) FROM rules.item_definitions")).scalar() or 0
    )


def _has_owning_world(connection) -> bool:  # type: ignore[no-untyped-def]
    return bool(
        connection.execute(
            text(
                "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'rules' "
                "AND table_name = 'item_definitions' AND column_name = 'owning_world_id'"
            )
        ).scalar()
    )


def test_upgrade_seeds_downgrade_removes_and_reupgrade_restores() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "131_npc_portrayal")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert _definitions(connection) == 0 and not _has_owning_world(connection)
        _alembic_upgrade(test_url, "132_item_definition_authoring")
        with engine.connect() as connection:
            assert _has_owning_world(connection)
            seeded = _definitions(connection)
            assert seeded >= 20
            ruleset_wide = connection.execute(
                text(
                    "SELECT count(*) FROM rules.item_definitions "
                    "WHERE owning_world_id IS NULL AND canon_status_id = "
                    "(SELECT canon_status_id FROM core.canon_statuses WHERE code = 'canon')"
                )
            ).scalar()
            assert ruleset_wide == seeded
        downgraded = _alembic(test_url, "downgrade", "131_npc_portrayal")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert _definitions(connection) == 0 and not _has_owning_world(connection)
        _alembic_upgrade(test_url, "head")
        with engine.connect() as connection:
            assert _definitions(connection) == seeded
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
