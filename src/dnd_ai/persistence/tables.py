"""SQLAlchemy Core table metadata.

This is the single `MetaData` that `alembic check` compares against the live
database, so it must stay in step with the migrations — a table added in a
revision and not declared here shows up as a spurious "remove_table" diff and
fails CI. That comparison is the point: it is what proves migrations and
application metadata agree (docs/DEVELOPMENT.md §8).

Core, not the ORM, per docs/DEVELOPMENT.md §1 — the domain model is
class-table inheritance across bounded schemas with typed state tables, and an
ORM identity map fights that more than it helps.

What autogenerate compares is declared here: tables, columns, types,
nullability, primary keys, foreign keys, indexes, and **comments** — Alembic
compares comments unconditionally, with no opt-out. That means every comment
appears both here and in the migration that creates it. The duplication is
deliberate rather than unfortunate: `alembic check` fails the moment the two
disagree, so drift is loud instead of silent. Sharing one constant between
them is not an option, because a migration must produce the same result on
every replay and cannot depend on a value that later edits can change.

CHECK constraints, triggers, and default privileges are *not* declared here.
Alembic does not compare them, so listing them would add maintenance with no
enforcement behind it. They are covered by tests instead — see
tests/database/test_core_lookups_and_security.py and test_role_grants.py.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import DOMAIN, TIMESTAMP, UUID
from sqlalchemy.types import Integer

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


# ---------------------------------------------------------------------------
# core — platform lookups (revision 003)
# ---------------------------------------------------------------------------

canon_statuses = _lookup_table(
    "core",
    "canon_statuses",
    "canon_status_id",
    "How authoritative a definition is. Independent of lifecycle status — "
    "see docs/ENTITY_LIFECYCLE.md §2.",
)
lifecycle_statuses = _lookup_table(
    "core",
    "lifecycle_statuses",
    "lifecycle_status_id",
    "Whether an entity is currently usable by the platform. Independent of "
    "canon status — see docs/ENTITY_LIFECYCLE.md §2.",
)
source_types = _lookup_table(
    "core",
    "source_types",
    "source_type_id",
    "Where an authored or imported fact came from — see docs/PLAN.md §4.5.",
)


# ---------------------------------------------------------------------------
# security (revision 003)
# ---------------------------------------------------------------------------

users = Table(
    "users",
    metadata,
    _uuid_pk("user_id"),
    Column("username", Text(), nullable=False),
    Column(
        "email",
        Text(),
        comment="Nullable: service-linked or imported accounts may have no address.",
    ),
    Column("display_name", Text(), nullable=False),
    Column("is_active", Boolean(), nullable=False, server_default=text("true")),
    *_timestamps(),
    UniqueConstraint("username", name="ux_users_username"),
    schema="security",
    comment=(
        "A person who can author or approve world content. Authentication itself "
        "is handled outside the database; this is identity for attribution and "
        "authorization."
    ),
)

roles = Table(
    "roles",
    metadata,
    _uuid_pk("role_id"),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    Column("sort_order", NONNEGATIVE_INTEGER, nullable=False, server_default=text("0")),
    Column("is_active", Boolean(), nullable=False, server_default=text("true")),
    *_timestamps(),
    UniqueConstraint("code", name="ux_roles_code"),
    schema="security",
    comment=(
        "Platform-level role a user can hold. Intentionally unseeded: the role "
        "vocabulary is not yet specified in the domain docs, and inventing it "
        "here would preempt that decision."
    ),
)

user_roles = Table(
    "user_roles",
    metadata,
    Column(
        "user_id",
        UUID(),
        ForeignKey("security.users.user_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "role_id",
        UUID(),
        ForeignKey("security.roles.role_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("granted_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column(
        "granted_by_user_id",
        UUID(),
        ForeignKey("security.users.user_id", ondelete="SET NULL"),
    ),
    PrimaryKeyConstraint("user_id", "role_id"),
    schema="security",
    comment=(
        "Role assignment. ON DELETE RESTRICT against roles so a role in use "
        "cannot be removed out from under its holders."
    ),
)

# Index every foreign key (§19.1). user_id is already covered as the leading
# column of the composite primary key.
Index("ix_user_roles_role_id", user_roles.c.role_id)
Index("ix_user_roles_granted_by_user_id", user_roles.c.granted_by_user_id)
