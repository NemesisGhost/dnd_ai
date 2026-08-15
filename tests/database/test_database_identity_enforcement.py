"""Proves `dnd_ai.api.deps.verify_database_identity` — the *live* half of
the app_read_write production enforcement — against a REAL PostgreSQL
connection. `tests/unit/test_config.py` covers the *static* half
(`dnd_ai.config.Settings` refusing to start when `DND_AI_DATABASE_URL`
doesn't *name* `app_read_write`); that alone only proves what a configured
URL claims, not what a connection actually authenticates as. This module
exists because the two can diverge: a connection pooler/proxy that maps a
credential to a different login role, or an implicit/explicit `SET ROLE`
after authentication, would satisfy the static check while the live
session is really running as something else — exactly the gap
`dnd_ai.api.app`'s lifespan startup calls `verify_database_identity` to
close (see that module's own docstring for why lifespan, not `/readyz`).
"""

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.deps import (
    DatabaseIdentityError,
    _check_database_identity,
    verify_database_identity,
)

pytestmark = pytest.mark.database


def test_a_postgres_admin_connection_fails_the_app_read_write_check(
    postgres_engine: Engine,
) -> None:
    """`postgres_engine` (tests/conftest.py) is the admin/superuser
    connection every other test module intentionally uses — it must NOT
    satisfy a check for `app_read_write`, or this function would be
    worthless as a production safeguard."""
    with pytest.raises(DatabaseIdentityError, match="app_read_write"):
        verify_database_identity(postgres_engine, expected_role="app_read_write")


def test_an_app_read_write_connection_passes_its_own_check(
    app_read_write_engine: Engine,
) -> None:
    verify_database_identity(
        app_read_write_engine, expected_role="app_read_write"
    )  # must not raise


def test_the_failure_message_never_includes_a_url_or_password(postgres_engine: Engine) -> None:
    """Requirement: the failure contract must not leak credentials or the
    database URL. postgres_engine's own URL embeds a password (see
    tests/conftest.py) — confirm neither that password nor any `://`
    URL-shaped substring ends up in the raised message."""
    admin_password = postgres_engine.url.password
    with pytest.raises(DatabaseIdentityError) as excinfo:
        verify_database_identity(postgres_engine, expected_role="app_read_write")
    message = str(excinfo.value)
    assert "://" not in message
    if admin_password:
        assert admin_password not in message


def test_an_explicit_set_role_does_not_mask_a_session_user_mismatch(
    postgres_engine: Engine,
) -> None:
    """The dual session_user/current_user check exists specifically for
    this: a superuser session that does `SET ROLE app_read_write` makes
    `current_user` report `app_read_write`, but the connection never
    stopped being authenticated as the original (here: postgres) role —
    `session_user` still reflects that. Checking current_user alone would
    have let this slip past as a false pass."""
    with postgres_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("SET ROLE app_read_write"))
            assert connection.execute(text("SELECT current_user")).scalar() == "app_read_write"
            with pytest.raises(DatabaseIdentityError, match="app_read_write"):
                _check_database_identity(connection, expected_role="app_read_write")
        finally:
            transaction.rollback()


def test_the_connection_level_check_passes_for_a_genuine_app_read_write_session(
    app_read_write_connection: Connection,
) -> None:
    _check_database_identity(  # must not raise
        app_read_write_connection, expected_role="app_read_write"
    )
