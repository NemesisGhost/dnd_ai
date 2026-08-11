"""Tests for src/dnd_ai/api/deps.py's per-request transaction management
(docs/architecture/SYSTEM_ARCHITECTURE.md §7 "Transaction boundary") —
`get_connection` must commit a handler's writes on success and roll them
back if the handler raises, exactly like a command's own transaction does
when called directly.
"""

import uuid
from collections.abc import Callable
from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.deps import get_connection, get_engine
from tests.factories import make_user

pytestmark = pytest.mark.database


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[], TestClient]:
    """A TestClient-producing app wired to the shared test database, with a
    couple of throwaway routes that write through `get_connection` so the
    transaction boundary itself can be exercised end to end."""
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine

    @app.post("/test-commit/{display_name}")
    def _commit(
        display_name: str, connection: Annotated[Connection, Depends(get_connection)]
    ) -> dict[str, str]:
        user_id = make_user(connection, display_name)
        return {"user_id": str(user_id)}

    @app.post("/test-rollback/{display_name}")
    def _rollback(
        display_name: str, connection: Annotated[Connection, Depends(get_connection)]
    ) -> None:
        make_user(connection, display_name)
        raise ValueError("deliberate failure after the write")

    def _make() -> TestClient:
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _count_users(connection: Connection, display_name: str) -> int:
    value = connection.execute(
        text("SELECT count(*) FROM security.users WHERE display_name = :name"),
        {"name": display_name},
    ).scalar()
    assert isinstance(value, int)
    return value


def test_get_connection_commits_on_success(
    client_factory: Callable[[], TestClient], db_connection: Connection
) -> None:
    display_name = f"api-commit-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        response = client.post(f"/test-commit/{display_name}")
    assert response.status_code == 200

    # db_connection is a separate connection/transaction against the same
    # database — seeing the row here proves the request's own transaction
    # actually committed rather than merely succeeding in-process.
    assert _count_users(db_connection, display_name) == 1


def test_get_connection_rolls_back_on_handler_error(
    client_factory: Callable[[], TestClient], db_connection: Connection
) -> None:
    display_name = f"api-rollback-{uuid.uuid4().hex[:8]}"
    with client_factory() as client:
        response = client.post(f"/test-rollback/{display_name}")
    assert response.status_code == 400

    assert _count_users(db_connection, display_name) == 0
