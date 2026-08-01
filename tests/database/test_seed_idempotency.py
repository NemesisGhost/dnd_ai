"""Seed idempotency — re-seeding must be a no-op.

Required by docs/DATABASE_CONVENTIONS.md §25.6 and listed as a recurring
obligation in docs/PLAN.md §23.1. Covers the seeded lookup tables against the
YAML files that are their source of truth, so drift between the two (a code
renamed in the file but not the database, or a row added to one side only) is
caught here rather than at runtime.
"""

import pytest
from sqlalchemy import Connection, text

from dnd_ai.persistence.seeds import load_seed_data, seed_statements

pytestmark = pytest.mark.database

# Seeded lookup tables and their primary-key column.
SEEDED_LOOKUPS = [
    ("core", "canon_statuses", "canon_status_id"),
    ("core", "lifecycle_statuses", "lifecycle_status_id"),
    ("core", "source_types", "source_type_id"),
]


def _reseed(connection: Connection, schema: str, table: str) -> None:
    """Re-apply a seed file through the same statements a migration would use."""
    for statement in seed_statements(schema, table):
        connection.execute(statement)


def _snapshot(connection: Connection, schema: str, table: str, pk: str) -> list[tuple[object, ...]]:
    rows = connection.execute(
        text(
            f"SELECT {pk}, code, display_name, description, sort_order, is_active "
            f"FROM {schema}.{table} ORDER BY code"
        )
    ).fetchall()
    return [tuple(r) for r in rows]


@pytest.mark.parametrize(("schema", "table", "pk"), SEEDED_LOOKUPS)
def test_database_matches_seed_file(
    db_connection: Connection, schema: str, table: str, pk: str
) -> None:
    """Every code in the seed file is present, and nothing extra is."""
    expected = {row["code"] for row in load_seed_data(schema, table)}
    actual = {r[0] for r in db_connection.execute(text(f"SELECT code FROM {schema}.{table}"))}
    assert actual == expected


@pytest.mark.parametrize(("schema", "table", "pk"), SEEDED_LOOKUPS)
def test_reseeding_changes_nothing(
    db_connection: Connection, schema: str, table: str, pk: str
) -> None:
    """Applying the seed to an already-seeded table leaves every row untouched.

    Runs inside the fixture's transaction, so it rolls back regardless of outcome.
    """
    before = _snapshot(db_connection, schema, table, pk)
    _reseed(db_connection, schema, table)
    after = _snapshot(db_connection, schema, table, pk)

    assert after == before, (
        f"Re-seeding {schema}.{table} changed its contents. Seeds must be "
        "idempotent (conventions §25.6) — check the ON CONFLICT target."
    )


@pytest.mark.parametrize(("schema", "table", "pk"), SEEDED_LOOKUPS)
def test_reseeding_does_not_duplicate_rows(
    db_connection: Connection, schema: str, table: str, pk: str
) -> None:
    count_before = db_connection.execute(text(f"SELECT count(*) FROM {schema}.{table}")).scalar()
    _reseed(db_connection, schema, table)
    _reseed(db_connection, schema, table)
    count_after = db_connection.execute(text(f"SELECT count(*) FROM {schema}.{table}")).scalar()

    assert count_after == count_before
