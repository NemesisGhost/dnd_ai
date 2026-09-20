"""Single-step upgrade/downgrade/re-upgrade coverage for revision
`106_access_group_desc_length`'s own production-safety correction — see
that migration's own "Production-safety correction" docstring section for
the full legacy-data policy this file proves.

Revisions 080 through 105 enforced no length bound on `security.
access_groups.description` at all, so a database that already has real
rows by the time `106` runs may carry either an empty string (legal
before this revision — the application's own blank-to-`NULL`
normalization was never database-enforced) or a description longer than
2000 characters (no bound existed to stop one). The first cut of this
migration added `ck_access_groups_description_length` immediately,
unconditionally validating — which would abort the `105`->`106` upgrade
outright on such a database, with only a generic `CheckViolation` and no
indication of which row(s) are responsible.

These tests prove the corrected policy end to end: an over-length
description blocks the upgrade with a deliberate, actionable error naming
the affected `access_group_id`(s) and changes nothing in the database; an
empty-string description is backfilled to `NULL` (the application's own
pre-existing normalization, applied retroactively — not a new, invented
one); a valid legacy description is preserved byte-for-byte; the final
constraint rejects a new invalid direct write; and the migration survives
a downgrade/re-upgrade round trip.

The concurrency section at the bottom of this file proves this revision's
own "Concurrency guarantee" docstring section directly against real
PostgreSQL locks, on two genuinely separate connections, using the
deterministic `SET LOCAL lock_timeout` blocking idiom already established
in `tests/database/test_membership_role_concurrency.py`: an invalid
legacy write racing the migration's `ADD CONSTRAINT ... NOT VALID` can
never slip past both the preflight and the constraint itself — it either
commits early enough to be caught by the preflight, or is forced to queue
behind the migration's own lock and is rejected by the constraint the
instant it is finally allowed to proceed.

Each test provisions its own disposable, throwaway database — never the
shared session-scoped `postgres_engine` every other test in this suite
reuses, since running `alembic upgrade`/`downgrade` as a subprocess
against a URL mutates that database's actual migration state — mirroring
`tests/database/test_login_failure_audit_action_migration.py`'s identical
per-revision pattern. The concurrency tests still provision their own
throwaway database (rather than reusing the shared `postgres_engine`
fixture), specifically because they need a schema state where
`ck_access_groups_description_length` does not yet exist to install it
themselves, mid-test, on two live connections — the shared fixture is
already migrated to head, where the constraint is already present.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import Connection, create_engine, make_url, text
from sqlalchemy.exc import IntegrityError

from tests.factories import make_access_group, make_campaign, make_timeline, make_world

pytestmark = pytest.mark.database

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "database" / "alembic.ini"

_PREVIOUS_REVISION = "105_access_group_status"
_THIS_REVISION = "106_access_group_desc_length"

# Matches tests/conftest.py's _MIGRATION_SUBPROCESS_TIMEOUT_SECONDS / the
# identical constant in test_login_failure_audit_action_migration.py — a
# hung alembic subprocess must fail this test clearly (subprocess.
# TimeoutExpired) rather than freeze the whole session with no recovery.
_ALEMBIC_SUBPROCESS_TIMEOUT_SECONDS = 300

# Matches tests/conftest.py's _DB_CONNECT_TIMEOUT_SECONDS.
_CONNECT_TIMEOUT_SECONDS = 10

_OVER_LENGTH_DESCRIPTION = "x" * 2001
_VALID_LEGACY_DESCRIPTION = "A perfectly ordinary legacy description."


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
    db_name = f"dnd_ai_106_{label}_{uuid.uuid4().hex[:12]}"
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
    # sys.executable -m alembic, not the "alembic" console-script entry
    # point — matches test_login_failure_audit_action_migration.py's
    # identical choice: doesn't depend on a separate PATH-resolved
    # executable, and avoids that shim's own extra process-spawn layer.
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


# ---------------------------------------------------------------------------
# Population helpers — raw factory calls against a database stopped at 105,
# never through the HTTP/command layer (which already normalizes/bounds
# description and did not exist to enforce anything at revision 105 anyway).
# ---------------------------------------------------------------------------


def _make_campaign_at_105(connection: Connection, slug: str) -> uuid.UUID:
    world_id = make_world(connection, slug=slug)
    timeline_id = make_timeline(connection, world_id, is_primary=True)
    # "pending", not "active" — this test only needs a campaign row to hang
    # an access_groups.campaign_id off of, never a real access-manager
    # membership/authorization scenario.
    return make_campaign(
        connection, timeline_id, f"{slug} campaign", lifecycle_status_code="pending"
    )


def _access_group_description(connection: Connection, access_group_id: uuid.UUID) -> str | None:
    return connection.execute(
        text("SELECT description FROM security.access_groups WHERE access_group_id = :g"),
        {"g": access_group_id},
    ).scalar()


def _constraint_exists(connection: Connection, constraint_name: str) -> bool:
    return bool(
        connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = :name)"),
            {"name": constraint_name},
        ).scalar()
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_revision_105_allows_an_empty_and_an_over_length_description() -> None:
    """Establishes the defect's own precondition: at 105, neither value is
    rejected by anything — proving the risk this migration's own
    production-safety correction actually addresses is real, not
    hypothetical."""
    admin_url, test_url = _provision_database("legacy_allowed")
    try:
        _alembic_upgrade(test_url, _PREVIOUS_REVISION)

        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            with engine.begin() as conn:
                campaign_id = _make_campaign_at_105(conn, f"legacy-allowed-{uuid.uuid4().hex[:8]}")
                empty_id = make_access_group(conn, campaign_id, name="Empty", description="")
                over_length_id = make_access_group(
                    conn, campaign_id, name="Over Length", description=_OVER_LENGTH_DESCRIPTION
                )
            with engine.connect() as conn:
                assert _access_group_description(conn, empty_id) == ""
                assert _access_group_description(conn, over_length_id) == _OVER_LENGTH_DESCRIPTION
        finally:
            engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def test_upgrading_to_106_blocks_deployment_on_an_over_length_description_and_changes_nothing() -> (
    None
):
    """The corrected policy's core proof: an over-length legacy
    description must never be silently truncated, and must never let the
    migration partially apply. The upgrade fails deliberately, names the
    affected access_group_id, and leaves the database completely
    untouched — still at 105, the offending row byte-for-byte unchanged,
    and the new constraint not yet created."""
    admin_url, test_url = _provision_database("blocked")
    try:
        _alembic_upgrade(test_url, _PREVIOUS_REVISION)

        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            with engine.begin() as conn:
                campaign_id = _make_campaign_at_105(conn, f"blocked-{uuid.uuid4().hex[:8]}")
                over_length_id = make_access_group(
                    conn, campaign_id, name="Over Length", description=_OVER_LENGTH_DESCRIPTION
                )
        finally:
            engine.dispose()

        result = _alembic(test_url, "upgrade", _THIS_REVISION)
        assert result.returncode != 0, (
            "expected the upgrade to fail while an over-length legacy description exists:\n"
            + result.stdout
            + result.stderr
        )
        combined_output = result.stdout + result.stderr
        assert "Cannot add ck_access_groups_description_length" in combined_output
        assert "1 security.access_groups row(s)" in combined_output
        assert str(over_length_id) in combined_output
        assert "not silently truncated" in combined_output

        # The Alembic revision never moved off 105.
        assert _current_revision(test_url) == _PREVIOUS_REVISION

        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            with engine.connect() as conn:
                # Byte-for-byte unchanged — no truncation, no normalization
                # attempt at all for this row.
                assert _access_group_description(conn, over_length_id) == _OVER_LENGTH_DESCRIPTION
                assert not _constraint_exists(conn, "ck_access_groups_description_length")
        finally:
            engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def test_after_shortening_the_description_upgrading_to_106_succeeds() -> None:
    """The documented resolution path: once an operator fixes the
    offending row (here, clearing it — an equally valid resolution to
    shortening it), re-running the migration succeeds."""
    admin_url, test_url = _provision_database("resolved")
    try:
        _alembic_upgrade(test_url, _PREVIOUS_REVISION)

        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            with engine.begin() as conn:
                campaign_id = _make_campaign_at_105(conn, f"resolved-{uuid.uuid4().hex[:8]}")
                over_length_id = make_access_group(
                    conn, campaign_id, name="Over Length", description=_OVER_LENGTH_DESCRIPTION
                )
        finally:
            engine.dispose()

        blocked = _alembic(test_url, "upgrade", _THIS_REVISION)
        assert blocked.returncode != 0

        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE security.access_groups SET description = NULL "
                        "WHERE access_group_id = :g"
                    ),
                    {"g": over_length_id},
                )
        finally:
            engine.dispose()

        _alembic_upgrade(test_url, _THIS_REVISION)
        assert _current_revision(test_url) == _THIS_REVISION

        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            with engine.connect() as conn:
                assert _access_group_description(conn, over_length_id) is None
                assert _constraint_exists(conn, "ck_access_groups_description_length")
        finally:
            engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def test_upgrading_to_106_normalizes_empty_descriptions_and_preserves_valid_ones() -> None:
    """The other half of the policy: an empty-string legacy description is
    backfilled to NULL (the application's own pre-existing normalization,
    applied retroactively — never a new, invented one), a NULL description
    stays NULL, and a valid, within-bound legacy description is preserved
    exactly — proving this migration is not destructive to any legitimate
    legacy data."""
    admin_url, test_url = _provision_database("normalize")
    try:
        _alembic_upgrade(test_url, _PREVIOUS_REVISION)

        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            with engine.begin() as conn:
                campaign_id = _make_campaign_at_105(conn, f"normalize-{uuid.uuid4().hex[:8]}")
                empty_id = make_access_group(conn, campaign_id, name="Empty", description="")
                null_id = make_access_group(conn, campaign_id, name="Null", description=None)
                valid_id = make_access_group(
                    conn, campaign_id, name="Valid", description=_VALID_LEGACY_DESCRIPTION
                )
        finally:
            engine.dispose()

        _alembic_upgrade(test_url, _THIS_REVISION)
        assert _current_revision(test_url) == _THIS_REVISION

        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            with engine.connect() as conn:
                assert _access_group_description(conn, empty_id) is None
                assert _access_group_description(conn, null_id) is None
                assert _access_group_description(conn, valid_id) == _VALID_LEGACY_DESCRIPTION
                assert _constraint_exists(conn, "ck_access_groups_description_length")
        finally:
            engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def test_the_final_constraint_rejects_a_new_invalid_direct_write() -> None:
    """Once 106 is fully applied, the database itself — not just the
    application — refuses both invalid shapes directly: an empty string
    (which the application would already normalize to NULL, but the raw
    column must still reject it as defense in depth) and an over-length
    value."""
    admin_url, test_url = _provision_database("rejects_new")
    try:
        _alembic_upgrade(test_url, _THIS_REVISION)

        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            campaign_id: uuid.UUID
            with engine.begin() as conn:
                campaign_id = _make_campaign_at_105(conn, f"rejects-new-{uuid.uuid4().hex[:8]}")

            with pytest.raises(IntegrityError) as empty_exc, engine.begin() as conn:
                make_access_group(conn, campaign_id, name="New Empty", description="")
            assert "ck_access_groups_description_length" in str(empty_exc.value)

            with pytest.raises(IntegrityError) as over_length_exc, engine.begin() as conn:
                make_access_group(
                    conn, campaign_id, name="New Over Length", description=_OVER_LENGTH_DESCRIPTION
                )
            assert "ck_access_groups_description_length" in str(over_length_exc.value)
        finally:
            engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def test_downgrade_then_reupgrade_round_trips_cleanly() -> None:
    """Test upgrade from the previous revision (with a legacy empty
    description already normalized), downgrade back to 105, and
    re-upgrade — the exact sequence a review of this migration's rollback
    behavior should exercise. The downgrade does not attempt to restore
    the original empty string (there is nothing to correctly restore —
    see the migration's own "Rollback" docstring section); re-upgrading
    must succeed cleanly since the data is already within bounds."""
    admin_url, test_url = _provision_database("roundtrip")
    try:
        _alembic_upgrade(test_url, _PREVIOUS_REVISION)

        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            with engine.begin() as conn:
                campaign_id = _make_campaign_at_105(conn, f"roundtrip-{uuid.uuid4().hex[:8]}")
                normalized_id = make_access_group(conn, campaign_id, name="Empty", description="")
        finally:
            engine.dispose()

        _alembic_upgrade(test_url, _THIS_REVISION)
        assert _current_revision(test_url) == _THIS_REVISION

        downgrade_result = _alembic(test_url, "downgrade", _PREVIOUS_REVISION)
        assert downgrade_result.returncode == 0, downgrade_result.stdout + downgrade_result.stderr
        assert _current_revision(test_url) == _PREVIOUS_REVISION

        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            with engine.connect() as conn:
                assert not _constraint_exists(conn, "ck_access_groups_description_length")
                # Still NULL, not restored to '' — the backfill is one-way.
                assert _access_group_description(conn, normalized_id) is None
        finally:
            engine.dispose()

        _alembic_upgrade(test_url, _THIS_REVISION)
        assert _current_revision(test_url) == _THIS_REVISION

        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            with engine.connect() as conn:
                assert _constraint_exists(conn, "ck_access_groups_description_length")
                assert _access_group_description(conn, normalized_id) is None
        finally:
            engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


# ---------------------------------------------------------------------------
# Concurrency: proves this revision's own "Concurrency guarantee" docstring
# section (106_access_group_desc_length.py) against real PostgreSQL locks —
# not through the alembic subprocess (which cannot be paused mid-transaction
# to synchronize with a second connection), but through the identical SQL
# statements upgrade() itself executes in the identical order, run directly
# against two real, separate connections. `_CONSTRAINT_SQL` mirrors the
# migration's own ADD CONSTRAINT statement exactly so a drift between the
# two would fail these tests, not silently diverge.
# ---------------------------------------------------------------------------

_CONSTRAINT_NAME = "ck_access_groups_description_length"
_CONSTRAINT_SQL = f"""
    ALTER TABLE security.access_groups
    ADD CONSTRAINT {_CONSTRAINT_NAME}
    CHECK (description IS NULL OR char_length(description) BETWEEN 1 AND 2000)
    NOT VALID;
"""

# Matches tests/database/test_membership_role_concurrency.py's identical
# choice: long enough that a genuinely granted lock never times out on a
# healthy local/CI database, short enough that a real block (the case these
# tests exist to prove) fails fast rather than hanging.
_LOCK_TIMEOUT = "2s"


def test_a_write_committed_while_add_constraint_waits_is_caught_by_the_preflight() -> None:
    """Half one of the "Concurrency guarantee": a writer already in flight
    when `ADD CONSTRAINT ... NOT VALID` runs must finish first (proven here
    via a genuine `lock_timeout` block, not a hopeful sleep), and once it
    commits, its row must already be visible to the preflight `SELECT` that
    runs immediately afterward in the same transaction — never silently
    missed."""
    admin_url, test_url = _provision_database("conc_preflight")
    try:
        _alembic_upgrade(test_url, _PREVIOUS_REVISION)

        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            with engine.begin() as setup:
                campaign_id = _make_campaign_at_105(setup, f"conc-preflight-{uuid.uuid4().hex[:8]}")

            with engine.connect() as writer, engine.connect() as migrator:
                writer.begin()
                # In flight, uncommitted — holds a ROW EXCLUSIVE lock on
                # security.access_groups that ADD CONSTRAINT's ACCESS
                # EXCLUSIVE conflicts with.
                over_length_id = make_access_group(
                    writer, campaign_id, name="Racer", description=_OVER_LENGTH_DESCRIPTION
                )

                migrator.begin()
                migrator.execute(text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
                with pytest.raises(Exception) as exc:
                    migrator.execute(text(_CONSTRAINT_SQL))
                message = str(exc.value)
                assert "lock_timeout" in message or "canceling statement" in message, (
                    "expected ADD CONSTRAINT to block on the writer's own in-flight, "
                    f"uncommitted insert, got: {message}"
                )
                migrator.rollback()

                # The writer commits — its over-length row is now durable.
                writer.commit()

                # Unblocked now: ADD CONSTRAINT proceeds, and the preflight
                # SELECT immediately after it (same transaction, same
                # statement-level READ COMMITTED snapshot) must see the row
                # the writer just committed.
                migrator.begin()
                migrator.execute(text(_CONSTRAINT_SQL))
                found_ids = (
                    migrator.execute(
                        text("""
                            SELECT access_group_id FROM security.access_groups
                            WHERE description IS NOT NULL AND char_length(description) > 2000
                        """)
                    )
                    .scalars()
                    .all()
                )
                assert over_length_id in found_ids, (
                    "expected the writer's committed over-length row to be visible to the "
                    "preflight SELECT run right after ADD CONSTRAINT acquired its lock"
                )
                # Mirrors upgrade()'s own behavior on a real violation: raise,
                # then let the transaction roll back the NOT VALID constraint
                # along with everything else.
                migrator.rollback()

            with engine.connect() as verify:
                assert not _constraint_exists(verify, _CONSTRAINT_NAME)
                assert _access_group_description(verify, over_length_id) == _OVER_LENGTH_DESCRIPTION
        finally:
            engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def test_a_write_queued_behind_constraint_installation_is_rejected_once_unblocked() -> None:
    """Half two of the "Concurrency guarantee": a writer that only attempts
    an invalid insert *after* `ADD CONSTRAINT ... NOT VALID` has already
    taken its lock must queue behind it (again proven via a genuine
    `lock_timeout` block) — and once the migration's transaction commits
    and the writer is finally allowed to proceed, its invalid insert must
    be rejected by the now-installed constraint immediately, even though
    `VALIDATE CONSTRAINT` never ran against it (a NOT VALID constraint
    still fully enforces itself against every new write)."""
    admin_url, test_url = _provision_database("conc_enforced")
    try:
        _alembic_upgrade(test_url, _PREVIOUS_REVISION)

        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            with engine.begin() as setup:
                campaign_id = _make_campaign_at_105(setup, f"conc-enforced-{uuid.uuid4().hex[:8]}")

            with engine.connect() as migrator, engine.connect() as writer:
                migrator.begin()
                # No pre-existing bad rows, so ADD CONSTRAINT succeeds
                # immediately and holds ACCESS EXCLUSIVE, uncommitted.
                migrator.execute(text(_CONSTRAINT_SQL))

                writer.begin()
                writer.execute(text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
                with pytest.raises(Exception) as exc:
                    make_access_group(
                        writer, campaign_id, name="Late Racer", description=_OVER_LENGTH_DESCRIPTION
                    )
                message = str(exc.value)
                assert "lock_timeout" in message or "canceling statement" in message, (
                    "expected the writer's insert to queue behind ADD CONSTRAINT's own "
                    f"still-uncommitted ACCESS EXCLUSIVE lock, got: {message}"
                )
                writer.rollback()

                # The migration finishes and commits — no violating legacy
                # rows existed, so the preflight, backfill, and VALIDATE
                # CONSTRAINT (irrelevant to this half — proven separately by
                # test_upgrading_to_106_normalizes_empty_descriptions_and_
                # preserves_valid_ones above) all succeed.
                migrator.execute(
                    text("""
                    ALTER TABLE security.access_groups
                    VALIDATE CONSTRAINT ck_access_groups_description_length;
                """)
                )
                migrator.commit()

            # Unblocked now — the previously-queued write is retried fresh,
            # and must be rejected by the constraint immediately.
            with pytest.raises(IntegrityError) as write_exc, engine.begin() as retry:
                make_access_group(
                    retry,
                    campaign_id,
                    name="Late Racer Retry",
                    description=_OVER_LENGTH_DESCRIPTION,
                )
            assert _CONSTRAINT_NAME in str(write_exc.value)

            with engine.connect() as verify:
                assert _constraint_exists(verify, _CONSTRAINT_NAME)
        finally:
            engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
