"""Regression tests for tests/conftest.py's bounded database-setup
timeouts: an unreachable PostgreSQL host and a stuck Alembic subprocess
must both fail fast with an actionable, credential-redacted diagnosis
instead of hanging postgres_engine() (and the pytest run/CI job around it)
indefinitely.

Runs entirely without a live PostgreSQL server or a real Alembic
invocation, per docs/DEVELOPMENT.md §6 (unit tests use no database) — the
"unreachable host" scenario is simulated with a local TCP listener that
completes the handshake but never speaks the PostgreSQL protocol back, and
the "hanging subprocess" scenario uses a real `python -c "time.sleep(...)"`
child process (not a mock), so both regressions exercise the real bounded-
timeout mechanism rather than only asserting on stubbed control flow.
"""

from __future__ import annotations

import os
import socket
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine

from tests.conftest import (
    DatabaseSetupTimeoutError,
    _connect_args,
    _redact_database_url,
    _redact_secret,
    _require_supported_postgres,
    _run_bounded_subprocess,
    _setup_timeout_error,
)

pytestmark = pytest.mark.unit

# Generous relative to the 2s connect_timeout/1s subprocess timeout the
# tests below configure — proves "fails within a short bound", not merely
# "eventually fails". Still small next to what an actual hang (an
# unbounded libpq wait, or a subprocess with no timeout at all) would take
# — anywhere from tens of seconds to indefinite.
_SHORT_BOUND_SECONDS = 15.0

_FAKE_PASSWORD = "s3cr3t-pw-must-never-appear-in-a-message"  # noqa: S105 - test fixture, not a real credential


@contextmanager
def _silent_listener() -> Iterator[int]:
    """A TCP server socket that completes the handshake for any connecting
    client (the OS auto-ACKs up to the listen backlog even before
    anything calls accept()) but never sends a single byte back —
    simulating an unreachable/hanging PostgreSQL server without depending
    on network-blackhole IPs, firewall behavior, or a real installation.
    libpq's connect_timeout covers this: it bounds the full connection
    handshake (through backend startup), not just the initial TCP
    SYN/ACK, so a server that accepts but never responds is timed out
    exactly like one that never accepts at all."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    try:
        yield server.getsockname()[1]
    finally:
        server.close()


def test_unreachable_postgres_fails_fast_with_redacted_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Read at call time by _connect_args(), so this takes effect without
    # waiting out the real 10s production default.
    monkeypatch.setattr("tests.conftest._DB_CONNECT_TIMEOUT_SECONDS", 2)

    with _silent_listener() as port:
        url = f"postgresql+psycopg://postgres:{_FAKE_PASSWORD}@127.0.0.1:{port}/dnd_ai"
        engine = create_engine(url, connect_args=_connect_args())
        start = time.monotonic()
        try:
            with pytest.raises(DatabaseSetupTimeoutError) as exc_info:
                _require_supported_postgres(engine)
        finally:
            elapsed = time.monotonic() - start
            engine.dispose()

    # Fails within a short bound, not by hanging.
    assert elapsed < _SHORT_BOUND_SECONDS, (
        f"took {elapsed:.1f}s to fail — connect_timeout did not actually bound this connection"
    )

    message = str(exc_info.value)
    # Shows the real setup cause: what failed, against what, and how to fix it.
    assert "127.0.0.1" in message
    assert str(port) in message
    assert "PostgreSQL" in message
    assert "docker compose" in message or "DATABASE_URL" in message
    # Redacts credentials: never the raw password, anywhere in the message.
    assert _FAKE_PASSWORD not in message


def test_hanging_alembic_style_subprocess_fails_fast_with_redacted_diagnostic() -> None:
    # A real child process that would hang far longer than the bound below
    # if not for subprocess.run(timeout=...) — not a mock of the timeout
    # mechanism, an actual exercise of it, standing in for a stuck
    # `alembic upgrade head` without needing a real Alembic invocation or
    # a live database for it to hang against.
    hang_command = [sys.executable, "-c", "import time; time.sleep(60)"]
    fake_url = f"postgresql+psycopg://postgres:{_FAKE_PASSWORD}@127.0.0.1:5432/dnd_ai_test_fake"

    start = time.monotonic()
    with pytest.raises(DatabaseSetupTimeoutError) as exc_info:
        _run_bounded_subprocess(
            hang_command,
            timeout_seconds=1,
            env=dict(os.environ),
            url=fake_url,
            action="alembic upgrade head",
        )
    elapsed = time.monotonic() - start

    # Fails within a short bound, not by hanging for the full 60s sleep.
    assert elapsed < _SHORT_BOUND_SECONDS, (
        f"took {elapsed:.1f}s to fail — the subprocess timeout did not actually bound this"
    )

    message = str(exc_info.value)
    # Shows the real setup cause.
    assert "alembic upgrade head" in message
    assert "did not complete" in message
    assert "1s" in message
    # Redacts credentials: never the raw password or an unredacted URL.
    assert _FAKE_PASSWORD not in message
    assert "***" in message


def test_redact_database_url_masks_the_password() -> None:
    url = f"postgresql+psycopg://postgres:{_FAKE_PASSWORD}@db.example:5432/dnd_ai"
    redacted = _redact_database_url(url)
    assert _FAKE_PASSWORD not in redacted
    assert "db.example" in redacted


def test_redact_database_url_tolerates_unparseable_input() -> None:
    # A diagnostic-message helper must never itself raise and replace the
    # real error it was building a message for.
    assert "unparseable" in _redact_database_url("not a valid url::::")


def test_redact_secret_strips_the_password_out_of_arbitrary_text() -> None:
    url = f"postgresql+psycopg://postgres:{_FAKE_PASSWORD}@db.example:5432/dnd_ai"
    driver_message = f"connection failed: password was '{_FAKE_PASSWORD}'"
    redacted = _redact_secret(driver_message, url)
    assert _FAKE_PASSWORD not in redacted
    assert "***" in redacted


def test_redact_secret_is_a_no_op_for_a_passwordless_url() -> None:
    url = "postgresql+psycopg://postgres@db.example:5432/dnd_ai"
    driver_message = "connection refused"
    assert _redact_secret(driver_message, url) == driver_message


def test_setup_timeout_error_message_never_contains_the_password() -> None:
    url = f"postgresql+psycopg://postgres:{_FAKE_PASSWORD}@db.example:5432/dnd_ai"
    cause = RuntimeError(f"driver said: {_FAKE_PASSWORD}")
    error = _setup_timeout_error("Connecting to PostgreSQL", url, 10, cause)
    assert isinstance(error, DatabaseSetupTimeoutError)
    assert _FAKE_PASSWORD not in str(error)
    assert "db.example" in str(error)
