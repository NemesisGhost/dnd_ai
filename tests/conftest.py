"""Pytest configuration and shared fixtures.

Provides a session-scoped PostgreSQL testcontainer with migrations applied, for
tests/database and tests/scenario per docs/DEVELOPMENT.md §6. tests/unit must
not depend on any fixture here — it runs with no database.

Markers (unit, database, scenario) are registered in pyproject.toml, not here.
"""

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, create_engine
from testcontainers.community.postgres import PostgresContainer

REPO_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = REPO_ROOT / "database" / "alembic.ini"


@pytest.fixture(scope="session")
def postgres_engine() -> Iterator[Engine]:
    """
    Spin up a disposable postgres:15 container and apply all migrations.

    Matches the deployed major version per docs/DEVELOPMENT.md §1. Torn down
    automatically when the container context manager exits.
    """
    with PostgresContainer("postgres:15") as postgres:
        database_url = postgres.get_connection_url(driver="psycopg")

        subprocess.run(
            ["alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
            check=True,
            cwd=REPO_ROOT,
            env={**os.environ, "DATABASE_URL": database_url},
        )

        engine = create_engine(database_url)
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def db_connection(postgres_engine: Engine) -> Iterator[Connection]:
    """
    Function-scoped connection wrapped in a transaction that always rolls back,
    so tests never leak state into each other via the shared session container.
    """
    with postgres_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()
