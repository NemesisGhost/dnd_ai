"""Migration 139 (CP-6): the `character.view_inventory` capability and its relationship defaults.

Both checks provision a throwaway database, never the shared one.
"""

import pytest
from sqlalchemy import Connection, create_engine, text

from dnd_ai.domain.access import BUILTIN_RELATIONSHIP_CAPABILITIES
from tests.database.test_organization_hierarchy_migration import _alembic
from tests.database.test_phase8_populated_upgrade import (
    _alembic_upgrade,
    _connect_args,
    _drop_database,
    _provision_database,
)
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_resource_grant,
    make_timeline,
    make_user,
    make_world,
)

pytestmark = pytest.mark.database

_INVENTORY = "character.view_inventory"


def _pairs(connection: Connection, capability: str) -> set[str]:
    rows = connection.execute(
        text("""
            SELECT rt.code
            FROM security.character_relationship_type_capabilities rtc
            JOIN security.character_relationship_types rt
              ON rt.character_relationship_type_id = rtc.character_relationship_type_id
            JOIN security.capabilities cap ON cap.capability_id = rtc.capability_id
            WHERE cap.code = :c
        """),
        {"c": capability},
    ).scalars()
    return {str(r) for r in rows}


def _capability_exists(connection: Connection) -> bool:
    return bool(
        connection.execute(
            text("SELECT 1 FROM security.capabilities WHERE code = :c"), {"c": _INVENTORY}
        ).scalar()
    )


def test_upgrade_reconciles_and_downgrade_removes_the_capability_with_its_grants() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "138_world_roles_and_use_grants")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.begin() as connection:
            assert not _capability_exists(connection)
            # A developer database that hand-added the capability and mapped it to a type the
            # matrix excludes (and to a custom type, which is left alone).
            connection.execute(
                text("""
                    INSERT INTO security.capabilities (code, display_name, sort_order)
                    VALUES (:c, 'Hand added', 1)
                """),
                {"c": _INVENTORY},
            )
            connection.execute(
                text("""
                    INSERT INTO security.character_relationship_type_capabilities
                        (character_relationship_type_id, capability_id)
                    SELECT rt.character_relationship_type_id, cap.capability_id
                    FROM security.character_relationship_types rt, security.capabilities cap
                    WHERE rt.code = 'former_controller' AND cap.code = :c
                """),
                {"c": _INVENTORY},
            )

        _alembic_upgrade(test_url, "139_inventory_capability")
        with engine.connect() as connection:
            assert _pairs(connection, _INVENTORY) == {
                t for t, caps in BUILTIN_RELATIONSHIP_CAPABILITIES.items() if _INVENTORY in caps
            }
            assert "former_controller" not in _pairs(connection, _INVENTORY)
            # An existing row is kept as it was (ON CONFLICT DO NOTHING), not rewritten.
            name = connection.execute(
                text("SELECT display_name FROM security.capabilities WHERE code = :c"),
                {"c": _INVENTORY},
            ).scalar()
            assert name == "Hand added"

        # A grant, a deny and an unrelated grant, then the lossy downgrade.
        with engine.begin() as connection:
            world = make_world(connection, slug="cp6-migration")
            timeline = make_timeline(connection, world, is_primary=True)
            campaign = make_campaign(connection, timeline, lifecycle_status_code="pending")
            character = make_character(connection, world, name="Aria")
            member = make_campaign_membership(connection, campaign, make_user(connection, "P"))
            for capability, effect in (
                (_INVENTORY, "allow"),
                (_INVENTORY, "deny"),
                ("character.view_full", "allow"),
            ):
                make_resource_grant(
                    connection,
                    campaign,
                    lookup_id(connection, "security", "capabilities", "capability_id", capability),
                    character_id=character,
                    grantee_campaign_membership_id=member,
                    effect=effect,
                    revoked=capability == _INVENTORY and effect == "allow",
                )

        downgraded = _alembic(test_url, "downgrade", "138_world_roles_and_use_grants")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert not _capability_exists(connection)
            assert _pairs(connection, _INVENTORY) == set()
            remaining = connection.execute(
                text("""
                    SELECT cap.code FROM security.resource_grants rg
                    JOIN security.capabilities cap ON cap.capability_id = rg.capability_id
                """)
            ).scalars()
            assert [str(c) for c in remaining] == ["character.view_full"]

        _alembic_upgrade(test_url, "head")
        with engine.connect() as connection:
            assert _pairs(connection, _INVENTORY) == {
                t for t, caps in BUILTIN_RELATIONSHIP_CAPABILITIES.items() if _INVENTORY in caps
            }
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def test_a_fresh_database_holds_the_capability_for_the_approved_types() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "head")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT display_name, is_active FROM security.capabilities WHERE code = :c"),
                {"c": _INVENTORY},
            ).one()
            assert (row.display_name, row.is_active) == ("View inventory", True)
            assert _pairs(connection, _INVENTORY) == {
                "owner",
                "primary_controller",
                "co_controller",
                "portrayer",
                "viewer",
                "observer_approved_viewer",
            }
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def test_the_code_capability_catalog_names_only_database_capabilities(
    db_connection: Connection,
) -> None:
    from dnd_ai.domain.access import (
        BUILTIN_RELATIONSHIP_CAPABILITIES,
        CHARACTER_TARGET_CAPABILITY_CODES,
    )

    stored = {
        str(c)
        for c in db_connection.execute(text("SELECT code FROM security.capabilities")).scalars()
    }
    assert stored >= CHARACTER_TARGET_CAPABILITY_CODES
    assert {c for caps in BUILTIN_RELATIONSHIP_CAPABILITIES.values() for c in caps} <= stored
    assert _INVENTORY in CHARACTER_TARGET_CAPABILITY_CODES
