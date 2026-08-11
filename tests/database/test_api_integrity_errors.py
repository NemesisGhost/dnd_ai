"""Tests for dnd_ai.api.errors' IntegrityError classification (finding 3):
only genuine unique/exclusion-constraint conflicts are described as
retriable; not-null/foreign-key/check violations and unrecognized SQLSTATEs
both get a non-disclosing 400 that makes no retry promise. Real constraint
violations are triggered against the live test database (through the
normal get_connection/get_engine wiring), not simulated, for the two cases
Postgres itself can produce; the "unrecognized" case constructs a fake
IntegrityError directly since Postgres has no such SQLSTATE to trigger.
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

    def _make() -> TestClient:
        return TestClient(app, raise_server_exceptions=False)

    return _make


def test_unique_violation_maps_to_409_retriable_conflict(
    client_factory: Callable[[], TestClient],
) -> None:
    with client_factory() as client:
        response = client.post("/test-unique-violation")

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "conflict"
    assert "retry" in body["error"]["message"].lower()
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


def test_unrecognized_integrity_failure_is_treated_conservatively(
    client_factory: Callable[[], TestClient],
) -> None:
    """finding 3: an unrecognized SQLSTATE must not be confidently
    described as a retriable conflict — it gets the same conservative
    non-disclosing response as a plain invalid request."""
    with client_factory() as client:
        response = client.post("/test-unrecognized-integrity-error")

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "validation_failed"
    assert "retry" not in body["error"]["message"].lower()
    assert "99999" not in response.text
    assert "unrecognized failure" not in response.text
