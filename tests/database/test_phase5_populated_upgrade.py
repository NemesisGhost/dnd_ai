"""Populated-upgrade proof for campaign.character_location_history's
location_period backfill (PHASE5_REMAINING_ISSUES.md item 3, revision 052).

Every other test in tests/database runs against the shared session-scoped
database, which is already migrated straight to head — it can never prove
anything about what happens to a database that had real rows *before*
revision 052's backfill exists to catch them. This file provisions its own
throwaway database so it can pause mid-upgrade at revision 042 (before
location_period exists at all, using that revision's nullable-endpoint
schema shape), insert legacy rows directly, then continue the supported
upgrade path through head and assert on what actually happened — the
positive case (valid legacy rows backfill to the exact expected ranges) and
the negative case (genuinely conflicting legacy rows fail the upgrade
clearly, at the exclusion constraint, rather than silently succeeding).

tests.factories' builders are reused for world/timeline/character/location/
world-time setup even at the revision-042 checkpoint: every table and
entity_types row they touch was created by a migration well before 042 and
is untouched by anything after it, so they behave identically at that
checkpoint and at head.
"""

import os
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, make_url, text

from tests.factories import (
    make_character,
    make_location,
    make_timeline,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "database" / "alembic.ini"

K0, K1, K2, K3 = 100, 200, 300, 400


def _require_admin_url() -> str:
    admin_url_raw = os.environ.get("DATABASE_URL")
    if not admin_url_raw:
        pytest.skip(
            "DATABASE_URL is not set — these tests provision their own throwaway "
            "database and need an admin/bootstrap connection, same precondition as "
            "tests/conftest.py::postgres_engine."
        )
    return admin_url_raw


def _provision_database() -> tuple[str, str]:
    """Creates a fresh, unmigrated throwaway database. Returns (admin_url, test_url)."""
    admin_url = make_url(_require_admin_url())
    db_name = f"dnd_ai_phase5_upgrade_{uuid.uuid4().hex[:12]}"
    test_url = admin_url.set(database=db_name)

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()

    return (
        admin_url.render_as_string(hide_password=False),
        test_url.render_as_string(hide_password=False),
    )


def _drop_database(admin_url: str, test_url: str) -> None:
    db_name = make_url(test_url).database
    admin_engine = create_engine(make_url(admin_url), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
    admin_engine.dispose()


def _alembic_upgrade(database_url: str, target: str) -> None:
    subprocess.run(
        ["alembic", "-c", str(ALEMBIC_INI), "upgrade", target],
        check=True,
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
    )


def test_a_populated_revision_042_database_backfills_location_period_through_head() -> None:
    """A database with real revision-042 history rows — one closed, one
    open/current, adjacent but not overlapping — upgrades cleanly through
    revision 052's backfill and revision 050's NOT NULL tightening, ending
    with exactly the ranges the trigger would have produced if it had
    existed when the rows were originally written."""
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "042_close_phase4_location_refs")

        engine = create_engine(test_url)
        with engine.begin() as conn:
            world = make_world(conn, slug="populated-upgrade-positive")
            timeline = make_timeline(conn, world, is_primary=True)
            character = make_character(conn, world)
            location_a = make_location(conn, world, name="Old Room")
            location_b = make_location(conn, world, name="Current Room")
            t0 = make_world_time(conn, world, K0)
            t1 = make_world_time(conn, world, K1)

            row_closed = conn.execute(
                text("""
                    INSERT INTO campaign.character_location_history
                        (timeline_id, character_id, location_id,
                         arrived_at_world_time_id, departed_at_world_time_id)
                    VALUES (:tl, :c, :l, :f, :t)
                    RETURNING character_location_history_id
                """),
                {"tl": timeline, "c": character, "l": location_a, "f": t0, "t": t1},
            ).scalar()
            row_open = conn.execute(
                text("""
                    INSERT INTO campaign.character_location_history
                        (timeline_id, character_id, location_id,
                         arrived_at_world_time_id, departed_at_world_time_id)
                    VALUES (:tl, :c, :l, :f, NULL)
                    RETURNING character_location_history_id
                """),
                {"tl": timeline, "c": character, "l": location_b, "f": t1},
            ).scalar()
        engine.dispose()

        _alembic_upgrade(test_url, "head")

        engine = create_engine(test_url)
        with engine.connect() as conn:
            closed_period = conn.execute(
                text(
                    "SELECT location_period::text FROM campaign.character_location_history "
                    "WHERE character_location_history_id = :id"
                ),
                {"id": row_closed},
            ).scalar()
            open_period = conn.execute(
                text(
                    "SELECT location_period::text FROM campaign.character_location_history "
                    "WHERE character_location_history_id = :id"
                ),
                {"id": row_open},
            ).scalar()
        engine.dispose()

        assert closed_period == f"[{K0},{K1})"
        assert open_period == f"[{K1},)"
    finally:
        _drop_database(admin_url, test_url)


def test_a_populated_revision_042_database_with_conflicting_legacy_rows_fails_the_upgrade_clearly() -> (
    None
):
    """Two genuinely overlapping legacy rows for the same (timeline,
    character) — a non-derivable-without-conflict case the review asked to
    fail clearly rather than silently succeed or corrupt data. The upgrade
    must abort on the overlap constraint's own error."""
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "042_close_phase4_location_refs")

        engine = create_engine(test_url)
        with engine.begin() as conn:
            world = make_world(conn, slug="populated-upgrade-negative")
            timeline = make_timeline(conn, world, is_primary=True)
            character = make_character(conn, world)
            location_a = make_location(conn, world, name="Room A")
            location_b = make_location(conn, world, name="Room B")
            t0 = make_world_time(conn, world, K0)
            t1 = make_world_time(conn, world, K1)
            t2 = make_world_time(conn, world, K2)
            t3 = make_world_time(conn, world, K3)

            conn.execute(
                text("""
                    INSERT INTO campaign.character_location_history
                        (timeline_id, character_id, location_id,
                         arrived_at_world_time_id, departed_at_world_time_id)
                    VALUES (:tl, :c, :l, :f, :t)
                """),
                {"tl": timeline, "c": character, "l": location_a, "f": t0, "t": t2},
            )
            conn.execute(
                text("""
                    INSERT INTO campaign.character_location_history
                        (timeline_id, character_id, location_id,
                         arrived_at_world_time_id, departed_at_world_time_id)
                    VALUES (:tl, :c, :l, :f, :t)
                """),
                {"tl": timeline, "c": character, "l": location_b, "f": t1, "t": t3},
            )
        engine.dispose()

        result = subprocess.run(
            ["alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
            cwd=REPO_ROOT,
            env={**os.environ, "DATABASE_URL": test_url},
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, "upgrade should have failed on the conflicting legacy rows"
        combined_output = result.stdout + result.stderr
        assert "ex_character_location_history_no_overlap" in combined_output
    finally:
        _drop_database(admin_url, test_url)


def test_a_populated_revision_042_database_with_a_missing_arrival_endpoint_fails_at_revision_043() -> (
    None
):
    """The other non-derivable case: a row with no arrival endpoint at all.
    Revision 052's docstring argues this can never actually reach the
    backfill, because revision 043 already makes arrived_at_world_time_id
    NOT NULL with no backfill of its own — a database with a NULL arrival
    endpoint fails applying revision 043 itself, long before reaching
    revision 052 or 050. This test proves that claim rather than leaving it
    asserted: the upgrade must fail exactly at revision 043, on that
    column's own NOT NULL constraint, not silently proceed with a
    manufactured or missing range."""
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "042_close_phase4_location_refs")

        engine = create_engine(test_url)
        with engine.begin() as conn:
            world = make_world(conn, slug="populated-upgrade-no-arrival")
            timeline = make_timeline(conn, world, is_primary=True)
            character = make_character(conn, world)
            location = make_location(conn, world, name="Room")
            t0 = make_world_time(conn, world, K0)

            conn.execute(
                text("""
                    INSERT INTO campaign.character_location_history
                        (timeline_id, character_id, location_id,
                         arrived_at_world_time_id, departed_at_world_time_id)
                    VALUES (:tl, :c, :l, NULL, :t)
                """),
                {"tl": timeline, "c": character, "l": location, "t": t0},
            )
        engine.dispose()

        result = subprocess.run(
            ["alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
            cwd=REPO_ROOT,
            env={**os.environ, "DATABASE_URL": test_url},
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, "upgrade should have failed on the missing arrival endpoint"
        combined_output = result.stdout + result.stderr
        assert "arrived_at_world_time_id" in combined_output
        assert "null value" in combined_output.lower() or "not-null" in combined_output.lower()

        current = subprocess.run(
            ["alembic", "-c", str(ALEMBIC_INI), "current"],
            cwd=REPO_ROOT,
            env={**os.environ, "DATABASE_URL": test_url},
            capture_output=True,
            text=True,
            check=True,
        )
        assert "042_close_phase4_location_refs" in current.stdout, (
            "the upgrade should have stopped at revision 043, before ever reaching 052"
        )
    finally:
        _drop_database(admin_url, test_url)
