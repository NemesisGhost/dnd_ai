"""Pytest configuration and shared fixtures.

Primary path, per docs/PLAN.md §23.0 and §29.9: tests/database and
tests/scenario run against the deployed AWS dev RDS instance, not a local
stand-in. Each test session creates its own throwaway database on that shared
instance (dnd_ai_test_<random>), migrates it to head, and drops it afterward —
real isolation on shared infrastructure without a database per developer.
DATABASE_URL must already point at a connectable admin/bootstrap connection on
the dev instance (one with CREATEDB) — opening network access to it is
scripts/aws-db-allow-my-ip.sh's job, not this fixture's.

Fallback only: set DND_AI_USE_LOCAL_POSTGRES=1 for a local testcontainers
PostgreSQL instead, when AWS is genuinely unreachable (docs/DEVELOPMENT.md §3).

If a caller has already created and migrated a database for this run — CI
does, to share one ephemeral database across its migration checks and the
pytest run rather than creating a second one here — set
DND_AI_TEST_DATABASE_URL to it and this fixture connects directly instead of
provisioning its own.

tests/unit must not depend on any fixture here — it runs with no database.
Markers (unit, database, scenario) are registered in pyproject.toml, not here.
"""

import os
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from dotenv import load_dotenv
from sqlalchemy import Connection, Engine, create_engine, make_url, text

REPO_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = REPO_ROOT / "database" / "alembic.ini"

load_dotenv()


def _run_alembic_upgrade(database_url: str) -> None:
    subprocess.run(
        ["alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        check=True,
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
    )


@pytest.fixture(scope="session")
def postgres_engine() -> Iterator[Engine]:
    """
    Session-scoped engine pointed at a throwaway database migrated to head —
    on the AWS dev instance by default, or a local testcontainer as an
    explicit fallback (DND_AI_USE_LOCAL_POSTGRES=1).
    """
    if os.environ.get("DND_AI_USE_LOCAL_POSTGRES"):
        yield from _local_postgres_engine()
        return

    preprovisioned_url = os.environ.get("DND_AI_TEST_DATABASE_URL")
    if preprovisioned_url:
        engine = create_engine(preprovisioned_url)
        try:
            yield engine
        finally:
            engine.dispose()
        return

    admin_url_raw = os.environ.get("DATABASE_URL")
    if not admin_url_raw:
        pytest.skip(
            "DATABASE_URL is not set — point it at the AWS dev endpoint per "
            "docs/DEVELOPMENT.md §3, or set DND_AI_USE_LOCAL_POSTGRES=1 for "
            "the local fallback."
        )

    admin_url = make_url(admin_url_raw)
    db_name = f"dnd_ai_test_{uuid.uuid4().hex[:12]}"
    test_url = admin_url.set(database=db_name)

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()

    _run_alembic_upgrade(test_url.render_as_string(hide_password=False))

    engine = create_engine(test_url)
    try:
        yield engine
    finally:
        engine.dispose()
        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        admin_engine.dispose()


def _local_postgres_engine() -> Iterator[Engine]:
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:15") as postgres:
        database_url = postgres.get_connection_url(driver="psycopg")
        _run_alembic_upgrade(database_url)

        engine = create_engine(database_url)
        try:
            yield engine
        finally:
            engine.dispose()


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
