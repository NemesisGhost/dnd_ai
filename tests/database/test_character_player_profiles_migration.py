"""Migration 147 (P03-A A5a): campaign player-profile storage, on throwaway databases.

A populated upgrade from 146 (an existing character has no profile afterwards, the lookup holds the
eleven D13 fields), the guarded downgrade (it refuses and changes nothing while any head or version
row exists, and drops everything on an empty store), a re-upgrade, and `alembic check` for drift
between the migration and the SQLAlchemy metadata.
"""

import uuid

import pytest
from sqlalchemy import Connection, create_engine, text

from dnd_ai.domain.player_profiles import (
    COPY_ELIGIBLE_PLAYER_PROFILE_FIELDS,
    PLAYER_PROFILE_FIELD_LABELS,
    PLAYER_PROFILE_FIELDS,
)
from tests.database.test_organization_hierarchy_migration import _alembic
from tests.database.test_phase8_populated_upgrade import (
    _alembic_upgrade,
    _connect_args,
    _drop_database,
    _provision_database,
)
from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_character,
    make_membership_role,
    make_timeline,
    make_user,
    make_world,
)
from tests.player_profile_support import seed_player_profile

pytestmark = pytest.mark.database

PARENT = "146_public_profile_identity"
TARGET = "147_character_player_profiles"
_TABLES = (
    "campaign.player_profile_fields",
    "campaign.character_player_profiles",
    "campaign.character_player_profile_versions",
)
_FUNCTIONS = (
    "enforce_player_profile_scope",
    "enforce_player_profile_version_matches_head",
    "enforce_player_profile_head_has_version",
    "enforce_player_profile_version_immutable",
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
            world = make_world(connection, slug=f"pp-mig-{uuid.uuid4().hex[:8]}")
            timeline = make_timeline(connection, world, is_primary=True)
            campaign = make_campaign(
                connection, timeline, "Profile Migration", lifecycle_status_code="active"
            )
            character = make_character(connection, world, name="Existing Character")
            user = make_user(connection, "Profile Migration Editor")
            membership = make_campaign_membership(connection, campaign, user)
            owner_role = connection.execute(
                text(
                    "SELECT role_id FROM security.roles WHERE code = 'campaign_owner' "
                    "AND campaign_id IS NULL"
                )
            ).scalar_one()
            make_membership_role(connection, membership, owner_role)

        _alembic_upgrade(test_url, TARGET)
        with engine.begin() as connection:
            assert all(_present(connection, table) for table in _TABLES)
            assert _function_count(connection) == len(_FUNCTIONS)
            # No backfill: the existing character has no profile; the lookup holds the 11 fields.
            for table in _TABLES[1:]:
                count = connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608
                assert count == 0
            rows = connection.execute(
                text(
                    "SELECT code, display_name, is_copy_eligible FROM campaign.player_profile_fields "
                    "ORDER BY sort_order"
                )
            ).all()
            assert [row.code for row in rows] == list(PLAYER_PROFILE_FIELDS)
            assert {row.code: row.display_name for row in rows} == PLAYER_PROFILE_FIELD_LABELS
            assert {row.code for row in rows if row.is_copy_eligible} == set(
                COPY_ELIGIBLE_PLAYER_PROFILE_FIELDS
            )

        # The guard: with a profile present the downgrade refuses and changes nothing.
        seed_player_profile(
            engine,
            campaign_id=campaign,
            character_id=character,
            editor_membership_id=membership,
            fields={"personality": "Keeps promises"},
        )
        refused = _alembic(test_url, "downgrade", PARENT)
        assert refused.returncode != 0
        with engine.connect() as connection:
            assert _revision(connection) == TARGET
            assert all(_present(connection, table) for table in _TABLES)
            assert _function_count(connection) == len(_FUNCTIONS)
            assert (
                connection.execute(
                    text("SELECT count(*) FROM campaign.character_player_profile_versions")
                ).scalar_one()
                == 1
            )
            assert (
                connection.execute(
                    text("SELECT count(*) FROM campaign.character_player_profiles")
                ).scalar_one()
                == 1
            )
        # The refusal names no profile text.
        assert "Keeps promises" not in refused.stdout + refused.stderr

        # An empty store downgrades (the fixture rows are removed as the superuser, bypassing the
        # append-only trigger the way no application role can).
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            connection.execute(text("DELETE FROM campaign.character_player_profile_versions"))
            connection.execute(text("DELETE FROM campaign.character_player_profiles"))
        downgraded = _alembic(test_url, "downgrade", PARENT)
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert _revision(connection) == PARENT
            assert not any(_present(connection, table) for table in _TABLES)
            assert _function_count(connection) == 0
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


def test_a_fresh_database_upgrades_to_head_with_no_drift() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "head")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.connect() as connection:
            assert all(_present(connection, table) for table in _TABLES)
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
