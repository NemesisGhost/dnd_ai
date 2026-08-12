"""Tests for /healthz vs /readyz (finding 3): liveness must never depend on
the database, and readiness must prove a real round trip through the same
engine/connection wiring every other endpoint uses, failing with a fixed,
non-secret body when the database is unavailable.
"""

import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine

from dnd_ai.api.app import create_app
from dnd_ai.api.deps import get_engine

pytestmark = pytest.mark.database


@pytest.fixture
def unavailable_engine() -> Iterator[Engine]:
    # Port 1 has nothing listening on it in this test environment, so a
    # connection attempt fails fast (connection refused) rather than hanging —
    # a self-contained way to simulate "database unavailable" without
    # touching the real PostgreSQL server (docs/PLAN.md §25.6 proportional
    # test-infrastructure policy).
    engine = create_engine(
        "postgresql+psycopg://nobody:nobody@localhost:1/does-not-exist",
        connect_args={"connect_timeout": 2},
    )
    try:
        yield engine
    finally:
        engine.dispose()


def test_readyz_returns_ready_when_database_available(postgres_engine: Engine) -> None:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine
    with TestClient(app) as client:
        response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_returns_503_and_a_fixed_body_when_database_unavailable(
    unavailable_engine: Engine,
) -> None:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: unavailable_engine
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    # No connection string, host, credential, or exception text leaks into the body.
    assert "nobody" not in response.text
    assert "localhost" not in response.text
    assert "psycopg" not in response.text


def test_healthz_does_not_depend_on_the_database(unavailable_engine: Engine) -> None:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: unavailable_engine
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_failure_logging_never_includes_the_underlying_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """finding 4 regression: a simulated connection failure whose own
    exception message embeds a DSN, host, and password must never have any
    of that text end up in a captured log record — only a safe class name."""

    secret_password = "SUPER_SECRET_PW_XYZ789"

    class _FakeEngine:
        def connect(self) -> None:
            raise RuntimeError(
                "connection to server failed: FATAL: password authentication failed for "
                f'user "app" (dsn=postgresql://app:{secret_password}@dbhost.internal:5432/dnd_ai)'
            )

    app = create_app()
    app.dependency_overrides[get_engine] = lambda: _FakeEngine()
    with caplog.at_level(logging.WARNING), TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    assert secret_password not in response.text

    captured_log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert secret_password not in captured_log_text
    assert "dbhost.internal" not in captured_log_text
    assert "postgresql://" not in captured_log_text
    # The safe classification (the exception's class name) is still present.
    assert "RuntimeError" in captured_log_text
