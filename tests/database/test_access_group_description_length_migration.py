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

Each test provisions its own disposable, throwaway database — never the
shared session-scoped `postgres_engine` every other test in this suite
reuses, since running `alembic upgrade`/`downgrade` as a subprocess
against a URL mutates that database's actual migration state — mirroring
`tests/database/test_login_failure_audit_action_migration.py`'s identical
per-revision pattern.
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
