"""Tests for dnd_ai.api.errors' IntegrityError classification (findings 2
and 3): a genuine unique/exclusion conflict gets a non-disclosing 409 that
makes no retry promise; not-null/foreign-key/check violations get a
non-disclosing 400; and a missing or unrecognized SQLSTATE — not
confidently classifiable as either — gets a non-disclosing 500 internal
error rather than a guessed 400. Real constraint violations are triggered
against the live test database (through the normal get_connection/
get_engine wiring), not simulated, for the cases Postgres itself can
produce; the "unrecognized"/"missing" cases construct fake IntegrityErrors
directly since Postgres has no such SQLSTATE (or no SQLSTATE at all) to
trigger.
"""

from collections.abc import Callable
from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from dnd_ai.api.app import create_app
from dnd_ai.api.deps import get_connection, get_engine

pytestmark = pytest.mark.database


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[], TestClient]:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine

    @app.post("/test-unique-violation")
    def _unique_violation(connection: Annotated[Connection, Depends(get_connection)]) -> None:
        connection.execute(text("CREATE TEMP TABLE t_unique (id int PRIMARY KEY)"))
        connection.execute(text("INSERT INTO t_unique VALUES (1)"))
        connection.execute(text("INSERT INTO t_unique VALUES (1)"))

    @app.post("/test-check-violation")
    def _check_violation(connection: Annotated[Connection, Depends(get_connection)]) -> None:
        connection.execute(
            text("CREATE TEMP TABLE t_check (id int PRIMARY KEY, n int CHECK (n > 0))")
        )
        connection.execute(text("INSERT INTO t_check VALUES (1, -5)"))

    @app.post("/test-unrecognized-integrity-error")
    def _unrecognized_integrity_error() -> None:
        class _FakeOrig(Exception):
            sqlstate = "99999"

        raise IntegrityError("INSERT ...", {}, _FakeOrig("unrecognized failure"))

    @app.post("/test-missing-sqlstate-integrity-error")
    def _missing_sqlstate_integrity_error() -> None:
        class _FakeOrigWithoutSqlstate(Exception):
            pass

        raise IntegrityError(
            "INSERT ...", {}, _FakeOrigWithoutSqlstate("driver gave no sqlstate at all")
        )

    def _make() -> TestClient:
        return TestClient(app, raise_server_exceptions=False)

    return _make


def test_unique_violation_maps_to_409_conflict_without_a_retry_promise(
    client_factory: Callable[[], TestClient],
) -> None:
    """finding 3: a generic duplicate insertion is a genuine conflict (409)
    but not a demonstrated case where retrying the same request would
    succeed — the response must not claim retrying helps."""
    with client_factory() as client:
        response = client.post("/test-unique-violation")

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "conflict"
    assert "retry" not in body["error"]["message"].lower()
    # No constraint name, table name, SQL, or offending value in the response.
    assert "t_unique" not in response.text
    assert "duplicate key" not in response.text
    assert "23505" not in response.text


def test_check_violation_maps_to_400_non_retriable(
    client_factory: Callable[[], TestClient],
) -> None:
    with client_factory() as client:
        response = client.post("/test-check-violation")

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "validation_failed"
    assert "retry" not in body["error"]["message"].lower()
    assert "t_check" not in response.text
    assert "check constraint" not in response.text
    assert "23514" not in response.text


def test_unrecognized_integrity_failure_maps_to_500_internal_error(
    client_factory: Callable[[], TestClient],
) -> None:
    """finding 2: an unrecognized SQLSTATE is not confidently a retriable
    conflict or a plain bad request — that ambiguity is itself evidence of
    an application/schema/runtime defect, so it gets a fixed, non-disclosing
    internal error (500), never a guessed 400 or 409."""
    with client_factory() as client:
        response = client.post("/test-unrecognized-integrity-error")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "retry" not in body["error"]["message"].lower()
    assert "99999" not in response.text
    assert "unrecognized failure" not in response.text


def test_missing_sqlstate_integrity_failure_maps_to_500_internal_error(
    client_factory: Callable[[], TestClient],
) -> None:
    """finding 2: a driver exception carrying no SQLSTATE at all (not just
    an unrecognized one) gets the identical conservative 500 — the handler
    never treats "no information" as equivalent to "safe to call a 400"."""
    with client_factory() as client:
        response = client.post("/test-missing-sqlstate-integrity-error")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "retry" not in body["error"]["message"].lower()
    assert "driver gave no sqlstate at all" not in response.text
