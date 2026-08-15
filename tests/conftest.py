"""Pytest configuration and shared fixtures.

Per docs/PLAN.md §24.0 and ADR 0012: tests/database and tests/scenario run
against a PostgreSQL 18 server — a local or self-hosted install for
development, a disposable containerized instance in CI
(.github/workflows/ci.yml) — the same major version throughout
(docs/DATABASE_CONVENTIONS.md §2.1). This fixture does not distinguish
between the two, because there is nothing target-specific left to
distinguish. Whatever DATABASE_URL points at is treated as an
admin/bootstrap connection with CREATEDB. Each test session creates its own
throwaway database on it (dnd_ai_test_<random>), migrates it to head, and
drops it afterward. AWS RDS remains usable as an optional, no-longer-verified
target for anyone who chooses it (docs/adr/0012-self-hosted-docker-deployment-and-ci-verification.md);
scripts/aws-db-allow-my-ip.sh is the reachability mechanism for that path.

If a caller has already created and migrated a database for this run, set
DND_AI_TEST_DATABASE_URL to it and this fixture connects directly instead of
provisioning its own.

tests/database and tests/scenario are required verification, not optional
coverage (docs/PLAN.md §23.0) — missing configuration and an unsupported
PostgreSQL major version both FAIL the session (DatabaseConfigurationError /
UnsupportedPostgresVersionError below), never pytest.skip(). A skip here
previously let every PostgreSQL-backed test report "skipped" while pytest
still exited 0 — a false-green that verified nothing.

tests/unit must not depend on any fixture here — it runs with no database.
Markers (unit, database, scenario) are registered in pyproject.toml, not here.
"""

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from dotenv import load_dotenv
from sqlalchemy import Connection, Engine, create_engine, make_url, text

REPO_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = REPO_ROOT / "database" / "alembic.ini"

# docs/DATABASE_CONVENTIONS.md §2.1 pins one PostgreSQL major version across
# local, dev/staging/prod, and CI.
REQUIRED_POSTGRES_MAJOR_VERSION = 18

# PR #21's CI run 31312847929 hit a 'psycopg.OperationalError: SSL error:
# unexpected eof while reading' on a completely unrelated, simple lookup
# (tests/database/test_phase7_reparent_guards.py::
# test_a_story_arcs_status_can_still_be_updated) roughly 40 minutes into a
# single pytest session, after 2,278 other tests had already passed
# cleanly — no failed assertion, no schema, migration, or constraint
# error. The evidence confirms the connection was interrupted; it does
# NOT distinguish which of two mechanisms caused that interruption: (a)
# the connection went stale while idle in the pool between checkouts and
# was then handed back out, or (b) it was actively executing that lookup
# when something (AWS RDS or a network path in front of it) dropped it
# mid-statement. Both are consistent with the observed symptom. This
# comment does not claim to know which one actually happened.
#
# pool_pre_ping=True (applied to both test engines below) makes
# SQLAlchemy issue a lightweight liveness check on every checkout,
# transparently discarding and replacing a connection that fails it —
# mitigating mechanism (a) specifically, a well-documented and common
# failure mode for long-lived pooled connections against RDS. It does
# nothing for, and cannot prevent or replay, mechanism (b): a connection
# that dies *mid-statement* while a test is actively using it has no safe
# way to be resumed, so that failure mode, if it recurs, still surfaces
# as a real test error rather than being silently retried or concealed.
# Whether this setting actually prevents a recurrence of PR #21's failure
# is unknown until a fresh CI run on the corrected head passes — this is
# a narrow, well-justified resilience improvement for a plausible
# mechanism, not a confirmed fix for a proven root cause.
#
# pool_recycle proactively retires any pooled connection older than this
# many seconds rather than waiting for pre-ping to catch it reactively —
# cheap insurance given RDS-side or network idle timeouts can be shorter
# than a full CI run, and equally scoped to mechanism (a) above.
_TEST_ENGINE_POOL_PRE_PING = True
_TEST_ENGINE_POOL_RECYCLE_SECONDS = 1800

load_dotenv()


class DatabaseConfigurationError(RuntimeError):
    """Neither DATABASE_URL nor DND_AI_TEST_DATABASE_URL is set.

    Raised rather than pytest.skip()ped: tests/database and tests/scenario
    are required verification, and a skip here used to let every
    PostgreSQL-backed test report "skipped" while pytest still exited 0 — a
    false-green that never actually verified anything.
    """


class UnsupportedPostgresVersionError(RuntimeError):
    """The connected server's major version isn't REQUIRED_POSTGRES_MAJOR_VERSION.

    docs/DATABASE_CONVENTIONS.md §2.1 pins one PostgreSQL major version
    across local, dev/staging/prod, and CI. A mismatch here means the
    developer's (or CI's) target has drifted from that pin — exactly the
    class of problem ADR 0011's two-tier verification model exists to
    catch — so it must fail the run rather than quietly test against the
    wrong version.
    """


def _missing_database_configuration_error() -> DatabaseConfigurationError:
    """Factored out of postgres_engine() so the missing-configuration path
    can be unit-tested (tests/unit/test_conftest_guards.py) without a live
    PostgreSQL server or invoking the real fixture."""
    return DatabaseConfigurationError(
        "Neither DATABASE_URL nor DND_AI_TEST_DATABASE_URL is set. "
        "tests/database and tests/scenario require a real PostgreSQL server "
        "and cannot be skipped — point DATABASE_URL at a local/self-hosted "
        f"PostgreSQL {REQUIRED_POSTGRES_MAJOR_VERSION} server per docs/DEVELOPMENT.md §3 "
        "(compose.yaml provides one), or an optional AWS dev endpoint per "
        "docs/DEVELOPMENT.md §3.5."
    )


def _check_server_major_version(version_num: int) -> None:
    """Pure version-number check, split from _require_supported_postgres()
    below so it can be unit-tested (tests/unit/test_conftest_guards.py)
    without a live PostgreSQL server.

    version_num is PostgreSQL's own server_version_num encoding — e.g.
    180004 for 18.4. For PostgreSQL 10+ (every version this project
    supports), the major version is the value floor-divided by 10000.
    """
    major = version_num // 10000
    if major != REQUIRED_POSTGRES_MAJOR_VERSION:
        raise UnsupportedPostgresVersionError(
            f"Connected PostgreSQL server is major version {major} "
            f"(server_version_num={version_num}); this project requires "
            f"PostgreSQL {REQUIRED_POSTGRES_MAJOR_VERSION}.x — see "
            "docs/DATABASE_CONVENTIONS.md §2.1."
        )


def _require_supported_postgres(engine: Engine) -> None:
    """Connects and enforces REQUIRED_POSTGRES_MAJOR_VERSION before the
    caller does anything else with `engine` — in particular, before
    postgres_engine() provisions the ephemeral test database, so a version
    mismatch fails immediately rather than after creating state that then
    has to be cleaned up. Applied identically on both the DATABASE_URL and
    DND_AI_TEST_DATABASE_URL paths, so local and CI can't diverge here.
    """
    with engine.connect() as conn:
        version_num = int(conn.execute(text("SHOW server_version_num")).scalar_one())
    _check_server_major_version(version_num)


def _test_engine_kwargs() -> dict[str, object]:
    """The pool-resilience kwargs applied to both create_engine() calls in
    postgres_engine() below — factored out to a pure function, rather than
    inlined at each call site, so the settings are unit-testable
    (tests/unit/test_conftest_guards.py) as plain data without asserting
    on SQLAlchemy's own (partly private) Pool/Engine internals."""
    return {
        "pool_pre_ping": _TEST_ENGINE_POOL_PRE_PING,
        "pool_recycle": _TEST_ENGINE_POOL_RECYCLE_SECONDS,
    }


def _run_alembic_upgrade(database_url: str) -> None:
    # sys.executable -m alembic rather than the "alembic" console-script
    # entry point: identical behavior, but doesn't depend on a separate
    # PATH-resolved executable existing/being runnable at all — the
    # interpreter running this test session is already known-good.
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        check=True,
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
    )


@pytest.fixture(scope="session")
def postgres_engine() -> Iterator[Engine]:
    """
    Session-scoped engine pointed at a throwaway database migrated to head,
    provisioned on whatever DATABASE_URL names — a local PostgreSQL server by
    default, or the AWS dev endpoint when that's what's configured. Fails
    loudly (never skips) when nothing is configured or the connected server
    is the wrong PostgreSQL major version — see DatabaseConfigurationError
    and UnsupportedPostgresVersionError above.
    """
    preprovisioned_url = os.environ.get("DND_AI_TEST_DATABASE_URL")
    if preprovisioned_url:
        engine = create_engine(preprovisioned_url, **_test_engine_kwargs())
        try:
            _require_supported_postgres(engine)
            yield engine
        finally:
            engine.dispose()
        return

    admin_url_raw = os.environ.get("DATABASE_URL")
    if not admin_url_raw:
        raise _missing_database_configuration_error()

    admin_url = make_url(admin_url_raw)
    db_name = f"dnd_ai_test_{uuid.uuid4().hex[:12]}"
    test_url = admin_url.set(database=db_name)

    # Admin/cleanup engines below are deliberately left without pre-ping/
    # recycle: each is created, used for one or two short-lived
    # statements (CREATE DATABASE / DROP DATABASE), and disposed
    # immediately — never held open long enough to go stale, so the
    # protection above would add overhead without addressing a real risk
    # here.
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        _require_supported_postgres(admin_engine)
        with admin_engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        admin_engine.dispose()

    # Everything from here must be inside try/finally: a failed migration
    # (which happened during development of this fixture) must not leave the
    # database it just created behind — orphans accumulate on a shared
    # instance otherwise, silently, since nothing else ever lists them.
    try:
        _run_alembic_upgrade(test_url.render_as_string(hide_password=False))

        engine = create_engine(test_url, **_test_engine_kwargs())
        try:
            yield engine
        finally:
            engine.dispose()
    finally:
        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        admin_engine.dispose()


@pytest.fixture
def db_connection(postgres_engine: Engine) -> Iterator[Connection]:
    """
    Function-scoped connection wrapped in a transaction that always rolls back,
    so tests never leak state into each other within the shared session database.
    """
    with postgres_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()
