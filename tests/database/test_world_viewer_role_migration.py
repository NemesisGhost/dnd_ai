"""Revision 136: the `world_viewer` world role
(docs/adr/0019-world-visibility-and-viewer-role.md)."""

import uuid

import pytest
from sqlalchemy import Connection, create_engine, text

from tests.database.test_organization_hierarchy_migration import _alembic
from tests.database.test_phase8_populated_upgrade import (
    _alembic_upgrade,
    _connect_args,
    _drop_database,
    _provision_database,
)
from tests.factories import make_user, make_world

pytestmark = pytest.mark.database

BEFORE = "135_scrub_narrative_text"
REVISION = "136_world_viewer_role"


def test_world_viewer_is_seeded_active_after_world_owner(db_connection: Connection) -> None:
    rows = db_connection.execute(
        text(
            "SELECT code, display_name, sort_order, is_active FROM security.world_roles "
            "WHERE code IN ('world_owner', 'world_viewer') ORDER BY sort_order"
        )
    ).all()
    assert [tuple(row) for row in rows] == [
        ("world_owner", "World owner", 10, True),
        ("world_viewer", "World viewer", 20, True),
    ]


def test_a_world_viewer_alone_does_not_satisfy_the_owner_guarantee(
    db_connection: Connection,
) -> None:
    """A viewer row never counts as an owner for `security.world_has_active_owner`."""
    world_id = make_world(db_connection, f"viewer-only-{uuid.uuid4().hex[:8]}")
    db_connection.execute(
        text("""
            INSERT INTO security.world_memberships
                (world_id, user_id, world_role_id, membership_status_id)
            VALUES (:w, :u,
                    (SELECT world_role_id FROM security.world_roles WHERE code = 'world_viewer'),
                    (SELECT membership_status_id FROM security.membership_statuses
                     WHERE code = 'active'))
        """),
        {"w": world_id, "u": make_user(db_connection)},
    )
    assert (
        db_connection.execute(
            text("SELECT security.world_has_active_owner(:w)"), {"w": world_id}
        ).scalar()
        is False
    )


def test_downgrade_removes_viewer_rows_and_the_role_and_upgrade_restores_it() -> None:
    admin_url, test_url = _provision_database()
    engine = create_engine(test_url, connect_args=_connect_args())
    try:
        _alembic_upgrade(test_url, REVISION)
        with engine.begin() as conn:
            world_id = make_world(conn, "viewer-round-trip")
            conn.execute(
                text("""
                    INSERT INTO security.world_memberships
                        (world_id, user_id, world_role_id, membership_status_id)
                    VALUES (:w, :u,
                            (SELECT world_role_id FROM security.world_roles
                             WHERE code = 'world_viewer'),
                            (SELECT membership_status_id FROM security.membership_statuses
                             WHERE code = 'active'))
                """),
                {"w": world_id, "u": make_user(conn)},
            )

        downgraded = _alembic(test_url, "downgrade", BEFORE)
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as conn:
            assert (
                conn.execute(text("SELECT count(*) FROM security.world_memberships")).scalar() == 0
            )
            assert [
                code for (code,) in conn.execute(text("SELECT code FROM security.world_roles"))
            ] == ["world_owner"]

        _alembic_upgrade(test_url, REVISION)
        with engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM security.world_roles WHERE code = 'world_viewer'")
                ).scalar()
                == 1
            )
    finally:
        engine.dispose()
        _drop_database(admin_url, test_url)
