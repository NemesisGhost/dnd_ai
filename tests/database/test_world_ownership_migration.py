"""Single-step upgrade/downgrade/re-upgrade coverage for revision
`105_world_ownership_scope` (ADR 0014).

The critical property this migration must get right against a *populated*
database: a world created before this revision ran must not have its
ownership guessed. Every pre-existing `core.worlds` row is backfilled onto
one explicit, zero-membership legacy ownership scope
("Legacy Self-Hosted Worlds (unclaimed)") rather than being assigned to
whichever user happens to exist first — these tests prove that behavior
directly against a real populated-then-migrated database, not just against
a fresh empty one (which `tests/database/test_seed_idempotency.py` and the
ordinary full-suite migration run already cover for the "does it apply at
all" question).

Each test provisions its own disposable, throwaway database — never the
shared session-scoped `postgres_engine` every other test in this suite
reuses, since running `alembic downgrade`/`upgrade` as a subprocess against
a URL mutates that database's actual migration state — mirroring
`tests/database/test_login_failure_audit_action_migration.py`'s established
per-file pattern for a migration-scoped up/down proof.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, make_url, text

pytestmark = pytest.mark.database

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "database" / "alembic.ini"

_PREVIOUS_REVISION = "104_audit_history_indexes"
_THIS_REVISION = "105_world_ownership_scope"
_LEGACY_OWNERSHIP_SCOPE_NAME = "Legacy Self-Hosted Worlds (unclaimed)"

# Matches tests/conftest.py's _MIGRATION_SUBPROCESS_TIMEOUT_SECONDS.
_ALEMBIC_SUBPROCESS_TIMEOUT_SECONDS = 300

# Matches tests/conftest.py's _DB_CONNECT_TIMEOUT_SECONDS.
_CONNECT_TIMEOUT_SECONDS = 10


def _connect_args() -> dict[str, object]:
    return {"connect_timeout": _CONNECT_TIMEOUT_SECONDS}


def _require_admin_url() -> str:
    admin_url_raw = os.environ.get("DATABASE_URL")
    if not admin_url_raw:
        pytest.skip(
            "DATABASE_URL is not set — these tests provision their own throwaway "
            "database and need an admin/bootstrap connection, same precondition as "
            "tests/conftest.py::postgres_engine."
        )
    return admin_url_raw


def _provision_database(label: str) -> tuple[str, str]:
    """Creates a fresh, unmigrated throwaway database. Returns (admin_url, test_url)."""
    admin_url = make_url(_require_admin_url())
    db_name = f"dnd_ai_105_{label}_{uuid.uuid4().hex[:12]}"
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


def _alembic_upgrade(database_url: str, target: str) -> None:
    result = _alembic(database_url, "upgrade", target)
    assert result.returncode == 0, result.stdout + result.stderr


def _current_revision(database_url: str) -> str:
    result = _alembic(database_url, "current")
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert lines, f"alembic current produced no output: {result.stdout!r}"
    return lines[-1].split()[0]


def _insert_pre_migration_world(database_url: str, *, slug: str) -> uuid.UUID:
    """Inserts a `core.worlds` row the way every world was created before
    this revision — no `ownership_scope_id` column exists yet at
    `_PREVIOUS_REVISION`."""
    engine = create_engine(database_url, connect_args=_connect_args())
    try:
        with engine.begin() as conn:
            world_id = conn.execute(
                text("""
                    INSERT INTO core.worlds (name, slug, lifecycle_status_id)
                    VALUES (
                        'Pre-existing World', :slug,
                        (SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active')
                    )
                    RETURNING world_id
                """),
                {"slug": slug},
            ).scalar_one()
    finally:
        engine.dispose()
    assert isinstance(world_id, uuid.UUID)
    return world_id


def test_upgrading_to_105_backfills_pre_existing_world_onto_unowned_legacy_scope() -> None:
    """The core regression this file exists to catch: a world that existed
    before ownership scopes did must land on one explicit, documented
    legacy scope with zero memberships — never a guessed owner."""
    admin_url, test_url = _provision_database("backfill")
    try:
        _alembic_upgrade(test_url, _PREVIOUS_REVISION)
        world_id = _insert_pre_migration_world(test_url, slug="pre-existing-world")

        _alembic_upgrade(test_url, _THIS_REVISION)

        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            with engine.connect() as conn:
                row = (
                    conn.execute(
                        text("""
                            SELECT os.ownership_scope_id, os.name
                            FROM core.worlds w
                            JOIN security.ownership_scopes os
                                ON os.ownership_scope_id = w.ownership_scope_id
                            WHERE w.world_id = :world_id
                        """),
                        {"world_id": world_id},
                    )
                    .mappings()
                    .one()
                )
                member_count = conn.execute(
                    text(
                        "SELECT count(*) FROM security.ownership_scope_memberships "
                        "WHERE ownership_scope_id = :scope"
                    ),
                    {"scope": row["ownership_scope_id"]},
                ).scalar_one()
        finally:
            engine.dispose()

        assert row["name"] == _LEGACY_OWNERSHIP_SCOPE_NAME
        assert member_count == 0
    finally:
        _drop_database(admin_url, test_url)


def test_downgrade_then_reupgrade_round_trips_cleanly() -> None:
    """Upgrade from the previous revision, downgrade back to it, and
    re-upgrade — including a pre-existing world, so the downgrade's
    restored global `ux_worlds_slug` and the re-upgrade's fresh backfill
    are both exercised against real data, not an empty schema."""
    admin_url, test_url = _provision_database("roundtrip")
    try:
        _alembic_upgrade(test_url, _PREVIOUS_REVISION)
        world_id = _insert_pre_migration_world(test_url, slug="roundtrip-world")

        _alembic_upgrade(test_url, _THIS_REVISION)
        assert _current_revision(test_url) == _THIS_REVISION

        downgrade_result = _alembic(test_url, "downgrade", _PREVIOUS_REVISION)
        assert downgrade_result.returncode == 0, downgrade_result.stdout + downgrade_result.stderr
        assert _current_revision(test_url) == _PREVIOUS_REVISION

        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            with engine.connect() as conn:
                slug = conn.execute(
                    text("SELECT slug FROM core.worlds WHERE world_id = :world_id"),
                    {"world_id": world_id},
                ).scalar_one()
        finally:
            engine.dispose()
        assert slug == "roundtrip-world"

        _alembic_upgrade(test_url, _THIS_REVISION)
        assert _current_revision(test_url) == _THIS_REVISION

        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            with engine.connect() as conn:
                ownership_scope_id = conn.execute(
                    text("SELECT ownership_scope_id FROM core.worlds WHERE world_id = :world_id"),
                    {"world_id": world_id},
                ).scalar_one()
        finally:
            engine.dispose()
        assert ownership_scope_id is not None
    finally:
        _drop_database(admin_url, test_url)
