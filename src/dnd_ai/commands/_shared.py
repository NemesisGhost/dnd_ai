"""Helpers shared across command handlers."""

import uuid

from sqlalchemy import Connection, text


class LookupCodeNotFoundError(ValueError):
    """Raised when a command references a lookup-table code that doesn't exist."""


def lookup_id(
    connection: Connection, schema: str, table: str, pk_column: str, code: str
) -> uuid.UUID:
    """Resolve a lookup table's stable `code` to its surrogate id.

    Every lookup table in this schema follows the shape in
    docs/DATABASE_CONVENTIONS.md §11: a `code` column with a unique
    constraint. Commands reference codes (readable, stable across
    environments) rather than hardcoding ids. schema/table/pk_column are
    always internal literals supplied by other command code, never
    user-controlled, so the interpolated SQL identifiers are safe.
    """
    value = connection.execute(
        text(f"SELECT {pk_column} FROM {schema}.{table} WHERE code = :code"),
        {"code": code},
    ).scalar()
    if value is None:
        raise LookupCodeNotFoundError(f"{schema}.{table} has no row with code = {code!r}")
    assert isinstance(value, uuid.UUID)
    return value
