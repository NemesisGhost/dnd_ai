"""Alembic environment configuration.

This module configures the Alembic migration environment according to the project
conventions in docs/DATABASE_CONVENTIONS.md §25 and docs/DEVELOPMENT.md §4.

Key settings:
- version_table_schema = "core" (no tables in public)
- include_schemas = True (autogenerate sees all thirteen bounded schemas)
- Connection URL read from environment, never hardcoded
"""

import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import MetaData, create_engine, pool, text

# Load .env from the repo root (or nearest parent) so the workflow in
# docs/DEVELOPMENT.md §3 — "cp .env.example .env, then edit" — actually takes
# effect here. A no-op if no .env file is found.
load_dotenv()

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate support.
# `alembic check` (run in CI) requires a MetaData object even before any table
# metadata exists — an empty one correctly reports "no diff" until
# src/dnd_ai/persistence/ starts registering real tables here.
target_metadata = MetaData()


# Database URL from environment
def get_url() -> str:
    """
    Get database URL from environment variable.

    This function is separate so tests can override it if needed.
    Defaults to the local Docker container described in docs/DEVELOPMENT.md §3.
    """
    return os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/dnd_ai",
    )


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine. By skipping
    the Engine creation we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the script output.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Critical: autogenerate must see all schemas, not just public
        include_schemas=True,
        # Version table lives in core schema per alembic.ini
        version_table_schema="core",
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    In this scenario we create an Engine and associate a connection with the
    context. This is the standard mode for development and deployment.
    """
    url = get_url()

    connectable = create_engine(
        url,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # The alembic_version table lives in `core` (version_table_schema below),
        # but on a brand-new database `core` doesn't exist until revision
        # 001_bootstrap runs. Alembic creates the version table before running
        # any revision, so the schema must exist first.
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS core;"))
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Critical: autogenerate must see all schemas, not just public
            include_schemas=True,
            # Version table lives in core schema per alembic.ini
            version_table_schema="core",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
