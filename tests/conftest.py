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
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from dotenv import load_dotenv
from sqlalchemy import URL, Connection, Engine, create_engine, make_url, text
from sqlalchemy.exc import OperationalError

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

# An unreachable PostgreSQL host (a silently-blackholed address, a listener
# that never completes the startup handshake, ...) or a stuck `alembic
# upgrade head` used to hang postgres_engine() indefinitely — no timeout on
# any connection attempt or on the migration subprocess meant a bad target
# silently consumed the entire pytest run (and CI job) instead of failing
# fast with a diagnosis. Every create_engine() call below now passes
# connect_args=_connect_args() (a bounded libpq connect_timeout, which
# covers the full connection handshake, not just the initial TCP SYN/ACK),
# and _run_alembic_upgrade()/_run_bounded_subprocess() pass a bounded
# subprocess timeout. Both are read as module attributes at call time
# (never captured as default-argument values), so tests can monkeypatch
# them to small values without waiting out the real production bound.
_DB_CONNECT_TIMEOUT_SECONDS = 10
_MIGRATION_SUBPROCESS_TIMEOUT_SECONDS = 300

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


class DatabaseSetupTimeoutError(RuntimeError):
    """A PostgreSQL connection attempt, or the Alembic migration subprocess,
    did not complete within its bounded timeout while provisioning the
    ephemeral test database.

    Raised instead of letting the underlying psycopg connection or the
    `alembic upgrade head` subprocess hang indefinitely — see
    _DB_CONNECT_TIMEOUT_SECONDS/_MIGRATION_SUBPROCESS_TIMEOUT_SECONDS above.
    Always built via _setup_timeout_error(), which redacts the target URL
    and strips any password out of the underlying driver/subprocess error
    text too, so this can be printed safely to test output or CI logs.
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
    try:
        with engine.connect() as conn:
            version_num = int(conn.execute(text("SHOW server_version_num")).scalar_one())
    except OperationalError as exc:
        raise _setup_timeout_error(
            "Connecting to PostgreSQL", engine.url, _DB_CONNECT_TIMEOUT_SECONDS, exc
        ) from exc
    _check_server_major_version(version_num)


def _connect_args() -> dict[str, object]:
    """The bounded libpq connect_timeout applied to every psycopg
    connection made while provisioning/tearing down the ephemeral test
    database — factored out (like _test_engine_kwargs() below) so it's
    unit-testable as plain data and so tests/unit/
    test_conftest_database_setup_timeouts.py can monkeypatch
    _DB_CONNECT_TIMEOUT_SECONDS down for a fast regression test rather
    than waiting out the real production bound."""
    return {"connect_timeout": _DB_CONNECT_TIMEOUT_SECONDS}


def _test_engine_kwargs() -> dict[str, object]:
    """The pool-resilience/connection-timeout kwargs applied to both
    create_engine() calls in postgres_engine() below — factored out to a
    pure function, rather than inlined at each call site, so the settings
    are unit-testable (tests/unit/test_conftest_guards.py) as plain data
    without asserting on SQLAlchemy's own (partly private) Pool/Engine
    internals."""
    return {
        "pool_pre_ping": _TEST_ENGINE_POOL_PRE_PING,
        "pool_recycle": _TEST_ENGINE_POOL_RECYCLE_SECONDS,
        "connect_args": _connect_args(),
    }


def _redact_database_url(url: str | URL) -> str:
    """Renders `url` with any password masked. Tolerates a URL that fails
    to parse (e.g. malformed input) rather than raising — a diagnostic-
    message helper must never itself blow up and replace the real error
    it was building a message for."""
    try:
        parsed = url if isinstance(url, URL) else make_url(url)
    except Exception:
        return "<database URL (unparseable)>"
    return parsed.render_as_string(hide_password=True)


def _redact_secret(text_: str, url: str | URL) -> str:
    """Strips `url`'s literal password (if any) out of arbitrary text —
    e.g. a driver or subprocess exception's own message — as defense in
    depth beyond the redacted URL _setup_timeout_error() already builds,
    which never includes it in the first place."""
    try:
        parsed = url if isinstance(url, URL) else make_url(url)
    except Exception:
        return text_
    password = parsed.password
    if password:
        return text_.replace(password, "***")
    return text_


def _setup_timeout_error(
    action: str, url: str | URL, timeout_seconds: float, cause: BaseException
) -> DatabaseSetupTimeoutError:
    """Builds the one diagnostic message every timeout site below raises,
    so the target host/database, the bound that was exceeded, and a
    concrete remediation are always reported together — and a password
    never appears, whether from `url` itself or from the underlying
    driver/subprocess error text."""
    return DatabaseSetupTimeoutError(
        f"{action} against {_redact_database_url(url)} did not complete "
        f"within {timeout_seconds:g}s. tests/database and tests/scenario "
        "fail fast here instead of hanging indefinitely — confirm "
        "PostgreSQL is actually reachable at that host/port "
        "(docs/DEVELOPMENT.md §3: `docker compose up -d db` for the "
        "local/self-hosted default) and that DATABASE_URL/"
        "DND_AI_TEST_DATABASE_URL name the right target. "
        f"Underlying error: {_redact_secret(str(cause), url)}"
    )


def _run_bounded_subprocess(
    args: Sequence[str],
    *,
    timeout_seconds: float,
    env: dict[str, str],
    url: str | URL,
    action: str,
) -> None:
    """subprocess.run(..., check=True) with a bounded timeout, translating
    a timeout into an actionable DatabaseSetupTimeoutError. A real,
    non-timeout failure (e.g. a genuine migration error) still raises
    subprocess.CalledProcessError unchanged — only the "it never
    finished" failure mode is translated here."""
    try:
        subprocess.run(
            list(args),
            check=True,
            cwd=REPO_ROOT,
            env=env,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise _setup_timeout_error(action, url, timeout_seconds, exc) from exc


def _run_alembic_upgrade(database_url: str) -> None:
    # sys.executable -m alembic rather than the "alembic" console-script
    # entry point: identical behavior, but doesn't depend on a separate
    # PATH-resolved executable existing/being runnable at all — the
    # interpreter running this test session is already known-good.
    _run_bounded_subprocess(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        timeout_seconds=_MIGRATION_SUBPROCESS_TIMEOUT_SECONDS,
        env={**os.environ, "DATABASE_URL": database_url},
        url=database_url,
        action="alembic upgrade head",
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
    # immediately — never held open long enough to go stale, so that
    # protection would add overhead without addressing a real risk here.
    # They still get the same bounded connect_args() as every other engine
    # in this fixture, so an unreachable admin_url fails fast here too.
    admin_engine = create_engine(
        admin_url, isolation_level="AUTOCOMMIT", connect_args=_connect_args()
    )
    try:
        _require_supported_postgres(admin_engine)
        try:
            with admin_engine.connect() as conn:
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        except OperationalError as exc:
            raise _setup_timeout_error(
                "Creating the ephemeral test database",
                admin_url,
                _DB_CONNECT_TIMEOUT_SECONDS,
                exc,
            ) from exc
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
        # setup_already_failed must be read *before* attempting cleanup
        # below, while whatever exception is unwinding through this
        # `finally` (a migration timeout, a real migration error, a test
        # failure, or nothing at all) is still the active exception per
        # sys.exc_info() — cleanup's own failure must never silently
        # replace it.
        setup_already_failed = sys.exc_info()[0] is not None
        try:
            admin_engine = create_engine(
                admin_url, isolation_level="AUTOCOMMIT", connect_args=_connect_args()
            )
            try:
                with admin_engine.connect() as conn:
                    conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
            finally:
                admin_engine.dispose()
        except OperationalError as exc:
            cleanup_error = _setup_timeout_error(
                "Dropping the ephemeral test database",
                admin_url,
                _DB_CONNECT_TIMEOUT_SECONDS,
                exc,
            )
            if setup_already_failed:
                # A real setup failure is already propagating (the usual
                # case being the same unreachable-server root cause this
                # cleanup attempt just hit too) — warn instead of raising,
                # so that original exception remains what the caller sees
                # per "show the real setup cause", not this one.
                print(f"WARNING: {cleanup_error}", file=sys.stderr)
            else:
                raise cleanup_error from exc


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
