"""Pytest configuration and shared fixtures.

Per docs/PLAN.md §23.0 and ADR 0011: tests/database and tests/scenario run
against a local PostgreSQL server by default — the same major version the
project deploys (docs/DATABASE_CONVENTIONS.md §2.1). CI runs the identical
suites against the deployed AWS dev RDS instance as the merge gate
(docs/PLAN.md §29.9); this fixture does not distinguish between the two,
because there is nothing target-specific left to distinguish. Whatever
DATABASE_URL points at — local or dev — is treated as an admin/bootstrap
connection with CREATEDB. Each test session creates its own throwaway
database on it (dnd_ai_test_<random>), migrates it to head, and drops it
afterward. Opening network access to a remote target (dev) is
scripts/aws-db-allow-my-ip.sh's job, not this fixture's.

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
    Session-scoped engine pointed at a throwaway database migrated to head,
    provisioned on whatever DATABASE_URL names — a local PostgreSQL server by
    default, or the AWS dev endpoint when that's what's configured.
    """
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
            "DATABASE_URL is not set — point it at a local PostgreSQL server "
            "per docs/DEVELOPMENT.md §3 (or the AWS dev endpoint per §3.5)."
        )

    admin_url = make_url(admin_url_raw)
    db_name = f"dnd_ai_test_{uuid.uuid4().hex[:12]}"
    test_url = admin_url.set(database=db_name)

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()

    # Everything from here must be inside try/finally: a failed migration
    # (which happened during development of this fixture) must not leave the
    # database it just created behind — orphans accumulate on a shared
    # instance otherwise, silently, since nothing else ever lists them.
    try:
        _run_alembic_upgrade(test_url.render_as_string(hide_password=False))

        engine = create_engine(test_url)
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
