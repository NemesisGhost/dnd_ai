"""Every free-text column has a data class (checkpoint 15.2A-3).

Introspects the migrated schema. A new TEXT/JSONB column in an authored or state
table without an entry in `COLUMN_CLASSES` fails here, which forces a
classification decision (and an audit/replay/projection decision) before it ships.
"""

import pytest
from sqlalchemy import Connection, text

from dnd_ai.domain.data_classification import COLUMN_CLASSES, REFERENCE_DATA_TABLES

pytestmark = pytest.mark.database

_SCHEMAS = [
    "core",
    "world",
    "character",
    "narrative",
    "knowledge",
    "campaign",
    "interaction",
    "rules",
]


def _text_columns(connection: Connection) -> set[str]:
    rows = connection.execute(
        text("""
            SELECT c.table_schema || '.' || c.table_name || '.' || c.column_name
            FROM information_schema.columns c
            JOIN pg_tables t ON t.schemaname = c.table_schema AND t.tablename = c.table_name
            WHERE c.table_schema = ANY(:schemas)
              AND c.data_type IN ('text', 'jsonb', 'character varying')
        """),
        {"schemas": _SCHEMAS},
    )
    return {str(r[0]) for r in rows}


def test_every_text_column_outside_reference_tables_is_classified(
    db_connection: Connection,
) -> None:
    columns = _text_columns(db_connection)
    unclassified = sorted(
        c
        for c in columns
        if c.rsplit(".", 1)[0] not in REFERENCE_DATA_TABLES and c not in COLUMN_CLASSES
    )
    assert not unclassified, (
        "classify these TEXT/JSONB columns in dnd_ai.domain.data_classification."
        f"COLUMN_CLASSES: {unclassified}"
    )


def test_no_classification_names_a_column_that_does_not_exist(db_connection: Connection) -> None:
    columns = _text_columns(db_connection)
    stale = sorted(c for c in COLUMN_CLASSES if c not in columns)
    assert not stale, f"COLUMN_CLASSES names columns that no longer exist: {stale}"


def test_reference_tables_exist(db_connection: Connection) -> None:
    existing = {
        f"{s}.{t}"
        for s, t in db_connection.execute(
            text("SELECT schemaname, tablename FROM pg_tables WHERE schemaname = ANY(:s)"),
            {"s": [*_SCHEMAS, "ai", "audit"]},
        )
    }
    assert existing >= REFERENCE_DATA_TABLES, sorted(REFERENCE_DATA_TABLES - existing)
