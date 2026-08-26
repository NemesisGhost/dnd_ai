"""Single-step upgrade/downgrade/re-upgrade coverage for revision
`103_login_failure_audit_action` (security-audit-review correction).

This migration originally added its one new `audit.change_actions` row
(`code = 'denied'`) by editing `database/seeds/audit.change_actions.yaml`
in place — the same file revision `007_audit_change_log` already applies
via `apply_seed`. That file is frozen once applied anywhere
(docs/DATABASE_CONVENTIONS.md §25.4): `007`'s own `upgrade()` re-reads the
file's *current* content on every run, so the in-place edit made `007`
itself start seeding the `denied` row on a fresh database, before `103`
ever ran — making `103`'s own seed call a permanent no-op, and its
`downgrade()` (which unconditionally deleted the row) an incorrect,
partial inverse: `alembic downgrade 102_revoke_foundry_system_keys` would
remove a row that revision `007` (still applied at 102) was actually
responsible for.

The fix restores the seed file to its original six-row content and has
`103` insert its one row directly (`INSERT ... ON CONFLICT (code) DO
NOTHING`), independent of that file. These tests prove revision `102`
alone seeds exactly the original six codes (the regression this file
exists to catch), and that `103`'s own upgrade/downgrade/re-upgrade cycle
is a clean, self-contained round trip.

Each test provisions its own disposable, throwaway database — never the
shared session-scoped `postgres_engine` every other test in this suite
reuses, since running `alembic downgrade`/`upgrade` as a subprocess against
a URL mutates that database's actual migration state — mirroring
`tests/database/test_downgrade_deferred_trigger_ordering.py`'s established
per-file pattern for a migration-scoped up/down proof, not a shared,
generalized harness.
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

_PREVIOUS_REVISION = "102_revoke_foundry_system_keys"
_THIS_REVISION = "103_login_failure_audit_action"

# Matches tests/conftest.py's _MIGRATION_SUBPROCESS_TIMEOUT_SECONDS / the
# identical constant in test_downgrade_deferred_trigger_ordering.py — a
# hung alembic subprocess must fail this test clearly (subprocess.
# TimeoutExpired) rather than freeze the whole session with no recovery.
_ALEMBIC_SUBPROCESS_TIMEOUT_SECONDS = 300

# Matches tests/conftest.py's _DB_CONNECT_TIMEOUT_SECONDS.
_CONNECT_TIMEOUT_SECONDS = 10

_ORIGINAL_SIX_CODES = frozenset(
    {"created", "updated", "status_changed", "archived", "restored", "deleted"}
)


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
    db_name = f"dnd_ai_103_{label}_{uuid.uuid4().hex[:12]}"
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
    # point — matches test_downgrade_deferred_trigger_ordering.py's
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


def _change_action_codes(database_url: str) -> set[str]:
    engine = create_engine(database_url, connect_args=_connect_args())
    try:
        with engine.connect() as conn:
            return set(conn.execute(text("SELECT code FROM audit.change_actions")).scalars().all())
    finally:
        engine.dispose()


def test_revision_102_alone_seeds_only_the_original_six_change_action_codes() -> None:
    """The regression this file exists to catch: revision `007` must never
    seed `denied` on its own — that row belongs exclusively to `103`. A
    database migrated only through `102` (the revision immediately before
    `103`) must show exactly the original six codes."""
    admin_url, test_url = _provision_database("upto102")
    try:
        _alembic_upgrade(test_url, _PREVIOUS_REVISION)
        assert _change_action_codes(test_url) == _ORIGINAL_SIX_CODES
    finally:
        _drop_database(admin_url, test_url)


def test_upgrading_to_103_adds_exactly_the_denied_code() -> None:
    admin_url, test_url = _provision_database("to103")
    try:
        _alembic_upgrade(test_url, _PREVIOUS_REVISION)
        _alembic_upgrade(test_url, _THIS_REVISION)
        assert _change_action_codes(test_url) == _ORIGINAL_SIX_CODES | {"denied"}

        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            with engine.connect() as conn:
                row = (
                    conn.execute(
                        text(
                            "SELECT display_name, sort_order, is_active FROM audit.change_actions "
                            "WHERE code = 'denied'"
                        )
                    )
                    .mappings()
                    .one()
                )
        finally:
            engine.dispose()
        assert row["display_name"] == "Denied"
        assert row["sort_order"] == 70
        assert row["is_active"] is True
    finally:
        _drop_database(admin_url, test_url)


def _denied_change_action_id(database_url: str) -> uuid.UUID:
    engine = create_engine(database_url, connect_args=_connect_args())
    try:
        with engine.connect() as conn:
            value = conn.execute(
                text("SELECT change_action_id FROM audit.change_actions WHERE code = 'denied'")
            ).scalar_one()
    finally:
        engine.dispose()
    assert isinstance(value, uuid.UUID)
    return value


def _insert_denied_audit_row(database_url: str) -> int:
    """A real `audit.change_log` row referencing `denied` through the same
    production `schema_name`/`table_name` pairing `dnd_ai.api.local_auth.
    _record_login_failure_audit` actually writes, resolving `change_action_
    id` through the real `audit.change_actions` foreign key rather than a
    literal — exactly the protected-history condition revision 103's
    conditional downgrade must detect and refuse to destroy."""
    engine = create_engine(database_url, connect_args=_connect_args())
    try:
        with engine.begin() as conn:
            change_log_id = conn.execute(
                text("""
                    INSERT INTO audit.change_log
                        (change_action_id, schema_name, table_name, actor_service, command_name)
                    VALUES (
                        (SELECT change_action_id FROM audit.change_actions WHERE code = 'denied'),
                        'security', 'browser_sessions', 'local_auth', 'local_auth.login_failure'
                    )
                    RETURNING change_log_id
                """)
            ).scalar_one()
    finally:
        engine.dispose()
    assert isinstance(change_log_id, int)
    return change_log_id


def test_downgrading_103_to_102_removes_only_the_denied_code() -> None:
    """Reversible path: no `denied` audit history exists yet, so downgrading
    must succeed and restore the exact pre-103 reference-data state."""
    admin_url, test_url = _provision_database("downgrade")
    try:
        _alembic_upgrade(test_url, _THIS_REVISION)
        assert _change_action_codes(test_url) == _ORIGINAL_SIX_CODES | {"denied"}

        result = _alembic(test_url, "downgrade", _PREVIOUS_REVISION)
        assert result.returncode == 0, result.stdout + result.stderr
        assert _current_revision(test_url) == _PREVIOUS_REVISION

        # The exact defect this migration's downgrade previously had: it
        # must remove only 'denied', leaving the original six intact —
        # never more, never fewer.
        assert _change_action_codes(test_url) == _ORIGINAL_SIX_CODES
    finally:
        _drop_database(admin_url, test_url)


def test_downgrade_then_reupgrade_round_trips_cleanly() -> None:
    """Test upgrade from the previous revision, downgrade back to the
    previous revision, and re-upgrade — the exact sequence a security
    review of this migration's rollback behavior should exercise."""
    admin_url, test_url = _provision_database("roundtrip")
    try:
        _alembic_upgrade(test_url, _THIS_REVISION)
        assert _current_revision(test_url) == _THIS_REVISION

        downgrade_result = _alembic(test_url, "downgrade", _PREVIOUS_REVISION)
        assert downgrade_result.returncode == 0, downgrade_result.stdout + downgrade_result.stderr
        assert _current_revision(test_url) == _PREVIOUS_REVISION
        assert _change_action_codes(test_url) == _ORIGINAL_SIX_CODES

        _alembic_upgrade(test_url, _THIS_REVISION)
        assert _current_revision(test_url) == _THIS_REVISION
        assert _change_action_codes(test_url) == _ORIGINAL_SIX_CODES | {"denied"}

        # Re-upgrading is idempotent (ON CONFLICT DO NOTHING) — a second
        # 'denied' row, or a duplicate-key failure, would both be wrong.
        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            with engine.connect() as conn:
                count = conn.execute(
                    text("SELECT count(*) FROM audit.change_actions WHERE code = 'denied'")
                ).scalar_one()
        finally:
            engine.dispose()
        assert count == 1
    finally:
        _drop_database(admin_url, test_url)


def test_downgrading_103_to_102_fails_safely_when_denied_audit_history_exists() -> None:
    """Protected-history path: once a real `audit.change_log` row
    references the `denied` outcome, downgrading past 103 must fail with a
    clear, actionable message rather than deleting or relabeling that
    history — and must leave the database completely unchanged: still at
    revision 103, the `denied` change action still defined, the
    referencing audit row still present and unmodified, and every other
    revision-103 reference-data row still exactly as it was."""
    admin_url, test_url = _provision_database("protected")
    try:
        _alembic_upgrade(test_url, _THIS_REVISION)
        denied_id_before = _denied_change_action_id(test_url)
        change_log_id = _insert_denied_audit_row(test_url)

        result = _alembic(test_url, "downgrade", _PREVIOUS_REVISION)
        assert result.returncode != 0, (
            "expected the downgrade to fail while durable 'denied' audit history exists:\n"
            + result.stdout
            + result.stderr
        )
        combined_output = result.stdout + result.stderr
        assert "Cannot downgrade revision 103_login_failure_audit_action" in combined_output
        assert "durable 'denied' security-audit history exists" in combined_output
        assert "will not be deleted or relabeled" in combined_output
        assert "restoring a database backup" in combined_output

        # The Alembic revision never moved off 103.
        assert _current_revision(test_url) == _THIS_REVISION

        # The denied change_action row is untouched — same id, still present.
        assert _denied_change_action_id(test_url) == denied_id_before

        # The referencing audit row is untouched.
        engine = create_engine(test_url, connect_args=_connect_args())
        try:
            with engine.connect() as conn:
                row = (
                    conn.execute(
                        text(
                            "SELECT change_action_id, schema_name, table_name, actor_service "
                            "FROM audit.change_log WHERE change_log_id = :id"
                        ),
                        {"id": change_log_id},
                    )
                    .mappings()
                    .one_or_none()
                )
        finally:
            engine.dispose()
        assert row is not None, "the referencing audit row must not have been deleted"
        assert row["change_action_id"] == denied_id_before
        assert row["schema_name"] == "security"
        assert row["table_name"] == "browser_sessions"
        assert row["actor_service"] == "local_auth"

        # No partial downgrade: every original code, plus 'denied', is
        # still present — nothing was removed or relabeled.
        assert _change_action_codes(test_url) == _ORIGINAL_SIX_CODES | {"denied"}
    finally:
        _drop_database(admin_url, test_url)
