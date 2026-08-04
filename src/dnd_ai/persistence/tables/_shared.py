"""Shared SQLAlchemy Core metadata, domains, and table-building helpers.

The one `MetaData` instance every domain module in this package attaches
its tables to, plus the column/comment helpers shared across them. See
src/dnd_ai/persistence/tables/__init__.py for why this metadata's shape
matters (the `alembic check` comparison).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import DOMAIN, TIMESTAMP, UUID
from sqlalchemy.types import Integer, SmallInteger

metadata = MetaData()

# Shared domains from revision 002. Declared with create_type=False because the
# migration owns their lifecycle; this is only so autogenerate recognises the
# column type rather than reporting a diff against it.
NONNEGATIVE_INTEGER = DOMAIN(
    "nonnegative_integer",
    Integer(),
    schema="core",
    create_type=False,
)
RATING_1_10 = DOMAIN(
    "rating_1_10",
    SmallInteger(),
    schema="core",
    create_type=False,
)
PERCENTAGE_0_100 = DOMAIN(
    "percentage_0_100",
    SmallInteger(),
    schema="core",
    create_type=False,
)


def _uuid_pk(name: str) -> Column[uuid.UUID]:
    return Column(name, UUID(), primary_key=True, server_default=text("gen_random_uuid()"))


def _timestamps() -> list[Column[datetime]]:
    return [
        Column(
            "created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
        ),
        Column(
            "updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
        ),
    ]


def _provenance_columns() -> list[Column[uuid.UUID]]:
    """source_id + canon_status_id, added to every rule-content table by
    revision 025. Must match that revision's COMMENT ON COLUMN text exactly."""
    return [
        Column(
            "source_id",
            UUID(),
            ForeignKey("core.sources.source_id", ondelete="SET NULL"),
            comment=(
                "Where this definition came from — a rulebook, a homebrew document, an "
                "import. NULL is common for official content with no single authored "
                "source record yet."
            ),
        ),
        Column(
            "canon_status_id",
            UUID(),
            ForeignKey("core.canon_statuses.canon_status_id", ondelete="RESTRICT"),
            nullable=False,
            # Not compared by alembic check (compare_server_default is off in
            # env.py), declared here only for readers of this module: defaults
            # to 'canon' via rules.default_canon_status_id(), since most rule
            # content is officially authored — see revision 025's reasoning.
            server_default=text("rules.default_canon_status_id()"),
            comment=(
                "How authoritative this definition is. Homebrew content uses the same "
                "column, typically starting at draft/proposed rather than canon "
                "(docs/architecture/DATABASE_MODEL.md §8)."
            ),
        ),
    ]


# Must match the COMMENT ON COLUMN text in revision 003 exactly.
LOOKUP_CODE_COMMENT = (
    "Stable machine-readable identifier. Application logic may reference "
    "codes, but foreign keys use IDs (conventions §11.1)."
)


def _lookup_table(schema: str, name: str, pk: str, comment: str) -> Table:
    """A platform lookup table in the shape of DATABASE_CONVENTIONS.md §11."""
    return Table(
        name,
        metadata,
        _uuid_pk(pk),
        Column("code", Text(), nullable=False, comment=LOOKUP_CODE_COMMENT),
        Column("display_name", Text(), nullable=False),
        Column("description", Text()),
        Column(
            "sort_order",
            NONNEGATIVE_INTEGER,
            nullable=False,
            server_default=text("0"),
        ),
        Column("is_active", Boolean(), nullable=False, server_default=text("true")),
        *_timestamps(),
        UniqueConstraint("code", name=f"ux_{name}_code"),
        schema=schema,
        comment=comment,
    )
