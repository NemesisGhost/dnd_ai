"""Proves `app_read_write`'s privilege boundaries hold for a REAL,
authenticated connection — not just the static `information_schema`/
`pg_roles` grants `tests/database/test_role_grants.py` already verifies.
`app_read_write` is the exact identity the containerized `api` service
connects as (`compose.yaml`'s own comment on that service); these tests
connect exactly that way, proving the constrained role actually behaves as
constrained in practice, not merely that it is declared that way.

This module's own existence is the direct result of what it found: before
migration `083_schema_usage_grants`, `app_read_write` held table-level DML
grants (`001_bootstrap`) but no `USAGE` on any project schema, so every one
of those grants was unreachable — a session authenticated as
`app_read_write` got `permission denied for schema core` on a bare
`SELECT` against a table it supposedly had `SELECT` on. See that
migration's own docstring for the full account; the positive tests below
are what a passing run of this file actually proves closed that gap, not
just a docstring's claim that it did.

`app_read_write` is a cluster-wide role (PostgreSQL roles are not
per-database), so `app_read_write_engine` below sets a test-only password
for it directly (`ALTER ROLE ... PASSWORD`, idempotent, safe to rerun) so
these tests are self-sufficient against a freshly migrated database —
never assuming an operator already ran `scripts/operations/
database_recovery.py set-role-password` first. The password is a fixed,
openly test-only literal committed here, never a real secret — the same
"disposable, clearly labeled, never a real credential" discipline this
project already applies to CI's `ci_disposable_password`
(`.github/workflows/ci.yml`).
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, create_engine, make_url, text
from sqlalchemy.exc import DBAPIError

from tests.factories import make_world

pytestmark = pytest.mark.database

# Not a real credential — see this module's own docstring. Distinct from
# any password used elsewhere in this repository (CI's own
# ci_disposable_password, or a real deployment's APP_READ_WRITE_PASSWORD)
# so a grep for this string can never be mistaken for a live secret.
_TEST_PASSWORD = "app-read-write-test-only-password-do-not-reuse"

# The full set of DBAPI-level failures a rejected statement can surface as
# through SQLAlchemy — mirrors tests/database/test_interactions.py's own
# CONSTRAINT_ERRORS constant for the same reason: a permission-denied
# error, a read-only-transaction violation, and a constraint violation can
# each surface through a different one of these depending on the exact
# statement, and this module cares that the statement was rejected, not
# which specific DBAPI exception class PostgreSQL chose to raise it as.
DENIED_ERRORS = (DBAPIError,)


@pytest.fixture(scope="session")
def app_read_write_engine(postgres_engine: Engine) -> Iterator[Engine]:
    """A second engine, connected to the SAME database as `postgres_engine`,
    authenticated as `app_read_write` instead of the admin/superuser
    connection every other test module uses. Session-scoped: setting a
    cluster-wide role's password is a one-time cost per test run, not
    per-test, and every test in this module shares the same underlying
    grants regardless.
    """
    with postgres_engine.begin() as connection:
        # A fixed, hardcoded, non-secret test literal — not user input —
        # so direct interpolation here carries no injection risk; this is
        # not the pattern production code should follow for a real,
        # externally supplied password (see scripts/operations/
        # database_recovery.py's set-role-password / _pg_string_literal
        # for that).
        connection.execute(text(f"ALTER ROLE app_read_write WITH PASSWORD '{_TEST_PASSWORD}'"))

    url = make_url(str(postgres_engine.url)).set(username="app_read_write", password=_TEST_PASSWORD)
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


# ---------------------------------------------------------------------------
# Identity — the connected session really is app_read_write, and it is
# genuinely unprivileged at the role-attribute level (the live-connection
# counterpart of test_role_grants.py's static pg_roles assertions).
# ---------------------------------------------------------------------------


def test_the_connection_authenticates_as_app_read_write(
    app_read_write_connection: Connection,
) -> None:
    assert (
        app_read_write_connection.execute(text("SELECT current_user")).scalar() == "app_read_write"
    )


def test_the_connected_role_is_not_a_superuser_or_owner(
    app_read_write_connection: Connection,
) -> None:
    row = app_read_write_connection.execute(
        text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
    ).one()
    assert row.rolsuper is False
    assert row.rolbypassrls is False


# ---------------------------------------------------------------------------
# Positive: normal API-required operations succeed.
# ---------------------------------------------------------------------------


def test_select_works_on_an_application_table(app_read_write_connection: Connection) -> None:
    count = app_read_write_connection.execute(text("SELECT count(*) FROM core.worlds")).scalar()
    assert isinstance(count, int)


def test_insert_and_update_work_via_the_same_factory_helpers_application_code_uses(
    app_read_write_connection: Connection,
) -> None:
    # make_world (tests/factories.py) is plain INSERT/SELECT SQL over a
    # Connection — reusing it here proves a *realistic* command-shaped
    # sequence (a lookup-table SELECT feeding an INSERT) works under
    # app_read_write's actual grants, not just a hand-picked single
    # statement.
    world_id = make_world(app_read_write_connection, slug=f"app-rw-{uuid.uuid4().hex[:8]}")

    app_read_write_connection.execute(
        text("UPDATE core.worlds SET name = 'Renamed World' WHERE world_id = :w"), {"w": world_id}
    )
    name = app_read_write_connection.execute(
        text("SELECT name FROM core.worlds WHERE world_id = :w"), {"w": world_id}
    ).scalar()
    assert name == "Renamed World"

    app_read_write_connection.execute(
        text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": world_id}
    )
    remaining = app_read_write_connection.execute(
        text("SELECT count(*) FROM core.worlds WHERE world_id = :w"), {"w": world_id}
    ).scalar()
    assert remaining == 0


def test_calling_an_existing_sql_function_works(app_read_write_connection: Connection) -> None:
    # dnd_ai.commands.interactions.resolve_check calls this function
    # directly as whatever role the request's own connection uses — it
    # must be callable by app_read_write specifically, not merely by the
    # admin/superuser connection every other test module uses. PostgreSQL
    # grants EXECUTE on a new function to PUBLIC by default and nothing in
    # this repository revokes that (083_schema_usage_grants' own
    # docstring) — this proves that holds in practice, for a function that
    # takes real arguments, not just that the function can be named.
    result = app_read_write_connection.execute(
        text("SELECT world.conditional_route_requirement_satisfied(NULL, NULL)")
    ).scalar()
    assert result is False


# ---------------------------------------------------------------------------
# Negative: everything a DML-only role must not be able to do.
# ---------------------------------------------------------------------------


def test_cannot_create_a_table(app_read_write_connection: Connection) -> None:
    with (
        pytest.raises(DENIED_ERRORS, match="permission denied"),
        app_read_write_connection.begin_nested(),
    ):
        app_read_write_connection.execute(text("CREATE TABLE core.app_rw_ddl_probe (id int)"))


def test_cannot_alter_an_existing_table(app_read_write_connection: Connection) -> None:
    # PostgreSQL rejects ALTER/DROP on a table this role doesn't own with
    # "must be owner of table", not "permission denied" (the wording
    # GRANT-based checks use) — still the same InsufficientPrivilege
    # SQLSTATE, just different phrasing for an ownership-based check.
    with (
        pytest.raises(DENIED_ERRORS, match="must be owner of table"),
        app_read_write_connection.begin_nested(),
    ):
        app_read_write_connection.execute(
            text("ALTER TABLE core.worlds ADD COLUMN app_rw_ddl_probe int")
        )


def test_cannot_drop_a_table(app_read_write_connection: Connection) -> None:
    with (
        pytest.raises(DENIED_ERRORS, match="must be owner of table"),
        app_read_write_connection.begin_nested(),
    ):
        app_read_write_connection.execute(text("DROP TABLE core.worlds"))


def test_cannot_create_a_role(app_read_write_connection: Connection) -> None:
    with (
        pytest.raises(DENIED_ERRORS, match="permission denied"),
        app_read_write_connection.begin_nested(),
    ):
        app_read_write_connection.execute(text("CREATE ROLE app_rw_privilege_escalation_probe"))


def test_cannot_alter_another_roles_password(app_read_write_connection: Connection) -> None:
    with (
        pytest.raises(DENIED_ERRORS, match="permission denied"),
        app_read_write_connection.begin_nested(),
    ):
        app_read_write_connection.execute(
            text("ALTER ROLE app_read_only WITH PASSWORD 'app-rw-privilege-escalation-probe'")
        )


def test_cannot_set_role_to_migration_owner(app_read_write_connection: Connection) -> None:
    with (
        pytest.raises(DENIED_ERRORS, match="permission denied"),
        app_read_write_connection.begin_nested(),
    ):
        app_read_write_connection.execute(text("SET ROLE migration_owner"))


def test_cannot_truncate_a_protected_table(app_read_write_connection: Connection) -> None:
    # TRUNCATE is its own privilege, separate from DELETE — 001_bootstrap
    # never grants it to app_read_write (only SELECT/INSERT/UPDATE/DELETE),
    # so a table app_read_write can otherwise freely DELETE from must
    # still reject a TRUNCATE against it.
    with (
        pytest.raises(DENIED_ERRORS, match="permission denied"),
        app_read_write_connection.begin_nested(),
    ):
        app_read_write_connection.execute(text("TRUNCATE core.worlds"))


def test_cannot_update_audit_change_log(app_read_write_connection: Connection) -> None:
    # audit.change_log is append-only to application roles at the grant
    # level (conventions §24.2, asserted statically by
    # tests/database/test_audit_change_log.py) — confirmed here from
    # app_read_write's own live connection, not only via
    # information_schema.
    with (
        pytest.raises(DENIED_ERRORS, match="permission denied"),
        app_read_write_connection.begin_nested(),
    ):
        app_read_write_connection.execute(text("UPDATE audit.change_log SET correlation_id = NULL"))


def test_cannot_delete_from_audit_change_log(app_read_write_connection: Connection) -> None:
    with (
        pytest.raises(DENIED_ERRORS, match="permission denied"),
        app_read_write_connection.begin_nested(),
    ):
        app_read_write_connection.execute(text("DELETE FROM audit.change_log"))
