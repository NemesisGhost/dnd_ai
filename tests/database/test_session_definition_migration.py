"""Migration 122 (session versioning and scheduling): populated round trip on a throwaway database."""

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


def _columns(connection) -> set[str]:  # type: ignore[no-untyped-def]
    return {
        str(c)
        for c in connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'campaign' AND table_name = 'sessions'"
            )
        ).scalars()
    }


def test_existing_sessions_get_version_one_and_the_round_trip_is_clean() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "121_party_membership_events")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.begin() as connection:
            # Seed legacy rows without the access-manager commit guard (throwaway database).
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            active = connection.execute(
                text(
                    "SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active'"
                )
            ).scalar()
            ruleset_version = connection.execute(
                text("SELECT ruleset_version_id FROM rules.ruleset_versions LIMIT 1")
            ).scalar()
            world = connection.execute(
                text(
                    "INSERT INTO core.worlds (name, slug, lifecycle_status_id) "
                    "VALUES ('Old World', 'old-world', :a) RETURNING world_id"
                ),
                {"a": active},
            ).scalar()
            connection.execute(
                text(
                    "INSERT INTO rules.world_rulesets (world_id, ruleset_id) "
                    "SELECT :w, ruleset_id FROM rules.ruleset_versions WHERE ruleset_version_id = :v"
                ),
                {"w": world, "v": ruleset_version},
            )
            timeline = connection.execute(
                text(
                    "INSERT INTO campaign.timelines (world_id, name, is_primary, lifecycle_status_id) "
                    "VALUES (:w, 'Main', true, :a) RETURNING timeline_id"
                ),
                {"w": world, "a": active},
            ).scalar()
            campaign = connection.execute(
                text(
                    "INSERT INTO campaign.campaigns "
                    "(timeline_id, name, lifecycle_status_id, ruleset_version_id) "
                    "VALUES (:t, 'Old', :a, :v) RETURNING campaign_id"
                ),
                {"t": timeline, "a": active, "v": ruleset_version},
            ).scalar()
            connection.execute(
                text(
                    "INSERT INTO campaign.sessions (campaign_id, session_number, lifecycle_status_id) "
                    "VALUES (:c, 1, :a)"
                ),
                {"c": campaign, "a": active},
            )
            assert "row_version" not in _columns(connection)
        _alembic_upgrade(test_url, "122_session_definition")
        with engine.connect() as connection:
            assert {"row_version", "scheduled_for", "archived_at", "created_by_user_id"} <= (
                _columns(connection)
            )
            row = connection.execute(
                text(
                    "SELECT row_version, scheduled_for, archived_at, created_by_user_id "
                    "FROM campaign.sessions"
                )
            ).one()
            assert tuple(row) == (1, None, None, None)
        downgraded = _alembic(test_url, "downgrade", "121_party_membership_events")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert "row_version" not in _columns(connection)
        _alembic_upgrade(test_url, "head")
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
