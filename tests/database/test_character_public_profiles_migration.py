"""Migration 142 (P03-A A2a): campaign-scoped public-profile drafts and immutable releases.

Runs on throwaway databases: a populated upgrade (an existing character has no draft and no
release afterwards), the documented lossy downgrade, a re-upgrade, and `alembic check` for drift
between the migration and the SQLAlchemy metadata.
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
from tests.factories import make_character, make_user

pytestmark = pytest.mark.database

_TABLES = (
    "campaign.public_profile_field_origins",
    "campaign.character_public_profiles",
    "campaign.character_public_profile_releases",
)
_FUNCTIONS = (
    "enforce_public_profile_scope",
    "enforce_public_profile_field_origins",
    "enforce_public_profile_release_immutable",
)


def _present(connection: Connection, table: str) -> bool:
    return connection.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar() is not None


def _function_count(connection: Connection) -> int:
    return int(
        connection.execute(
            text("SELECT count(*) FROM pg_proc WHERE proname = ANY(:names)"),
            {"names": list(_FUNCTIONS)},
        ).scalar()
        or 0
    )


def test_populated_upgrade_and_documented_downgrade() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "141_character_reveal_delegations")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.begin() as connection:
            assert not any(_present(connection, table) for table in _TABLES)
            owner = make_user(connection, "Profile Migration Owner")
            world = make_authored_world(connection, owner_user_id=owner, name="Profile World")
            make_authored_campaign(connection, world, name="Profile Campaign")
            character = make_character(connection, world.world_id, name="Existing Character")
        _alembic_upgrade(test_url, "142_character_public_profiles")
        with engine.begin() as connection:
            assert all(_present(connection, table) for table in _TABLES)
            assert _function_count(connection) == 3
            # No backfill: the existing character has no draft and no release.
            for table in _TABLES[1:]:
                assert (
                    connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0  # noqa: S608
                )
            origins = set(
                connection.execute(
                    text("SELECT code FROM campaign.public_profile_field_origins")
                ).scalars()
            )
            assert origins == {"authored", "legacy_appearance", "legacy_background"}
        downgraded = _alembic(test_url, "downgrade", "141_character_reveal_delegations")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.begin() as connection:
            assert not any(_present(connection, table) for table in _TABLES)
            assert _function_count(connection) == 0
            # Nothing else is lost: the character stays.
            assert (
                connection.execute(
                    text("SELECT count(*) FROM character.characters WHERE character_id = :c"),
                    {"c": character},
                ).scalar_one()
                == 1
            )
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def test_a_fresh_database_upgrades_to_head_with_the_tables_and_no_drift() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "head")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert all(_present(connection, table) for table in _TABLES)
            columns = set(
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'campaign' "
                        "AND table_name = 'character_public_profile_releases'"
                    )
                ).scalars()
            )
            assert {
                "character_public_profile_release_id",
                "character_public_profile_id",
                "campaign_id",
                "character_id",
                "version_number",
                "from_draft_row_version",
                "public_appearance",
                "public_background",
                "authority_source_code",
                "character_reveal_delegation_id",
                "released_by_membership_id",
                "released_at",
                "release_note",
            } <= columns
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
