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


# ---------------------------------------------------------------------------
# core — worlds, entity types, entities, sources (revision 004)
# ---------------------------------------------------------------------------

worlds = Table(
    "worlds",
    metadata,
    _uuid_pk("world_id"),
    Column("name", Text(), nullable=False),
    Column(
        "slug",
        Text(),
        nullable=False,
        comment="Stable URL-safe identifier. Distinct from name, which may be renamed freely.",
    ),
    Column("description", Text()),
    Column(
        "lifecycle_status_id",
        UUID(),
        ForeignKey("core.lifecycle_statuses.lifecycle_status_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    *_timestamps(),
    UniqueConstraint("slug", name="ux_worlds_slug"),
    schema="core",
    comment=(
        "A persistent fictional setting. Owns entity definitions, calendars, and "
        "timelines; outlives any individual campaign."
    ),
)

entity_types = Table(
    "entity_types",
    metadata,
    _uuid_pk("entity_type_id"),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    Column(
        "parent_entity_type_id",
        UUID(),
        ForeignKey("core.entity_types.entity_type_id", ondelete="RESTRICT"),
    ),
    Column(
        "required_subtype_table",
        Text(),
        comment=(
            "Schema-qualified subtype table an entity of this type must have a row in, "
            'e.g. "character.npcs". NULL for types with no subtype table. Enforced by '
            "core.enforce_entity_subtype()."
        ),
    ),
    Column(
        "is_abstract",
        Boolean(),
        nullable=False,
        server_default=text("false"),
        comment=(
            "True when no entity may be created with this type directly — it exists only "
            "as a parent of concrete types."
        ),
    ),
    *_timestamps(),
    UniqueConstraint("code", name="ux_entity_types_code"),
    schema="core",
    comment=(
        "The allowed entity type hierarchy. Each phase registers the types it "
        "builds; rows are not seeded ahead of the subtype tables they name."
    ),
)

sources = Table(
    "sources",
    metadata,
    _uuid_pk("source_id"),
    Column(
        "world_id",
        UUID(),
        ForeignKey("core.worlds.world_id", ondelete="CASCADE"),
        comment=(
            "NULL for sources that are not world-specific, such as a published rulebook "
            "shared across every world."
        ),
    ),
    Column(
        "source_type_id",
        UUID(),
        ForeignKey("core.source_types.source_type_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("title", Text(), nullable=False),
    Column(
        "reference",
        Text(),
        comment="Locator within the source — page number, URL, message id, timestamp.",
    ),
    Column("description", Text()),
    Column(
        "created_by_user_id",
        UUID(),
        ForeignKey("security.users.user_id", ondelete="SET NULL"),
    ),
    *_timestamps(),
    schema="core",
    comment=(
        "Where an authored or imported fact came from. Every meaningful authored "
        "record should reference one where practical (docs/PLAN.md §4.5)."
    ),
)

entities = Table(
    "entities",
    metadata,
    _uuid_pk("entity_id"),
    Column(
        "world_id",
        UUID(),
        ForeignKey("core.worlds.world_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "entity_type_id",
        UUID(),
        ForeignKey("core.entity_types.entity_type_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("canonical_name", Text(), nullable=False),
    Column(
        "summary",
        Text(),
        comment=(
            "Short human-readable description. A derived, revisable convenience field — not "
            "authoritative world data."
        ),
    ),
    Column(
        "canon_status_id",
        UUID(),
        ForeignKey("core.canon_statuses.canon_status_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "lifecycle_status_id",
        UUID(),
        ForeignKey("core.lifecycle_statuses.lifecycle_status_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("source_id", UUID(), ForeignKey("core.sources.source_id", ondelete="SET NULL")),
    Column(
        "created_by_user_id",
        UUID(),
        ForeignKey("security.users.user_id", ondelete="SET NULL"),
    ),
    *_timestamps(),
    Column(
        "archived_at",
        TIMESTAMP(timezone=True),
        comment=(
            "Set when the entity is archived. Persistent world entities are archived rather "
            "than deleted (docs/ENTITY_LIFECYCLE.md §12)."
        ),
    ),
    schema="core",
    comment=(
        "Stable identity for important world objects, and the root of the class-table "
        "inheritance chain. Definition only — what an entity IS. What is currently true "
        "about it in a timeline lives in campaign state, not here."
    ),
)

Index("ix_worlds_lifecycle_status_id", worlds.c.lifecycle_status_id)
Index("ix_entity_types_parent_entity_type_id", entity_types.c.parent_entity_type_id)
Index("ix_sources_world_id", sources.c.world_id)
Index("ix_sources_source_type_id", sources.c.source_type_id)
Index("ix_sources_created_by_user_id", sources.c.created_by_user_id)
Index("ix_entities_world_id", entities.c.world_id)
Index("ix_entities_entity_type_id", entities.c.entity_type_id)
Index("ix_entities_canon_status_id", entities.c.canon_status_id)
Index("ix_entities_lifecycle_status_id", entities.c.lifecycle_status_id)
Index("ix_entities_source_id", entities.c.source_id)
Index("ix_entities_created_by_user_id", entities.c.created_by_user_id)
Index("ix_entities_world_id_canonical_name", entities.c.world_id, entities.c.canonical_name)


# ---------------------------------------------------------------------------
# core — names and tags (revision 005)
# ---------------------------------------------------------------------------

name_types = _lookup_table(
    "core",
    "name_types",
    "name_type_id",
    "Kinds of alternate or historical name an entity can carry — see docs/DOMAIN_MODEL.md §4.4.",
)

entity_names = Table(
    "entity_names",
    metadata,
    _uuid_pk("entity_name_id"),
    Column(
        "entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "name_type_id",
        UUID(),
        ForeignKey("core.name_types.name_type_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("name", Text(), nullable=False),
    Column(
        "language",
        Text(),
        comment=(
            "In-world or real-world language tag, for translated names. NULL when not applicable."
        ),
    ),
    Column("notes", Text()),
    Column(
        "is_primary",
        Boolean(),
        nullable=False,
        server_default=text("false"),
        comment=(
            "At most one per entity, enforced by a partial unique index. Marks the name to "
            "prefer when several of the same type exist."
        ),
    ),
    *_timestamps(),
    schema="core",
    comment=(
        "Alternate and historical names for an entity. core.entities.canonical_name "
        "stays the single denormalized display name; this table holds everything else."
    ),
)

tags = Table(
    "tags",
    metadata,
    _uuid_pk("tag_id"),
    Column("world_id", UUID(), ForeignKey("core.worlds.world_id", ondelete="CASCADE")),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    *_timestamps(),
    schema="core",
    comment=(
        "Free-form classification. world_id NULL means a platform tag usable by every "
        "world; a set world_id means the world owns it (conventions §11.3)."
    ),
)

entity_tags = Table(
    "entity_tags",
    metadata,
    Column(
        "entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "tag_id",
        UUID(),
        ForeignKey("core.tags.tag_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("tagged_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column(
        "tagged_by_user_id",
        UUID(),
        ForeignKey("security.users.user_id", ondelete="SET NULL"),
    ),
    PrimaryKeyConstraint("entity_id", "tag_id"),
    schema="core",
    comment=(
        "Applies a tag to an entity. A world-owned tag may only be applied to entities "
        "in that world — enforced by core.enforce_entity_tag_world()."
    ),
)

Index("ix_entity_names_entity_id", entity_names.c.entity_id)
Index("ix_entity_names_name_type_id", entity_names.c.name_type_id)
Index("ix_tags_world_id", tags.c.world_id)
Index("ix_entity_tags_tag_id", entity_tags.c.tag_id)
Index("ix_entity_tags_tagged_by_user_id", entity_tags.c.tagged_by_user_id)

# Partial and expression indexes. Autogenerate does not reliably produce these
# (docs/DEVELOPMENT.md §4), so they are declared explicitly to keep
# `alembic check` from reporting them as drift against the migration.
Index(
    "ux_entity_names_one_primary_per_entity",
    entity_names.c.entity_id,
    unique=True,
    postgresql_where=entity_names.c.is_primary,
)
Index(
    "ix_entity_names_name_trgm",
    entity_names.c.name,
    postgresql_using="gin",
    postgresql_ops={"name": "gin_trgm_ops"},
)
Index(
    "ux_tags_platform_code",
    tags.c.code,
    unique=True,
    postgresql_where=tags.c.world_id.is_(None),
)
Index(
    "ux_tags_world_code",
    tags.c.world_id,
    tags.c.code,
    unique=True,
    postgresql_where=tags.c.world_id.isnot(None),
)
