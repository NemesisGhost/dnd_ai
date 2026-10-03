"""Upgrade/downgrade/re-upgrade coverage for revision `109_user_portal_preferences`.

Each test provisions its own throwaway database (never the shared
session-scoped engine), mirroring
`test_login_failure_audit_action_migration.py`'s per-file pattern: running
`alembic downgrade`/`upgrade` against a URL mutates that database's migration
state.

Table-level behavior (unique `user_id`, `updated_at` trigger, no authorization
columns) is exercised against the shared migrated database in
`test_user_portal_preferences_schema` below.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import Connection, create_engine, make_url, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.database

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "database" / "alembic.ini"

_PREVIOUS_REVISION = "108_ios_consumed_by_index"
_THIS_REVISION = "109_user_portal_preferences"
_ALEMBIC_SUBPROCESS_TIMEOUT_SECONDS = 300
_CONNECT_TIMEOUT_SECONDS = 10


def _connect_args() -> dict[str, object]:
    return {"connect_timeout": _CONNECT_TIMEOUT_SECONDS}


def _require_admin_url() -> str:
    admin_url_raw = os.environ.get("DATABASE_URL")
    if not admin_url_raw:
        pytest.skip(
            "DATABASE_URL is not set — these tests provision their own throwaway "
            "database and need an admin/bootstrap connection."
        )
    return admin_url_raw


def _provision_database(label: str) -> tuple[str, str]:
    admin_url = make_url(_require_admin_url())
    db_name = f"dnd_ai_109_{label}_{uuid.uuid4().hex[:12]}"
    test_url = admin_url.set(database=db_name)
    admin_engine = create_engine(
        admin_url, isolation_level="AUTOCOMMIT", connect_args=_connect_args()
    )
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()
    return (
        admin_url.render_as_string(hide_password=False),
        test_url.render_as_string(hide_password=False),
    )


def _drop_database(admin_url: str, test_url: str) -> None:
    db_name = make_url(test_url).database
    admin_engine = create_engine(
        make_url(admin_url), isolation_level="AUTOCOMMIT", connect_args=_connect_args()
    )
    with admin_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
    admin_engine.dispose()


def _alembic(database_url: str, *args: str) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args],
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        timeout=_ALEMBIC_SUBPROCESS_TIMEOUT_SECONDS,
    )


def _alembic_ok(database_url: str, *args: str) -> None:
    result = _alembic(database_url, *args)
    assert result.returncode == 0, result.stdout + result.stderr


def _current_revision(database_url: str) -> str:
    result = _alembic(database_url, "current")
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines[-1].split()[0]


def _table_exists(database_url: str) -> bool:
    engine = create_engine(database_url, connect_args=_connect_args())
    try:
        with engine.connect() as conn:
            return bool(
                conn.execute(
                    text("SELECT to_regclass('security.user_portal_preferences') IS NOT NULL")
                ).scalar_one()
            )
    finally:
        engine.dispose()


def test_upgrade_downgrade_and_reupgrade_round_trip() -> None:
    admin_url, test_url = _provision_database("roundtrip")
    try:
        _alembic_ok(test_url, "upgrade", _PREVIOUS_REVISION)
        assert not _table_exists(test_url)

        _alembic_ok(test_url, "upgrade", _THIS_REVISION)
        assert _current_revision(test_url) == _THIS_REVISION
        assert _table_exists(test_url)

        _alembic_ok(test_url, "downgrade", _PREVIOUS_REVISION)
        assert _current_revision(test_url) == _PREVIOUS_REVISION
        assert not _table_exists(test_url)

        _alembic_ok(test_url, "upgrade", _THIS_REVISION)
        assert _table_exists(test_url)
    finally:
        _drop_database(admin_url, test_url)


def _insert_user(conn: Connection) -> uuid.UUID:
    user_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO security.users (user_id, display_name, lifecycle_status_id) "
            "VALUES (:uid, 'Pref Tester', "
            "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active'))"
        ),
        {"uid": user_id},
    )
    return user_id


def test_user_portal_preferences_schema(db_connection: Connection) -> None:
    user_id = _insert_user(db_connection)
    db_connection.execute(
        text("INSERT INTO security.user_portal_preferences (user_id) VALUES (:uid)"),
        {"uid": user_id},
    )
    row = (
        db_connection.execute(
            text(
                "SELECT preferred_campaign_id, last_visited_campaign_id, created_at "
                "FROM security.user_portal_preferences WHERE user_id = :uid"
            ),
            {"uid": user_id},
        )
        .mappings()
        .one()
    )
    assert row["preferred_campaign_id"] is None
    assert row["last_visited_campaign_id"] is None

    # updated_at trigger advances (now() is transaction-stable, so force a
    # distinct value first and assert the trigger overwrote it).
    db_connection.execute(
        text(
            "UPDATE security.user_portal_preferences SET updated_at = '2000-01-01' "
            "WHERE user_id = :uid"
        ),
        {"uid": user_id},
    )
    db_connection.execute(
        text(
            "UPDATE security.user_portal_preferences SET preferred_campaign_id = NULL "
            "WHERE user_id = :uid"
        ),
        {"uid": user_id},
    )
    bumped = db_connection.execute(
        text(
            "SELECT updated_at > '2000-01-01' FROM security.user_portal_preferences "
            "WHERE user_id = :uid"
        ),
        {"uid": user_id},
    ).scalar_one()
    assert bumped is True

    # At most one row per user.
    nested = db_connection.begin_nested()
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text("INSERT INTO security.user_portal_preferences (user_id) VALUES (:uid)"),
            {"uid": user_id},
        )
    nested.rollback()


def test_user_portal_preferences_has_only_non_authorization_columns(
    db_connection: Connection,
) -> None:
    columns = set(
        db_connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'security' AND table_name = 'user_portal_preferences'"
            )
        )
        .scalars()
        .all()
    )
    assert columns == {
        "user_portal_preference_id",
        "user_id",
        "preferred_campaign_id",
        "last_visited_campaign_id",
        "created_at",
        "updated_at",
    }
