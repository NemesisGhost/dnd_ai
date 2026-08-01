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
from sqlalchemy import Connection, MetaData, create_engine, pool, text

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


def _set_role_if_bootstrapped(connection: Connection, role: str) -> None:
    """
    SET ROLE to `role`, but only if 001_bootstrap has already completed in the
    CURRENT database.

    `role` (migration_owner) is cluster-wide in PostgreSQL, so checking that it
    exists and that the current user is a member of it is not enough — both
    can be true on a database where 001_bootstrap has never run, because every
    database on the same instance shares the same roles. The ephemeral
    per-test-run databases in docs/PLAN.md §29.9 are exactly this case: fresh
    per database, but talking to an instance where migration_owner has already
    been created for some other database. Switching role there, before
    granting it anything in *this* database, made Alembic's own
    CREATE TABLE core.alembic_version fail with "permission denied for schema
    core" — verified against a real RDS instance.

    core.alembic_version existing is a reasonable proxy for "bootstrap has run
    here": Alembic creates it (as whichever role is active at the time, i.e.
    the connecting user) before any revision executes, so its presence means
    a prior invocation reached at least that point in this specific database.
    """
    bootstrapped = connection.execute(text("SELECT to_regclass('core.alembic_version')")).scalar()
    if not bootstrapped:
        return

    exists = connection.execute(
        text("SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = :role"), {"role": role}
    ).scalar()
    if not exists:
        return

    is_member = connection.execute(
        text("SELECT pg_has_role(current_user, :role, 'MEMBER')"), {"role": role}
    ).scalar()
    if is_member:
        # Role names here are project constants, not user input.
        connection.execute(text(f"SET ROLE {role}"))


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

        # Everything this project creates is owned by migration_owner, never by
        # whoever happens to be connected (the RDS master user in dev, the
        # migration_runner role when deployed). PostgreSQL takes ownership from
        # the current role rather than from inherited membership, so becoming
        # the role is the only way to get that — and it also makes the
        # ALTER DEFAULT PRIVILEGES entries keyed to migration_owner actually
        # apply. See docs/adr/0009-separate-owning-role-from-login-roles.md.
        #
        # Skipped when 001_bootstrap has not yet completed in this database
        # (see _set_role_if_bootstrapped) — that revision grants migration_owner
        # what it needs here and issues its own SET ROLE once it has.
        _set_role_if_bootstrapped(connection, "migration_owner")
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
