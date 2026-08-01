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
from sqlalchemy import Connection, create_engine, pool, text

from dnd_ai.persistence.tables import metadata as target_metadata

# Load .env from the repo root (or nearest parent) so the workflow in
# docs/DEVELOPMENT.md §3 — "cp .env.example .env, then edit" — actually takes
# effect here. A no-op if no .env file is found.
load_dotenv()

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate support — the real table definitions from
# src/dnd_ai/persistence/tables.py, imported above.
#
# This was an empty MetaData() through Phase 1, which was correct only while
# the database had no tables: once revision 003 created some, autogenerate
# compared them against nothing and reported every one as a table to drop.
# Any table added by a migration must also be declared in tables.py, and CI's
# `alembic check` step is what enforces that.


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


def _set_role_if_usable(connection: Connection, role: str) -> None:
    """
    SET ROLE to `role`, but only if doing so would actually work here.

    Three things must hold, and each guards a failure seen against real RDS:

    1. The role exists. It does not before 001_bootstrap first runs, and
       `pg_has_role` raises rather than returning false for an unknown role.
    2. The connected user is a member of it, or SET ROLE is refused.
    3. The role holds USAGE and CREATE on `core` **in this database**.

    (3) is the subtle one, and a plain "has 001_bootstrap run?" check is not a
    substitute for it. Roles are cluster-wide while schemas and grants are
    per-database, so `role` can exist — created for some entirely different
    database on the same instance — while having no privileges at all here.
    Two situations produce exactly that:

    - A fresh ephemeral test database (docs/PLAN.md §29.9) on an instance
      where another database is already bootstrapped. Switching role there
      made Alembic's own CREATE TABLE core.alembic_version fail with
      "permission denied for schema core".
    - A database downgraded to base on a shared instance. 001_bootstrap's
      downgrade revokes the role's privileges and hands `core` back, but now
      deliberately keeps the role itself when another database still needs it
      — so the role survives with no access, and the next upgrade would fail
      the same way.

    Checking the privilege directly covers both, and needs no proxy for
    migration state.
    """
    exists = connection.execute(
        text("SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = :role"), {"role": role}
    ).scalar()
    if not exists:
        return

    usable = connection.execute(
        text("""
            SELECT pg_has_role(current_user, :role, 'MEMBER')
               AND has_schema_privilege(:role, 'core', 'USAGE')
               AND has_schema_privilege(:role, 'core', 'CREATE')
        """),
        {"role": role},
    ).scalar()
    if usable:
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
        # Skipped when the role cannot actually be used in this database yet
        # (see _set_role_if_usable) — 001_bootstrap grants migration_owner what
        # it needs here and issues its own SET ROLE once it has.
        _set_role_if_usable(connection, "migration_owner")
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
