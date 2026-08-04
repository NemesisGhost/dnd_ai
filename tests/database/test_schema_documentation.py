"""Every table carries a comment (docs/DATABASE_CONVENTIONS.md §31).

`alembic check` compares comments between the live database and the
dnd_ai.persistence.tables package (src/dnd_ai/persistence/tables/). These
catalog-level assertions complement that comparison by requiring every
project-owned schema and table to have a comment at all, including objects
accidentally omitted from metadata.

Deliberately queries the catalog rather than a hardcoded table list, so a new
table added in a later phase is covered the moment it exists.
"""

import pytest
from sqlalchemy import Connection, text

pytestmark = pytest.mark.database

# Bounded schemas this project owns (docs/PLAN.md §3). `public` is excluded —
# nothing of ours goes there (§3.1).
PROJECT_SCHEMAS = (
    "core",
    "security",
    "rules",
    "character",
    "world",
    "campaign",
    "narrative",
    "knowledge",
    "interaction",
    "ai",
    "audit",
    "import",
    "integration",
)

# Alembic owns this one; it is not ours to document.
EXEMPT_TABLES = {("core", "alembic_version")}


def test_every_table_has_a_comment(db_connection: Connection) -> None:
    undocumented = [
        (schema, table)
        for schema, table in db_connection.execute(
            text("""
                SELECT n.nspname, c.relname
                FROM pg_class c
                JOIN pg_namespace n ON c.relnamespace = n.oid
                WHERE c.relkind = 'r'
                  AND n.nspname = ANY(:schemas)
                  AND obj_description(c.oid, 'pg_class') IS NULL
                ORDER BY 1, 2
            """),
            {"schemas": list(PROJECT_SCHEMAS)},
        )
        if (schema, table) not in EXEMPT_TABLES
    ]

    assert not undocumented, (
        "Tables without a comment (conventions §31 requires one in the same "
        f"revision that creates the table): {undocumented}"
    )


def test_every_schema_has_a_comment(db_connection: Connection) -> None:
    undocumented = [
        row[0]
        for row in db_connection.execute(
            text("""
                SELECT n.nspname
                FROM pg_namespace n
                WHERE n.nspname = ANY(:schemas)
                  AND obj_description(n.oid, 'pg_namespace') IS NULL
                ORDER BY 1
            """),
            {"schemas": list(PROJECT_SCHEMAS)},
        )
    ]
    assert not undocumented, f"Schemas without a comment: {undocumented}"


def test_every_foreign_key_is_indexed(db_connection: Connection) -> None:
    """PostgreSQL does not index FK columns automatically (§19.1).

    A leading-column match counts: a composite index on (a, b) covers an FK
    on a.
    """
    unindexed = [
        (row[0], row[1], row[2])
        for row in db_connection.execute(
            text("""
                SELECT n.nspname, t.relname, con.conname
                FROM pg_constraint con
                JOIN pg_class t ON con.conrelid = t.oid
                JOIN pg_namespace n ON t.relnamespace = n.oid
                WHERE con.contype = 'f'
                  AND n.nspname = ANY(:schemas)
                  AND NOT EXISTS (
                      SELECT 1
                      FROM pg_index i
                      WHERE i.indrelid = con.conrelid
                        AND (i.indkey::smallint[])[0:array_length(con.conkey, 1) - 1]
                            @> con.conkey[1:1]
                  )
                ORDER BY 1, 2, 3
            """),
            {"schemas": list(PROJECT_SCHEMAS)},
        )
    ]

    assert not unindexed, f"Foreign keys with no supporting index (conventions §19.1): {unindexed}"
