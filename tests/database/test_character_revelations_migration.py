"""Migration 145 (P03-A A3a): character revelations, the audience snapshot, the
`character.view_public_profile` capability and `public_summary`.

Runs on throwaway databases: a populated upgrade (nothing existing changes and nobody has a
revelation), the downgrade guard that refuses atomically while the new capability is named by a
role capability, the documented lossy downgrade, a re-upgrade, and `alembic check`.
"""

import pytest
from sqlalchemy import Connection, create_engine, text

from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_organization_hierarchy_migration import _alembic
from tests.database.test_phase8_populated_upgrade import (
    _alembic_upgrade,
    _connect_args,
    _drop_database,
    _provision_database,
)
from tests.factories import make_user

pytestmark = pytest.mark.database

PARENT = "144_profile_provenance_guard"
TARGET = "145_character_revelations"
_TABLES = (
    "security.revelation_audience_kinds",
    "security.character_revelations",
    "security.character_revelation_members",
)
_CAPABILITY = "character.view_public_profile"


def _present(connection: Connection, table: str) -> bool:
    return connection.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar() is not None


def _summary_columns(connection: Connection) -> int:
    return int(
        connection.execute(
            text(
                "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'campaign' "
                "AND table_name IN ('character_public_profiles', "
                "'character_public_profile_releases') AND column_name = 'public_summary'"
            )
        ).scalar_one()
    )


def _capability_present(connection: Connection) -> bool:
    return bool(
        connection.execute(
            text("SELECT count(*) FROM security.capabilities WHERE code = :c"),
            {"c": _CAPABILITY},
        ).scalar()
    )


def _revision(connection: Connection) -> str:
    return str(
        connection.execute(text("SELECT version_num FROM core.alembic_version")).scalar_one()
    )


def test_populated_upgrade_guarded_downgrade_and_reupgrade() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, PARENT)
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.begin() as connection:
            assert not any(_present(connection, table) for table in _TABLES)
            assert _summary_columns(connection) == 0 and not _capability_present(connection)
            owner = make_user(connection, "Revelation Migration Owner")
            world = make_authored_world(connection, owner_user_id=owner, name="Revelation World")
            make_authored_campaign(connection, world, name="Revelation Campaign")
        _alembic_upgrade(test_url, TARGET)
        with engine.begin() as connection:
            assert all(_present(connection, table) for table in _TABLES)
            assert _summary_columns(connection) == 2 and _capability_present(connection)
            kinds = set(
                connection.execute(
                    text("SELECT code FROM security.revelation_audience_kinds")
                ).scalars()
            )
            assert kinds == {
                "member",
                "access_group",
                "campaign_current",
                "campaign_current_and_future",
            }
            for table in _TABLES[1:]:
                assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0  # noqa: S608

        # The downgrade refuses, and changes nothing, while a role capability names the new code.
        with engine.begin() as connection:
            role = connection.execute(
                text(
                    "SELECT role_id FROM security.roles WHERE code = 'player' AND campaign_id IS NULL"
                )
            ).scalar_one()
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            connection.execute(
                text(
                    "INSERT INTO security.role_capabilities (role_id, capability_id) "
                    "SELECT :r, capability_id FROM security.capabilities WHERE code = :c"
                ),
                {"r": role, "c": _CAPABILITY},
            )
        refused = _alembic(test_url, "downgrade", PARENT)
        assert refused.returncode != 0
        assert "Refusing to downgrade 145_character_revelations" in refused.stderr + refused.stdout
        with engine.begin() as connection:
            assert _revision(connection) == TARGET
            assert all(_present(connection, table) for table in _TABLES)
            assert _summary_columns(connection) == 2 and _capability_present(connection)
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            connection.execute(
                text(
                    "DELETE FROM security.role_capabilities WHERE capability_id = "
                    "(SELECT capability_id FROM security.capabilities WHERE code = :c)"
                ),
                {"c": _CAPABILITY},
            )

        downgraded = _alembic(test_url, "downgrade", PARENT)
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.begin() as connection:
            assert _revision(connection) == PARENT
            assert not any(_present(connection, table) for table in _TABLES)
            assert _summary_columns(connection) == 0 and not _capability_present(connection)
            assert (
                connection.execute(
                    text("SELECT count(*) FROM pg_proc WHERE proname LIKE '%character_revelation%'")
                ).scalar_one()
                == 0
            )
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
