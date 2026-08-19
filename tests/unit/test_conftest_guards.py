"""Regression tests for tests/conftest.py's fail-loud guards.

Missing database configuration and an unsupported PostgreSQL major version
must both raise, never pytest.skip() — a skip in postgres_engine() used to
let every PostgreSQL-backed test report "skipped" while pytest still exited
0, a false-green that verified nothing (see tests/conftest.py's
DatabaseConfigurationError / UnsupportedPostgresVersionError docstrings).

These test the pure, connection-free pieces the fixture is built from
directly, per docs/DEVELOPMENT.md §6: no live PostgreSQL server needed here,
matching how tests/unit/test_verify_sh.py stubs out its own external
dependencies rather than skipping when they're unavailable.
"""

from __future__ import annotations

import pytest

from tests.conftest import (
    REQUIRED_POSTGRES_MAJOR_VERSION,
    DatabaseConfigurationError,
    UnsupportedPostgresVersionError,
    _check_server_major_version,
    _missing_database_configuration_error,
    _test_engine_kwargs,
    postgres_engine,
)

pytestmark = pytest.mark.unit


def test_required_major_version_constant_is_18() -> None:
    # Pinned in docs/DATABASE_CONVENTIONS.md §2.1 — this test exists so a
    # future bump of the constant is a deliberate, visible diff here too.
    assert REQUIRED_POSTGRES_MAJOR_VERSION == 18


def test_missing_database_configuration_error_is_a_database_configuration_error() -> None:
    error = _missing_database_configuration_error()
    assert isinstance(error, DatabaseConfigurationError)


def test_missing_database_configuration_error_names_both_env_vars() -> None:
    message = str(_missing_database_configuration_error())
    assert "DATABASE_URL" in message
    assert "DND_AI_TEST_DATABASE_URL" in message


def test_missing_database_configuration_error_is_not_a_skip() -> None:
    # The regression this file exists to guard against: DatabaseConfigurationError
    # must not be (or be caught and converted into) pytest.skip.Exception —
    # that would silently resurrect the false-green this file is named for.
    error = _missing_database_configuration_error()
    assert not isinstance(error, pytest.skip.Exception)


def test_postgres_engine_fixture_raises_not_skips_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drives the real postgres_engine() fixture directly (via __wrapped__,
    which pytest.fixture() leaves callable) rather than only the extracted
    helper above — proves the fixture's own composition still raises, not
    just that the pieces it's built from would raise if used correctly.

    Deliberately does NOT use pytest.raises(DatabaseConfigurationError):
    pytest.skip() raises Skipped, a BaseException subclass that
    pytest.raises() would let propagate uncaught, and a Skipped raised from
    inside a test body — as opposed to fixture setup — marks *this test*
    as skipped rather than failed. That would silently hide exactly the
    regression this test exists to catch (a reversion to pytest.skip() in
    the fixture), so every path below ends in an explicit pytest.fail()
    unless the exact expected exception was raised.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DND_AI_TEST_DATABASE_URL", raising=False)

    generator = postgres_engine.__wrapped__()
    try:
        next(generator)
    except DatabaseConfigurationError:
        pass
    except BaseException as exc:  # noqa: BLE001 - see docstring
        pytest.fail(
            f"postgres_engine() raised {type(exc).__name__} instead of "
            f"DatabaseConfigurationError when unconfigured: {exc}"
        )
    else:
        pytest.fail("postgres_engine() did not raise when unconfigured")
    finally:
        generator.close()


def test_supported_major_version_passes_silently() -> None:
    # 180004 == PostgreSQL 18.4's server_version_num.
    _check_server_major_version(18 * 10000 + 4)


def test_supported_major_version_with_zero_minor_passes_silently() -> None:
    _check_server_major_version(18 * 10000)


@pytest.mark.parametrize("major", [10, 15, 16, 17, 19, 20])
def test_unsupported_major_version_raises(major: int) -> None:
    version_num = major * 10000 + 2  # arbitrary minor
    with pytest.raises(UnsupportedPostgresVersionError):
        _check_server_major_version(version_num)


@pytest.mark.parametrize("major", [15, 17, 19])
def test_unsupported_major_version_error_names_detected_and_required(major: int) -> None:
    version_num = major * 10000 + 7
    with pytest.raises(UnsupportedPostgresVersionError) as exc_info:
        _check_server_major_version(version_num)
    message = str(exc_info.value)
    # "Detected and required versions" per the task this guards against
    # regressing: both the server's actual major and the project's pinned
    # requirement must be legible directly from the failure message.
    assert str(major) in message
    assert str(REQUIRED_POSTGRES_MAJOR_VERSION) in message
    assert str(version_num) in message


def test_test_engine_kwargs_enables_pre_ping() -> None:
    # Regression for PR #21's CI run 31312847929 (an RDS connection gone
    # stale between checkouts, surfaced as an unrelated test's SSL error
    # ~40 minutes into the run, not a schema/constraint defect): both
    # postgres_engine() code paths must pass pool_pre_ping so a dead
    # pooled connection is detected — and transparently replaced — at
    # checkout rather than surfacing as a random test's failure.
    assert _test_engine_kwargs()["pool_pre_ping"] is True


def test_test_engine_kwargs_recycles_before_a_typical_ci_run_completes() -> None:
    # A positive recycle age, comfortably shorter than this project's CI
    # runs typically take, so long-idle connections are proactively
    # retired rather than relying on pre-ping alone to catch every case.
    recycle_seconds = _test_engine_kwargs()["pool_recycle"]
    assert isinstance(recycle_seconds, int)
    assert 0 < recycle_seconds <= 3600


def test_test_engine_kwargs_has_no_unexpected_keys() -> None:
    # Pins the contract to exactly the pool-resilience and connection-
    # timeout settings this project adds — a stray extra key here would
    # silently change create_engine()'s behavior for every test engine.
    assert set(_test_engine_kwargs()) == {"pool_pre_ping", "pool_recycle", "connect_args"}


def test_test_engine_kwargs_sets_a_bounded_connect_timeout() -> None:
    # Regression for postgres_engine() hanging indefinitely against an
    # unreachable host: every engine this fixture creates must bound how
    # long it will wait to connect, rather than the libpq default of
    # waiting forever.
    connect_args = _test_engine_kwargs()["connect_args"]
    assert isinstance(connect_args, dict)
    timeout = connect_args["connect_timeout"]
    assert isinstance(timeout, int | float)
    assert 0 < timeout <= 60
