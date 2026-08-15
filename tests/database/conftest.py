"""Shared fixtures for tests/database modules that need a connection
authenticated as `app_read_write` specifically — not the `postgres_engine`
admin connection `tests/conftest.py` provides for everything else.
Originally defined only in `test_app_read_write_role.py`; moved here once
`test_database_identity_enforcement.py` needed the same connection.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, create_engine, make_url, text

# Not a real credential: a fixed, openly test-only literal, distinct from
# any password used elsewhere in this repository (CI's own
# ci_disposable_password, or a real deployment's APP_READ_WRITE_PASSWORD)
# so a grep for this string can never be mistaken for a live secret —
# matching the "disposable, clearly labeled, never a real credential"
# discipline this project already applies to CI.
_APP_READ_WRITE_TEST_PASSWORD = "app-read-write-test-only-password-do-not-reuse"


@pytest.fixture(scope="session")
def app_read_write_engine(postgres_engine: Engine) -> Iterator[Engine]:
    """A second engine, connected to the SAME database as `postgres_engine`,
    authenticated as `app_read_write` instead of the admin/superuser
    connection every other test module uses. Session-scoped: setting a
    cluster-wide role's password is a one-time cost per test run, not
    per-test, and every test using this fixture shares the same underlying
    grants regardless.
    """
    with postgres_engine.begin() as connection:
        # A fixed, hardcoded, non-secret test literal — not user input —
        # so direct interpolation here carries no injection risk; this is
        # not the pattern production code should follow for a real,
        # externally supplied password (see scripts/operations/
        # database_recovery.py's set-role-password / _pg_string_literal
        # for that).
        connection.execute(
            text(f"ALTER ROLE app_read_write WITH PASSWORD '{_APP_READ_WRITE_TEST_PASSWORD}'")
        )

    url = make_url(str(postgres_engine.url)).set(
        username="app_read_write", password=_APP_READ_WRITE_TEST_PASSWORD
    )
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def app_read_write_connection(app_read_write_engine: Engine) -> Iterator[Connection]:
    """Function-scoped connection wrapped in a transaction that always
    rolls back — the app_read_write twin of tests/conftest.py's own
    `db_connection` fixture."""
    with app_read_write_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()
