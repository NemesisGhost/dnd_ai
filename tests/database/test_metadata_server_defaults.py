"""SQLAlchemy metadata server_default drift detection.

Split from test_phase4_remaining_issues.py (DEVELOPMENT.md §2.1).
`alembic check` does not compare server defaults (compare_server_default is
off in env.py — see tables/_shared.py's _provenance_columns() docstring),
so a metadata default that PostgreSQL would reject outright (like a bare
subquery) is otherwise invisible to CI. This walks every column in the
metadata with a text() server_default and asserts it matches what
PostgreSQL actually stores for that column.
"""

import pytest
from sqlalchemy import Connection, text

from dnd_ai.persistence.tables import metadata

pytestmark = pytest.mark.database


def _text_server_defaults() -> list[tuple[str, str, str, str]]:
    """(schema, table, column, declared default text) for every column in the
    metadata whose server_default is a text() clause. Skips columns whose
    server-side default is something else entirely (e.g. Identity()), which
    have no comparable literal text and are not this bug's shape."""
    out = []
    for table in metadata.tables.values():
        assert table.schema is not None, f"table {table.name} has no schema"
        for column in table.columns:
            default = column.server_default
            if default is None or not hasattr(default, "arg"):
                continue
            arg = default.arg
            if hasattr(arg, "text"):
                out.append((table.schema, table.name, column.name, arg.text))
    return out


@pytest.mark.parametrize("schema, table, column, declared", _text_server_defaults())
def test_metadata_server_default_matches_live_schema(
    db_connection: Connection, schema: str, table: str, column: str, declared: str
) -> None:
    actual = db_connection.execute(
        text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = :t AND column_name = :c"
        ),
        {"s": schema, "t": table, "c": column},
    ).scalar()
    assert actual == declared, (
        f"{schema}.{table}.{column}: tables.py declares default {declared!r}, "
        f"but the live schema has {actual!r} — PostgreSQL may have silently "
        f"rejected the declared form (e.g. a bare subquery is not a valid "
        f"column DEFAULT)."
    )
