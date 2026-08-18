"""Regression tests for tests/conftest.py's database-setup failure
classification against a REAL PostgreSQL 18 server.

Complements tests/unit/test_conftest_database_setup_timeouts.py, which
covers everything reproducible without a real server (a genuine
connect_timeout expiry, an immediate rejection, a hanging subprocess).
The two categories here — a wrong password and a role that lacks
CREATEDB — only occur through a genuine PostgreSQL authentication/
privilege round trip, which a synthetic TCP listener cannot faithfully
reproduce (see tests/conftest.py's _classify_setup_failure() docstring:
psycopg reports these very differently — a wrong password as a plain
OperationalError with a descriptive message, insufficient privilege as a
distinctly-typed ProgrammingError subclass — and both were empirically
verified against a real server, not assumed, before this file was
written). Requires PostgreSQL 18 per docs/DEVELOPMENT.md §3, like every
other tests/database test.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from tests.conftest import DatabaseConnectionError, DatabaseSetupTimeoutError
from tests.conftest import postgres_engine as postgres_engine_fixture

pytestmark = pytest.mark.database

_FAKE_PASSWORD = "wrong-password-must-never-appear-in-a-message"  # noqa: S105 - deliberately wrong
_ROLE_PASSWORD = "role-password-must-never-appear-in-a-message"  # noqa: S105 - test-only, throwaway role


def test_a_wrong_password_is_classified_as_a_connection_error_not_a_timeout(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drives postgres_engine() itself (not _classify_setup_failure() in
    isolation) with DATABASE_URL pointed at the real server but the wrong
    password — proving the fixture's own version-check connection
    attempt correctly classifies this as DatabaseConnectionError, not
    DatabaseSetupTimeoutError (the regression this whole correction pass
    exists to fix: every DBAPIError used to become a timeout claim), and
    that the wrong password itself never appears in the resulting
    message.
    """
    wrong_url = postgres_engine.url.set(password=_FAKE_PASSWORD)
    monkeypatch.setenv("DATABASE_URL", wrong_url.render_as_string(hide_password=False))
    monkeypatch.delenv("DND_AI_TEST_DATABASE_URL", raising=False)

    generator = postgres_engine_fixture.__wrapped__()
    try:
        with pytest.raises(DatabaseConnectionError) as exc_info:
            next(generator)
    finally:
        generator.close()

    error = exc_info.value
    assert not isinstance(error, DatabaseSetupTimeoutError)
    message = str(error)
    assert "authentication" in message.lower()
    assert "not a timeout" in message
    assert _FAKE_PASSWORD not in message


def test_create_database_without_createdb_privilege_is_classified_correctly(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drives postgres_engine() itself with DATABASE_URL pointed at a
    real, freshly created role that has LOGIN but not CREATEDB —
    proving the fixture's CREATE DATABASE step correctly classifies
    psycopg.errors.InsufficientPrivilege (a ProgrammingError, which the
    original except OperationalError clause could not have caught at
    all) as DatabaseConnectionError, not a timeout, and not an unhandled/
    unredacted exception either. The role is created and dropped via
    postgres_engine's own (already-authenticated, superuser) connection,
    and is guaranteed dropped even if the assertion below fails.
    """
    role_name = f"priv_test_{uuid.uuid4().hex[:8]}"

    # CREATE ROLE's PASSWORD clause takes a literal, not a bind parameter
    # (PostgreSQL's grammar rejects a $1 placeholder there) — safe to
    # inline directly since _ROLE_PASSWORD is a fixed, quote-free module
    # constant, not external input.
    with postgres_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
        admin.execute(
            text(f"CREATE ROLE \"{role_name}\" LOGIN PASSWORD '{_ROLE_PASSWORD}' NOCREATEDB")
        )
    try:
        limited_url = postgres_engine.url.set(username=role_name, password=_ROLE_PASSWORD)
        monkeypatch.setenv("DATABASE_URL", limited_url.render_as_string(hide_password=False))
        monkeypatch.delenv("DND_AI_TEST_DATABASE_URL", raising=False)

        generator = postgres_engine_fixture.__wrapped__()
        try:
            with pytest.raises(DatabaseConnectionError) as exc_info:
                next(generator)
        finally:
            generator.close()
    finally:
        with postgres_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
            admin.execute(text(f'DROP ROLE IF EXISTS "{role_name}"'))

    error = exc_info.value
    assert not isinstance(error, DatabaseSetupTimeoutError)
    message = str(error)
    assert "privilege" in message.lower()
    assert "not a timeout" in message
    assert _ROLE_PASSWORD not in message
