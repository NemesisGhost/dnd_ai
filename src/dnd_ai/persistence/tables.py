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
    BigInteger,
    Boolean,
    Column,
    ForeignKey,
    Identity,
    Index,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import DOMAIN, INT8RANGE, JSONB, TIMESTAMP, UUID
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
    # Added by revision 006, once core.calendars existed to point at.
    Column(
        "default_calendar_id",
        UUID(),
        ForeignKey("core.calendars.calendar_id", ondelete="SET NULL"),
        comment=(
            "The calendar to use when none is specified. Nullable: a world need not have "
            "defined one yet."
        ),
    ),
    # Added by revision 016, once rules.rulesets existed to point at.
    Column(
        "default_ruleset_id",
        UUID(),
        ForeignKey("rules.rulesets.ruleset_id", ondelete="SET NULL"),
        comment=(
            "The ruleset to use when none is specified. Must be one of the rulesets the "
            "world allows (rules.world_rulesets) — enforced by trigger."
        ),
    ),
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
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
        comment=(
            "NULL means the name is global — valid regardless of which timeline is being "
            "viewed, and what every name defaults to. A set value scopes the name to that "
            "timeline, for names that only exist after some historical event; it must "
            "belong to the same world as the named entity."
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
Index(
    "ix_entity_names_timeline_id",
    entity_names.c.timeline_id,
    postgresql_where=entity_names.c.timeline_id.isnot(None),
)
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


# ---------------------------------------------------------------------------
# core — calendars and world times (revision 006)
# ---------------------------------------------------------------------------

world_time_precisions = _lookup_table(
    "core",
    "world_time_precisions",
    "world_time_precision_id",
    "How precisely a world time is known — see docs/DOMAIN_MODEL.md §6.2.",
)

calendars = Table(
    "calendars",
    metadata,
    _uuid_pk("calendar_id"),
    Column(
        "world_id",
        UUID(),
        ForeignKey("core.worlds.world_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    Column("days_per_week", NONNEGATIVE_INTEGER),
    Column(
        "epoch_label",
        Text(),
        comment='What year zero is counted from, e.g. "Founding of the Republic".',
    ),
    *_timestamps(),
    UniqueConstraint("world_id", "code", name="ux_calendars_world_code"),
    schema="core",
    comment=(
        "A fictional time system belonging to one world (docs/DOMAIN_MODEL.md §6.1). "
        "Worlds may define several — a common reckoning and an elvish one, say."
    ),
)

calendar_months = Table(
    "calendar_months",
    metadata,
    _uuid_pk("calendar_month_id"),
    Column(
        "calendar_id",
        UUID(),
        ForeignKey("core.calendars.calendar_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "month_number",
        NONNEGATIVE_INTEGER,
        nullable=False,
        comment="Ordinal position within the year, starting at 1. Not a real-world month.",
    ),
    Column("name", Text(), nullable=False),
    Column("day_count", NONNEGATIVE_INTEGER, nullable=False),
    *_timestamps(),
    UniqueConstraint("calendar_id", "month_number", name="ux_calendar_months_calendar_number"),
    UniqueConstraint("calendar_id", "name", name="ux_calendar_months_calendar_name"),
    schema="core",
    comment=(
        "The months of a calendar, ordered by month_number. Both the ordinal and the "
        "name are unique within a calendar."
    ),
)

world_times = Table(
    "world_times",
    metadata,
    _uuid_pk("world_time_id"),
    Column(
        "world_id",
        UUID(),
        ForeignKey("core.worlds.world_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "calendar_id",
        UUID(),
        ForeignKey("core.calendars.calendar_id", ondelete="RESTRICT"),
    ),
    Column(
        "world_time_precision_id",
        UUID(),
        ForeignKey("core.world_time_precisions.world_time_precision_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "year",
        Integer(),
        comment=(
            "Plain INTEGER, not a non-negative domain: fictional calendars count backwards "
            "from their epoch as readily as forwards."
        ),
    ),
    Column("month_number", NONNEGATIVE_INTEGER),
    Column("day", NONNEGATIVE_INTEGER),
    Column("hour", NONNEGATIVE_INTEGER),
    Column("minute", NONNEGATIVE_INTEGER),
    Column(
        "label",
        Text(),
        comment=(
            'Relative narrative description, e.g. "shortly after the Sundering". Required when '
            "there is no calendar year."
        ),
    ),
    Column(
        "sort_key",
        BigInteger(),
        nullable=False,
        comment=(
            "Orderable position in fictional chronology. NOT NULL because a world time that "
            "cannot be ordered is useless to timeline and effective-state queries; the caller "
            "must decide where even an approximate or narrative moment sits. Computation is "
            "calendar-specific and belongs in the domain layer."
        ),
    ),
    *_timestamps(),
    schema="core",
    comment=(
        "A point or approximate period in fictional chronology (docs/DOMAIN_MODEL.md §6.2). "
        "Never a real-world timestamp — system time and world time must not be conflated "
        "(§6.3)."
    ),
)

Index("ix_worlds_default_calendar_id", worlds.c.default_calendar_id)
Index(
    "ix_worlds_default_ruleset_id",
    worlds.c.default_ruleset_id,
    postgresql_where=worlds.c.default_ruleset_id.isnot(None),
)
Index("ix_calendars_world_id", calendars.c.world_id)
Index("ix_calendar_months_calendar_id", calendar_months.c.calendar_id)
Index("ix_world_times_world_id", world_times.c.world_id)
Index("ix_world_times_calendar_id", world_times.c.calendar_id)
Index("ix_world_times_world_time_precision_id", world_times.c.world_time_precision_id)
Index("ix_world_times_world_id_sort_key", world_times.c.world_id, world_times.c.sort_key)


# ---------------------------------------------------------------------------
# audit (revision 007)
# ---------------------------------------------------------------------------

change_actions = _lookup_table(
    "audit",
    "change_actions",
    "change_action_id",
    "What kind of change an audit row records. Covers the operations in "
    "docs/DATABASE_CONVENTIONS.md §24.1.",
)

change_log = Table(
    "change_log",
    metadata,
    Column(
        "change_log_id",
        BigInteger(),
        Identity(always=True),
        primary_key=True,
        comment=(
            "BIGINT identity rather than UUID: high-volume internal append-only data with no "
            "need for globally portable identity (conventions §5.2)."
        ),
    ),
    Column(
        "change_action_id",
        UUID(),
        ForeignKey("audit.change_actions.change_action_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("schema_name", Text(), nullable=False),
    Column("table_name", Text(), nullable=False),
    Column(
        "record_id",
        UUID(),
        comment=(
            "Primary key of the changed row, in whatever table schema_name.table_name names. "
            "Unconstrained by design."
        ),
    ),
    Column(
        "entity_id",
        UUID(),
        comment=(
            "The core.entities row this change concerns, when there is one. Denormalized from "
            "record_id so entity history can be queried without knowing which subtype table "
            "the change landed in."
        ),
    ),
    Column("world_id", UUID()),
    Column("previous_status", Text()),
    Column("new_status", Text()),
    Column(
        "actor_user_id",
        UUID(),
        ForeignKey("security.users.user_id", ondelete="SET NULL"),
    ),
    Column(
        "actor_service",
        Text(),
        comment=(
            "Set instead of actor_user_id when the actor is a service, integration, or AI agent "
            "rather than a person (conventions §24.3). At least one of the two is required."
        ),
    ),
    Column("source_id", UUID(), ForeignKey("core.sources.source_id", ondelete="SET NULL")),
    Column("reason", Text()),
    Column("correlation_id", UUID()),
    Column("causation_id", UUID()),
    Column("command_name", Text()),
    Column(
        "event_id",
        UUID(),
        comment=(
            "The narrative event that caused this change, once narrative.events exists in "
            "Phase 6. Unconstrained until then; rule 6 in CLAUDE.md is what makes it matter."
        ),
    ),
    Column("ai_proposal_id", UUID()),
    Column(
        "changed_fields",
        JSONB(),
        comment=(
            "Field-level diff when one is worth keeping. JSONB here is a deliberate use for "
            "genuinely variable shape, not a substitute for relational modelling (§18)."
        ),
    ),
    Column("recorded_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    schema="audit",
    comment=(
        "Append-only record of who changed what and why. Rows outlive the records they "
        "describe, so the columns identifying those records carry no foreign keys — a "
        "cascade would destroy history and a restrict would block legitimate deletion."
    ),
)

Index("ix_change_log_change_action_id", change_log.c.change_action_id)
Index("ix_change_log_actor_user_id", change_log.c.actor_user_id)
Index("ix_change_log_source_id", change_log.c.source_id)
Index("ix_change_log_correlation_id", change_log.c.correlation_id)
Index(
    "ix_change_log_entity_id_recorded_at",
    change_log.c.entity_id,
    change_log.c.recorded_at.desc(),
)
Index(
    "ix_change_log_world_id_recorded_at",
    change_log.c.world_id,
    change_log.c.recorded_at.desc(),
)


# ---------------------------------------------------------------------------
# campaign — timelines (revision 008)
# ---------------------------------------------------------------------------

timelines = Table(
    "timelines",
    metadata,
    _uuid_pk("timeline_id"),
    Column(
        "world_id",
        UUID(),
        ForeignKey("core.worlds.world_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", Text(), nullable=False),
    Column("description", Text()),
    Column(
        "parent_timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="RESTRICT"),
    ),
    Column(
        "branch_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
        comment=(
            "The world time at which this timeline diverged from its parent. NULL only "
            "for a root timeline. The causal branch_event_id arrives in Phase 6 with "
            "narrative.events."
        ),
    ),
    Column(
        "is_primary",
        Boolean(),
        nullable=False,
        server_default=text("false"),
        comment=(
            "The world's canonical timeline. At most one per world, enforced by a partial "
            "unique index rather than a CHECK, since the rule spans rows."
        ),
    ),
    Column(
        "lifecycle_status_id",
        UUID(),
        ForeignKey("core.lifecycle_statuses.lifecycle_status_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    *_timestamps(),
    schema="campaign",
    comment=(
        "A branching chronology within a world. Campaigns are played on a timeline; a "
        "branch inherits parent history only up to its branch point (docs/PLAN.md §5.2)."
    ),
)

Index("ix_timelines_world_id", timelines.c.world_id)
Index(
    "ix_timelines_parent_timeline_id",
    timelines.c.parent_timeline_id,
    postgresql_where=timelines.c.parent_timeline_id.isnot(None),
)
Index("ix_timelines_lifecycle_status_id", timelines.c.lifecycle_status_id)
Index(
    "ix_timelines_branch_world_time_id",
    timelines.c.branch_world_time_id,
    postgresql_where=timelines.c.branch_world_time_id.isnot(None),
)
Index(
    "ux_timelines_one_primary_per_world",
    timelines.c.world_id,
    unique=True,
    postgresql_where=timelines.c.is_primary,
)


# ---------------------------------------------------------------------------
# campaign — parties and memberships (revision 009)
# ---------------------------------------------------------------------------

parties = Table(
    "parties",
    metadata,
    _uuid_pk("party_id"),
    Column(
        "world_id",
        UUID(),
        ForeignKey("core.worlds.world_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", Text(), nullable=False),
    Column("description", Text()),
    *_timestamps(),
    schema="campaign",
    comment=(
        "A group of characters who adventure together. A stable world-level identity that "
        "may persist across campaigns; membership is timeline-scoped state, not a property "
        "of this row (docs/PLAN.md §5.4)."
    ),
)

# The EXCLUDE constraint is intentionally absent from this metadata. Alembic's
# autogenerate does not compare exclusion constraints, so declaring it here
# would add a second place to maintain with no enforcement behind it — the same
# reasoning applied to CHECK constraints and triggers. It is covered by
# tests/database/test_party_memberships.py, which asserts both that it exists
# with the exact shape ADR 0010 specifies and that it behaves correctly.
party_memberships = Table(
    "party_memberships",
    metadata,
    _uuid_pk("party_membership_id"),
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
        comment=(
            "Membership is timeline state: it can diverge after a branch. A row written "
            "to one branch is not a row in its sibling."
        ),
    ),
    Column(
        "party_id",
        UUID(),
        ForeignKey("campaign.parties.party_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "member_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        nullable=False,
        comment=(
            "References core.entities, not character.characters, which arrives in Phase 4. "
            "Characters are entities, so this is correct but weaker than it will be — the "
            "database cannot yet reject a non-character being added to a party."
        ),
    ),
    Column(
        "effective_from_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "effective_to_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
        comment=(
            'NULL means the membership is open-ended — the single representation of "still a '
            'member". Bounded memberships are half-open: this world time is the first moment '
            "NOT in the membership, so one membership may start exactly where another ends."
        ),
    ),
    Column(
        "effective_period",
        INT8RANGE(),
        nullable=False,
        comment=(
            "Derived, never client-authoritative: an INT8RANGE over the endpoint rows' "
            "core.world_times.sort_key values, rebuilt by trigger on every INSERT and "
            "UPDATE. It exists because PostgreSQL cannot apply the overlap operator to "
            "foreign keys."
        ),
    ),
    Column("joined_reason", Text()),
    Column("left_reason", Text()),
    *_timestamps(),
    schema="campaign",
    comment=(
        "Timeline-scoped temporal record of a character belonging to a party. A character "
        "may leave and rejoin, and may belong to several parties at once, but cannot have "
        "two overlapping memberships of the SAME party in the SAME timeline — enforced by "
        "an exclusion constraint, which is concurrency-safe in a way an application check "
        "is not (ADR 0010)."
    ),
)

Index("ix_parties_world_id", parties.c.world_id)
Index("ix_party_memberships_member_entity_id", party_memberships.c.member_entity_id)
Index("ix_party_memberships_party_id", party_memberships.c.party_id)
Index(
    "ix_party_memberships_effective_from_world_time_id",
    party_memberships.c.effective_from_world_time_id,
)
Index(
    "ix_party_memberships_effective_to_world_time_id",
    party_memberships.c.effective_to_world_time_id,
    postgresql_where=party_memberships.c.effective_to_world_time_id.isnot(None),
)


# ---------------------------------------------------------------------------
# campaign — campaigns and campaign_parties (revision 010)
# ---------------------------------------------------------------------------

campaigns = Table(
    "campaigns",
    metadata,
    _uuid_pk("campaign_id"),
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="RESTRICT"),
        nullable=False,
        comment="The timeline this campaign is played on. Not unique: two campaigns may share one timeline.",
    ),
    Column("name", Text(), nullable=False),
    Column("description", Text()),
    Column(
        "lifecycle_status_id",
        UUID(),
        ForeignKey("core.lifecycle_statuses.lifecycle_status_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("started_at", TIMESTAMP(timezone=True)),
    Column("ended_at", TIMESTAMP(timezone=True)),
    *_timestamps(),
    # Added by revision 016 (as ruleset_id), once rules.rulesets existed to
    # point at; renamed to ruleset_version_id by revision 024 so a campaign
    # pins a specific, reproducible ruleset version rather than a family that
    # might later gain a second, different, current version.
    Column(
        "ruleset_version_id",
        UUID(),
        ForeignKey("rules.ruleset_versions.ruleset_version_id", ondelete="RESTRICT"),
        nullable=False,
        comment=(
            "The exact ruleset version this campaign is played with — pinned, not just "
            "the ruleset family, so the campaign's rules configuration is reproducible. "
            "Must belong to a ruleset allowed for the campaign's world "
            "(rules.world_rulesets) — enforced by trigger."
        ),
    ),
    schema="campaign",
    comment=(
        "A single game's run on a timeline. Several campaigns may share one timeline "
        "(docs/PLAN.md §5.3). Does not own world entities — it reaches them through "
        "participation, discovery, state, and event records."
    ),
)

# The world-agreement trigger (campaign.enforce_campaign_party_world) is
# intentionally absent here — same reasoning as the exclusion constraint in
# party_memberships: alembic check does not compare triggers, so declaring one
# here would be a second place to maintain with no enforcement behind it.
campaign_parties = Table(
    "campaign_parties",
    metadata,
    Column(
        "campaign_id",
        UUID(),
        ForeignKey("campaign.campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "party_id",
        UUID(),
        ForeignKey("campaign.parties.party_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("added_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("campaign_id", "party_id"),
    schema="campaign",
    comment=(
        "Associates a world-level party (campaign.parties) with the campaigns that use "
        "it. Membership itself is timeline-scoped state tracked separately in "
        "campaign.party_memberships — this table only says which campaigns a party "
        "participates in."
    ),
)

Index("ix_campaigns_timeline_id", campaigns.c.timeline_id)
Index("ix_campaigns_lifecycle_status_id", campaigns.c.lifecycle_status_id)
Index("ix_campaigns_ruleset_version_id", campaigns.c.ruleset_version_id)
Index("ix_campaign_parties_party_id", campaign_parties.c.party_id)


# ---------------------------------------------------------------------------
# campaign — sessions (revision 011)
# ---------------------------------------------------------------------------

sessions = Table(
    "sessions",
    metadata,
    _uuid_pk("session_id"),
    Column(
        "campaign_id",
        UUID(),
        ForeignKey("campaign.campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("session_number", Integer(), nullable=False),
    Column("title", Text()),
    Column(
        "lifecycle_status_id",
        UUID(),
        ForeignKey("core.lifecycle_statuses.lifecycle_status_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "start_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
        comment=(
            "Where the story was in fictional chronology when the session began. "
            "Distinct from started_at, which is when the table actually played."
        ),
    ),
    Column(
        "end_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
    ),
    Column("started_at", TIMESTAMP(timezone=True)),
    Column("ended_at", TIMESTAMP(timezone=True)),
    Column(
        "summary",
        Text(),
        comment=(
            "A derived artifact. May be revised freely without changing the events it "
            "summarizes (docs/PLAN.md §5.5)."
        ),
    ),
    Column(
        "source_id",
        UUID(),
        ForeignKey("core.sources.source_id", ondelete="SET NULL"),
    ),
    # Added by revision 023: a derived INT8RANGE over the world-time
    # endpoints' sort_key values, mirroring party_memberships.effective_period
    # (ADR 0010) — see that revision for the [start, end)/unscheduled/
    # open-ended contract. No exclusion constraint: sessions may overlap.
    Column(
        "world_time_period",
        INT8RANGE(),
        comment=(
            "Derived, never client-authoritative: an INT8RANGE over start_world_time_id/"
            "end_world_time_id's sort_key values, rebuilt by trigger on every INSERT and "
            "UPDATE. NULL when the session is unscheduled (both endpoints NULL). Unlike "
            "party_memberships, there is no exclusion constraint over this column — "
            "overlapping sessions are legitimate (docs/architecture/DATABASE_MODEL.md §6.4)."
        ),
    ),
    *_timestamps(),
    schema="campaign",
    comment=(
        "A single period of play within a campaign. Carries both real-world time "
        "(started_at/ended_at, when the table actually played) and fictional time "
        "(start/end_world_time_id, where the story was) — see docs/PLAN.md §5.5."
    ),
)

Index(
    "ux_sessions_campaign_number",
    sessions.c.campaign_id,
    sessions.c.session_number,
    unique=True,
)
Index("ix_sessions_campaign_id", sessions.c.campaign_id)
Index("ix_sessions_lifecycle_status_id", sessions.c.lifecycle_status_id)
Index(
    "ix_sessions_start_world_time_id",
    sessions.c.start_world_time_id,
    postgresql_where=sessions.c.start_world_time_id.isnot(None),
)
Index(
    "ix_sessions_end_world_time_id",
    sessions.c.end_world_time_id,
    postgresql_where=sessions.c.end_world_time_id.isnot(None),
)
Index(
    "ix_sessions_source_id",
    sessions.c.source_id,
    postgresql_where=sessions.c.source_id.isnot(None),
)


# ---------------------------------------------------------------------------
# rules — rulesets and ruleset versions (revision 013)
# ---------------------------------------------------------------------------

rulesets = Table(
    "rulesets",
    metadata,
    _uuid_pk("ruleset_id"),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    Column(
        "source_id",
        UUID(),
        ForeignKey("core.sources.source_id", ondelete="SET NULL"),
    ),
    # canon_status_id added by revision 025 — rules.rulesets had source_id
    # from the start but was missing this, contradicting its own comment
    # below (which was already true about source_id and became true about
    # canon status once this column existed).
    Column(
        "canon_status_id",
        UUID(),
        ForeignKey("core.canon_statuses.canon_status_id", ondelete="RESTRICT"),
        nullable=False,
        # PostgreSQL rejects a bare subquery in a column DEFAULT — matches the
        # STABLE SQL function every other rule-content table's canon_status_id
        # default calls (revision 025's rules.default_canon_status_id()).
        server_default=text("rules.default_canon_status_id()"),
        comment=(
            "How authoritative this ruleset is. Homebrew rulesets typically start at "
            "draft/proposed rather than canon (docs/architecture/DATABASE_MODEL.md §8)."
        ),
    ),
    *_timestamps(),
    UniqueConstraint("code", name="ux_rulesets_code"),
    schema="rules",
    comment=(
        'A named, edition-neutral rule-system family (e.g. "D&D 5e") — a specific edition '
        "or revision is recorded on rules.ruleset_versions.version_label and description, "
        "not here. Homebrew rulesets are ordinary rows here with their own source and "
        "canon status (docs/PLAN.md §6.2) — not a separate structure."
    ),
)

ruleset_versions = Table(
    "ruleset_versions",
    metadata,
    _uuid_pk("ruleset_version_id"),
    Column(
        "ruleset_id",
        UUID(),
        ForeignKey("rules.rulesets.ruleset_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("version_label", Text(), nullable=False),
    Column("description", Text()),
    Column(
        "is_current",
        Boolean(),
        nullable=False,
        server_default=text("false"),
        comment=(
            "The version to use when none is pinned explicitly. At most one per ruleset, "
            "enforced by a partial unique index rather than a CHECK, since the rule spans "
            "rows."
        ),
    ),
    *_provenance_columns(),
    *_timestamps(),
    UniqueConstraint("ruleset_id", "version_label", name="ux_ruleset_versions_ruleset_label"),
    schema="rules",
    comment=(
        "A version within a ruleset. Rule-content tables reference a version rather than "
        "a bare ruleset, since two versions of the same ruleset may define the same-named "
        "thing differently."
    ),
)

Index(
    "ix_rulesets_source_id",
    rulesets.c.source_id,
    postgresql_where=rulesets.c.source_id.isnot(None),
)
Index("ix_rulesets_canon_status_id", rulesets.c.canon_status_id)
Index("ix_ruleset_versions_ruleset_id", ruleset_versions.c.ruleset_id)
Index(
    "ix_ruleset_versions_source_id",
    ruleset_versions.c.source_id,
    postgresql_where=ruleset_versions.c.source_id.isnot(None),
)
Index("ix_ruleset_versions_canon_status_id", ruleset_versions.c.canon_status_id)
Index(
    "ux_ruleset_versions_one_current_per_ruleset",
    ruleset_versions.c.ruleset_id,
    unique=True,
    postgresql_where=ruleset_versions.c.is_current,
)


# ---------------------------------------------------------------------------
# rules — ruleset-scoped lookup content (revision 014)
# ---------------------------------------------------------------------------


def _ruleset_lookup_table(name: str, pk: str, comment: str) -> Table:
    """A ruleset-version-scoped lookup, per revision 014's shared shape."""
    return Table(
        name,
        metadata,
        _uuid_pk(pk),
        Column(
            "ruleset_version_id",
            UUID(),
            ForeignKey("rules.ruleset_versions.ruleset_version_id", ondelete="CASCADE"),
            nullable=False,
        ),
        Column("code", Text(), nullable=False),
        Column("display_name", Text(), nullable=False),
        Column("description", Text()),
        *_provenance_columns(),
        *_timestamps(),
        UniqueConstraint("ruleset_version_id", "code", name=f"ux_{name}_ruleset_version_code"),
        schema="rules",
        comment=comment,
    )


abilities = _ruleset_lookup_table(
    "abilities",
    "ability_id",
    "A scored capability a character has (Strength, Dexterity, ...). Governs skills "
    "and saving throws.",
)
species = _ruleset_lookup_table(
    "species",
    "species_id",
    "A playable ancestry (Human, Elf, ...). One of the identity-level references on "
    "character.characters (docs/architecture/DATABASE_MODEL.md §7.1).",
)
damage_types = _ruleset_lookup_table(
    "damage_types",
    "damage_type_id",
    "A category of damage (fire, slashing, ...) that resistances, vulnerabilities, "
    "and immunities key off.",
)
conditions = _ruleset_lookup_table(
    "conditions",
    "condition_id",
    "A status a character can be under (poisoned, prone, ...). Definitions only — "
    "campaign.character_conditions (Phase 4 timeline state) tracks who currently has "
    "one.",
)
creature_types = _ruleset_lookup_table(
    "creature_types",
    "creature_type_id",
    "A monster-manual classification (beast, fiend, undead, ...), distinct from "
    "species: a character has a species, any character or monster has a creature "
    "type.",
)
languages = _ruleset_lookup_table(
    "languages",
    "language_id",
    "A language a character can know or speak, referenced by character.character_languages.",
)
proficiency_types = _ruleset_lookup_table(
    "proficiency_types",
    "proficiency_type_id",
    "A category of proficiency (weapon, armor, tool, skill, saving throw) that "
    "character.character_proficiencies rows are typed by.",
)
resource_definitions = _ruleset_lookup_table(
    "resource_definitions",
    "resource_definition_id",
    "A depletable/rechargeable resource kind (spell slot, ki point, rage use, ...). "
    "Definitions only — campaign.character_resources (Phase 4 timeline state) tracks "
    "current and maximum amounts.",
)

for _t in (
    abilities,
    species,
    damage_types,
    conditions,
    creature_types,
    languages,
    proficiency_types,
    resource_definitions,
):
    Index(f"ix_{_t.name}_ruleset_version_id", _t.c.ruleset_version_id)
    Index(f"ix_{_t.name}_source_id", _t.c.source_id, postgresql_where=_t.c.source_id.isnot(None))
    Index(f"ix_{_t.name}_canon_status_id", _t.c.canon_status_id)

# target_kind added by revision 029, specific to proficiency_types alone —
# not part of the shared _ruleset_lookup_table shape.
proficiency_types.append_column(
    Column(
        "target_kind",
        Text(),
        nullable=False,
        comment=(
            "Which column of character.character_proficiencies a proficiency of this "
            "type must set: skill_id, saving_throw_ability_id, or the free-text "
            "target_label (weapon/armor/tool categories with no dedicated lookup yet). "
            "Enforced by trigger on character.character_proficiencies."
        ),
    )
)

skills = Table(
    "skills",
    metadata,
    _uuid_pk("skill_id"),
    Column(
        "ruleset_version_id",
        UUID(),
        ForeignKey("rules.ruleset_versions.ruleset_version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "ability_id",
        UUID(),
        ForeignKey("rules.abilities.ability_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    *_provenance_columns(),
    *_timestamps(),
    UniqueConstraint("ruleset_version_id", "code", name="ux_skills_ruleset_version_code"),
    schema="rules",
    comment="A trained capability governed by one ability (Stealth -> Dexterity, ...).",
)

Index("ix_skills_ruleset_version_id", skills.c.ruleset_version_id)
Index("ix_skills_ability_id", skills.c.ability_id)
Index("ix_skills_source_id", skills.c.source_id, postgresql_where=skills.c.source_id.isnot(None))
Index("ix_skills_canon_status_id", skills.c.canon_status_id)


# ---------------------------------------------------------------------------
# rules — classes, subclasses, features, feats, spells (revision 015)
# ---------------------------------------------------------------------------

classes = Table(
    "classes",
    metadata,
    _uuid_pk("class_id"),
    Column(
        "ruleset_version_id",
        UUID(),
        ForeignKey("rules.ruleset_versions.ruleset_version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    Column("hit_die", NONNEGATIVE_INTEGER, nullable=False),
    Column(
        "primary_ability_id",
        UUID(),
        ForeignKey("rules.abilities.ability_id", ondelete="RESTRICT"),
    ),
    *_provenance_columns(),
    *_timestamps(),
    UniqueConstraint("ruleset_version_id", "code", name="ux_classes_ruleset_version_code"),
    schema="rules",
    comment=(
        "A playable class definition (Fighter, Wizard, ...). character_class_levels "
        "references this to record a character's levels in it."
    ),
)

Index("ix_classes_ruleset_version_id", classes.c.ruleset_version_id)
Index(
    "ix_classes_primary_ability_id",
    classes.c.primary_ability_id,
    postgresql_where=classes.c.primary_ability_id.isnot(None),
)
Index("ix_classes_source_id", classes.c.source_id, postgresql_where=classes.c.source_id.isnot(None))
Index("ix_classes_canon_status_id", classes.c.canon_status_id)

subclasses = Table(
    "subclasses",
    metadata,
    _uuid_pk("subclass_id"),
    Column(
        "class_id",
        UUID(),
        ForeignKey("rules.classes.class_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "ruleset_version_id",
        UUID(),
        ForeignKey("rules.ruleset_versions.ruleset_version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    *_provenance_columns(),
    *_timestamps(),
    UniqueConstraint("class_id", "code", name="ux_subclasses_class_code"),
    schema="rules",
    comment=(
        "A specialization within a class (Champion within Fighter, ...). Unique per "
        "class, not per ruleset version — two different classes may each define their "
        "own subclass with the same code."
    ),
)

Index("ix_subclasses_class_id", subclasses.c.class_id)
Index("ix_subclasses_ruleset_version_id", subclasses.c.ruleset_version_id)
Index(
    "ix_subclasses_source_id",
    subclasses.c.source_id,
    postgresql_where=subclasses.c.source_id.isnot(None),
)
Index("ix_subclasses_canon_status_id", subclasses.c.canon_status_id)

features = Table(
    "features",
    metadata,
    _uuid_pk("feature_id"),
    Column(
        "ruleset_version_id",
        UUID(),
        ForeignKey("rules.ruleset_versions.ruleset_version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("class_id", UUID(), ForeignKey("rules.classes.class_id", ondelete="CASCADE")),
    Column("subclass_id", UUID(), ForeignKey("rules.subclasses.subclass_id", ondelete="CASCADE")),
    Column("species_id", UUID(), ForeignKey("rules.species.species_id", ondelete="CASCADE")),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    Column(
        "granted_at_level",
        NONNEGATIVE_INTEGER,
        comment=(
            "The class or subclass level at which this feature is gained. NULL for "
            "species traits, which are not level-gated."
        ),
    ),
    *_provenance_columns(),
    *_timestamps(),
    UniqueConstraint("ruleset_version_id", "code", name="ux_features_ruleset_version_code"),
    schema="rules",
    comment=(
        "A granted trait or ability — a class feature, subclass feature, or species "
        "trait. The three associations are independently nullable, not mutually "
        "exclusive: which combinations are meaningful is rules content, not structure."
    ),
)

Index("ix_features_ruleset_version_id", features.c.ruleset_version_id)
Index(
    "ix_features_source_id", features.c.source_id, postgresql_where=features.c.source_id.isnot(None)
)
Index("ix_features_canon_status_id", features.c.canon_status_id)
Index("ix_features_class_id", features.c.class_id, postgresql_where=features.c.class_id.isnot(None))
Index(
    "ix_features_subclass_id",
    features.c.subclass_id,
    postgresql_where=features.c.subclass_id.isnot(None),
)
Index(
    "ix_features_species_id",
    features.c.species_id,
    postgresql_where=features.c.species_id.isnot(None),
)

feats = Table(
    "feats",
    metadata,
    _uuid_pk("feat_id"),
    Column(
        "ruleset_version_id",
        UUID(),
        ForeignKey("rules.ruleset_versions.ruleset_version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    Column("prerequisite_description", Text()),
    *_provenance_columns(),
    *_timestamps(),
    UniqueConstraint("ruleset_version_id", "code", name="ux_feats_ruleset_version_code"),
    schema="rules",
    comment=(
        "An optional feat a character may take. prerequisite_description is free text "
        "for now — structured, machine-checkable prerequisites are a later refinement."
    ),
)

Index("ix_feats_ruleset_version_id", feats.c.ruleset_version_id)
Index("ix_feats_source_id", feats.c.source_id, postgresql_where=feats.c.source_id.isnot(None))
Index("ix_feats_canon_status_id", feats.c.canon_status_id)

spells = Table(
    "spells",
    metadata,
    _uuid_pk("spell_id"),
    Column(
        "ruleset_version_id",
        UUID(),
        ForeignKey("rules.ruleset_versions.ruleset_version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    Column("level", NONNEGATIVE_INTEGER, nullable=False),
    Column("school", Text()),
    Column("casting_time", Text()),
    Column("range", Text()),
    Column("duration", Text()),
    Column(
        "damage_type_id",
        UUID(),
        ForeignKey("rules.damage_types.damage_type_id", ondelete="RESTRICT"),
    ),
    *_provenance_columns(),
    *_timestamps(),
    UniqueConstraint("ruleset_version_id", "code", name="ux_spells_ruleset_version_code"),
    schema="rules",
    comment=(
        "A spell definition. level 0 is a cantrip. damage_type_id is set only for "
        "spells that deal typed damage."
    ),
)

Index("ix_spells_ruleset_version_id", spells.c.ruleset_version_id)
Index(
    "ix_spells_damage_type_id",
    spells.c.damage_type_id,
    postgresql_where=spells.c.damage_type_id.isnot(None),
)
Index("ix_spells_source_id", spells.c.source_id, postgresql_where=spells.c.source_id.isnot(None))
Index("ix_spells_canon_status_id", spells.c.canon_status_id)


# ---------------------------------------------------------------------------
# rules — world_rulesets (revision 016)
# ---------------------------------------------------------------------------

world_rulesets = Table(
    "world_rulesets",
    metadata,
    Column(
        "world_id",
        UUID(),
        ForeignKey("core.worlds.world_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "ruleset_id",
        UUID(),
        ForeignKey("rules.rulesets.ruleset_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    # is_default removed by revision 027: core.worlds.default_ruleset_id is
    # now the sole source of truth for a world's default ruleset, so this
    # table is a pure allow-list with no default concept of its own.
    Column("added_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("world_id", "ruleset_id"),
    schema="rules",
    comment=(
        "Associates a world with the rulesets it allows. A world may allow more than "
        "one ruleset; its default is core.worlds.default_ruleset_id alone (not "
        "represented here — see the reconciliation note in revision 027)."
    ),
)

Index("ix_world_rulesets_ruleset_id", world_rulesets.c.ruleset_id)


# ---------------------------------------------------------------------------
# character — characters, npcs, player_characters (revision 017)
# ---------------------------------------------------------------------------

characters = Table(
    "characters",
    metadata,
    Column(
        "character_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "species_id",
        UUID(),
        ForeignKey("rules.species.species_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("size_category", Text(), nullable=False),
    *_timestamps(),
    # Added by revision 042, once world.locations existed to point at.
    Column(
        "origin_location_id",
        UUID(),
        ForeignKey("world.locations.location_id", ondelete="SET NULL"),
        comment=(
            "Where this character is from. Deferred from Phase 4 until world.locations "
            "existed (docs/architecture/DATABASE_MODEL.md §7.1). Must belong to the "
            "character's own world, enforced by trigger."
        ),
    ),
    schema="character",
    comment=(
        "Identity-level mechanical data shared by every character: species and size. "
        "NPCs and player characters both extend this row rather than duplicating it "
        "(docs/PLAN.md §7.1). origin_location_id arrives in Phase 5 once "
        "world.locations exists."
    ),
)

Index("ix_characters_species_id", characters.c.species_id)
Index(
    "ix_characters_origin_location_id",
    characters.c.origin_location_id,
    postgresql_where=characters.c.origin_location_id.isnot(None),
)

npcs = Table(
    "npcs",
    metadata,
    Column(
        "npc_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    *_timestamps(),
    schema="character",
    comment=(
        "Marks a character as an NPC. Portrayal, goals, routines, and other simulation "
        "apparatus (docs/PLAN.md §8) are deferred to Phase 10, which builds the AI "
        "agents that consume them."
    ),
)

player_characters = Table(
    "player_characters",
    metadata,
    Column(
        "player_character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "player_user_id",
        UUID(),
        ForeignKey("security.users.user_id", ondelete="SET NULL"),
    ),
    *_timestamps(),
    schema="character",
    comment=(
        "Marks a character as player-controlled. player_user_id is basic ownership "
        "identity; timeline- or session-scoped control handoffs "
        "(character.character_controllers) are deferred to Phase 10."
    ),
)

Index(
    "ix_player_characters_player_user_id",
    player_characters.c.player_user_id,
    postgresql_where=player_characters.c.player_user_id.isnot(None),
)


# ---------------------------------------------------------------------------
# character — shared data: descriptions, languages, senses, movements
# (revision 019)
# ---------------------------------------------------------------------------

character_descriptions = Table(
    "character_descriptions",
    metadata,
    Column(
        "character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("background", Text()),
    Column("appearance", Text()),
    Column("notes", Text()),
    *_timestamps(),
    schema="character",
    comment=(
        "Free-text background, appearance, and notes that do not drive mechanics "
        "(docs/PLAN.md §7.2). Optional: a character need not have one yet."
    ),
)

character_languages = Table(
    "character_languages",
    metadata,
    Column(
        "character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "language_id",
        UUID(),
        ForeignKey("rules.languages.language_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("character_id", "language_id"),
    schema="character",
    comment=(
        "Languages a character knows. Pure association — a character may know "
        "languages from more than one ruleset's content, as long as every ruleset "
        "family in play is one the character's world allows (rules.world_rulesets); "
        "enforced by trigger (revision 037), same as species/build/condition/resource."
    ),
)

Index("ix_character_languages_language_id", character_languages.c.language_id)

character_senses = Table(
    "character_senses",
    metadata,
    Column(
        "character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("sense_type", Text(), nullable=False),
    Column("range_feet", NONNEGATIVE_INTEGER, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("character_id", "sense_type"),
    schema="character",
    comment="A special sense a character has (darkvision, blindsight, ...) and its range.",
)

character_movements = Table(
    "character_movements",
    metadata,
    Column(
        "character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("movement_type", Text(), nullable=False),
    Column("speed_feet", NONNEGATIVE_INTEGER, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("character_id", "movement_type"),
    schema="character",
    comment="A movement mode a character has (walk, fly, swim, ...) and its speed.",
)


# ---------------------------------------------------------------------------
# character — builds (revision 020)
# ---------------------------------------------------------------------------

character_builds = Table(
    "character_builds",
    metadata,
    _uuid_pk("character_build_id"),
    Column(
        "character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "ruleset_version_id",
        UUID(),
        ForeignKey("rules.ruleset_versions.ruleset_version_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("label", Text()),
    # is_current removed by revision 028: active-build selection moved to
    # timeline state (campaign.character_state.character_build_id), since a
    # single global "current" flag cannot represent a character built
    # differently on two timelines after a branch.
    *_timestamps(),
    schema="character",
    comment=(
        "A versioned mechanical snapshot of a character, pinned to one ruleset version. "
        "Ability scores, class levels, proficiencies, features, and spellcasting all "
        "belong to a build, not directly to the character, so re-leveling or rebuilding "
        "does not erase the prior build's history. Which build is active on a given "
        "timeline is timeline state (campaign.character_state.character_build_id), not a "
        "property of the build itself — a character may use different builds on "
        "different timelines after a branch."
    ),
)

Index("ix_character_builds_character_id", character_builds.c.character_id)
Index("ix_character_builds_ruleset_version_id", character_builds.c.ruleset_version_id)

character_ability_scores = Table(
    "character_ability_scores",
    metadata,
    Column(
        "character_build_id",
        UUID(),
        ForeignKey("character.character_builds.character_build_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "ability_id",
        UUID(),
        ForeignKey("rules.abilities.ability_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("score", NONNEGATIVE_INTEGER, nullable=False),
    *_timestamps(),
    PrimaryKeyConstraint("character_build_id", "ability_id"),
    schema="character",
    comment=(
        "The raw score (e.g. 16) a build has in one ability. Modifiers are derived, not stored."
    ),
)

Index("ix_character_ability_scores_ability_id", character_ability_scores.c.ability_id)

character_class_levels = Table(
    "character_class_levels",
    metadata,
    Column(
        "character_build_id",
        UUID(),
        ForeignKey("character.character_builds.character_build_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "class_id",
        UUID(),
        ForeignKey("rules.classes.class_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "subclass_id",
        UUID(),
        ForeignKey("rules.subclasses.subclass_id", ondelete="RESTRICT"),
    ),
    Column("level", NONNEGATIVE_INTEGER, nullable=False),
    *_timestamps(),
    PrimaryKeyConstraint("character_build_id", "class_id"),
    schema="character",
    comment="A build's level in one class. Multiple rows per build support multiclassing.",
)

Index("ix_character_class_levels_class_id", character_class_levels.c.class_id)
Index(
    "ix_character_class_levels_subclass_id",
    character_class_levels.c.subclass_id,
    postgresql_where=character_class_levels.c.subclass_id.isnot(None),
)

character_proficiencies = Table(
    "character_proficiencies",
    metadata,
    _uuid_pk("character_proficiency_id"),
    Column(
        "character_build_id",
        UUID(),
        ForeignKey("character.character_builds.character_build_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "proficiency_type_id",
        UUID(),
        ForeignKey("rules.proficiency_types.proficiency_type_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("skill_id", UUID(), ForeignKey("rules.skills.skill_id", ondelete="CASCADE")),
    Column(
        "saving_throw_ability_id",
        UUID(),
        ForeignKey("rules.abilities.ability_id", ondelete="CASCADE"),
    ),
    Column("target_label", Text()),
    Column("is_expertise", Boolean(), nullable=False, server_default=text("false")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    schema="character",
    comment=(
        "A build's proficiency in a skill, a saving-throw ability, or a free-text "
        "target (a weapon, armor category, or tool). Exactly one of skill_id, "
        "saving_throw_ability_id, and target_label is set."
    ),
)

Index("ix_character_proficiencies_build_id", character_proficiencies.c.character_build_id)
Index("ix_character_proficiencies_type_id", character_proficiencies.c.proficiency_type_id)
Index(
    "ix_character_proficiencies_skill_id",
    character_proficiencies.c.skill_id,
    postgresql_where=character_proficiencies.c.skill_id.isnot(None),
)
Index(
    "ix_character_proficiencies_saving_throw_ability_id",
    character_proficiencies.c.saving_throw_ability_id,
    postgresql_where=character_proficiencies.c.saving_throw_ability_id.isnot(None),
)
# Duplicate-prevention indexes added by revision 029 — a build cannot be
# granted the same semantic proficiency twice.
Index(
    "ux_character_proficiencies_build_skill",
    character_proficiencies.c.character_build_id,
    character_proficiencies.c.skill_id,
    unique=True,
    postgresql_where=character_proficiencies.c.skill_id.isnot(None),
)
Index(
    "ux_character_proficiencies_build_saving_throw",
    character_proficiencies.c.character_build_id,
    character_proficiencies.c.saving_throw_ability_id,
    unique=True,
    postgresql_where=character_proficiencies.c.saving_throw_ability_id.isnot(None),
)
Index(
    "ux_character_proficiencies_build_target_label",
    character_proficiencies.c.character_build_id,
    character_proficiencies.c.target_label,
    unique=True,
    postgresql_where=character_proficiencies.c.target_label.isnot(None),
)

character_features = Table(
    "character_features",
    metadata,
    Column(
        "character_build_id",
        UUID(),
        ForeignKey("character.character_builds.character_build_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "feature_id",
        UUID(),
        ForeignKey("rules.features.feature_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("character_build_id", "feature_id"),
    schema="character",
    comment="A feature a build has been granted, from its class, subclass, or species.",
)

Index("ix_character_features_feature_id", character_features.c.feature_id)

character_spellcasting_profiles = Table(
    "character_spellcasting_profiles",
    metadata,
    _uuid_pk("character_spellcasting_profile_id"),
    Column(
        "character_build_id",
        UUID(),
        ForeignKey("character.character_builds.character_build_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("class_id", UUID(), ForeignKey("rules.classes.class_id", ondelete="CASCADE")),
    Column(
        "spellcasting_ability_id",
        UUID(),
        ForeignKey("rules.abilities.ability_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("character_build_id", "class_id", name="ux_spellcasting_profiles_build_class"),
    schema="character",
    comment=(
        "A source of spellcasting for a build (Wizard casting, Warlock Pact Magic, "
        "...) and the ability it keys off. class_id is NULL for species- or "
        "feat-granted casting with no owning class."
    ),
)

Index("ix_spellcasting_profiles_build_id", character_spellcasting_profiles.c.character_build_id)
Index(
    "ix_spellcasting_profiles_class_id",
    character_spellcasting_profiles.c.class_id,
    postgresql_where=character_spellcasting_profiles.c.class_id.isnot(None),
)
Index(
    "ix_spellcasting_profiles_ability_id",
    character_spellcasting_profiles.c.spellcasting_ability_id,
)

character_known_spells = Table(
    "character_known_spells",
    metadata,
    Column(
        "character_spellcasting_profile_id",
        UUID(),
        ForeignKey(
            "character.character_spellcasting_profiles.character_spellcasting_profile_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    ),
    Column(
        "spell_id",
        UUID(),
        ForeignKey("rules.spells.spell_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("character_spellcasting_profile_id", "spell_id"),
    schema="character",
    comment="Spells a spellcasting profile knows, independent of whether they are prepared.",
)

Index("ix_character_known_spells_spell_id", character_known_spells.c.spell_id)

character_prepared_spells = Table(
    "character_prepared_spells",
    metadata,
    Column(
        "character_spellcasting_profile_id",
        UUID(),
        ForeignKey(
            "character.character_spellcasting_profiles.character_spellcasting_profile_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    ),
    Column(
        "spell_id",
        UUID(),
        ForeignKey("rules.spells.spell_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("character_spellcasting_profile_id", "spell_id"),
    schema="character",
    comment=(
        "Spells currently prepared for a spellcasting profile. Not constrained to be "
        "a subset of known spells: whether that subset relationship applies at all "
        "varies by class."
    ),
)

Index("ix_character_prepared_spells_spell_id", character_prepared_spells.c.spell_id)


# ---------------------------------------------------------------------------
# campaign — character timeline state (revision 021)
# ---------------------------------------------------------------------------

character_state = Table(
    "character_state",
    metadata,
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("current_hit_points", Integer(), nullable=False),
    Column("maximum_hit_points", NONNEGATIVE_INTEGER, nullable=False),
    Column("temporary_hit_points", NONNEGATIVE_INTEGER, nullable=False, server_default=text("0")),
    Column("exhaustion_level", NONNEGATIVE_INTEGER, nullable=False, server_default=text("0")),
    Column("death_save_successes", NONNEGATIVE_INTEGER, nullable=False, server_default=text("0")),
    Column("death_save_failures", NONNEGATIVE_INTEGER, nullable=False, server_default=text("0")),
    Column(
        "initiative",
        Integer(),
        comment="Set only while the character is in an encounter. NULL otherwise.",
    ),
    Column(
        "transformed_into_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="SET NULL"),
        comment=(
            "The character sheet currently being used instead of this one's own (a "
            "polymorph or similar transformation). NULL means no transformation is "
            "active."
        ),
    ),
    # Added by revision 028: the build this character sheet is assembled
    # from on this timeline, replacing character_builds.is_current so a
    # character can use different builds on different timelines after a
    # branch.
    Column(
        "character_build_id",
        UUID(),
        ForeignKey("character.character_builds.character_build_id", ondelete="SET NULL"),
        comment=(
            "The build this character sheet is currently assembled from on this "
            "timeline. NULL if no build has been selected yet. Must belong to this same "
            "character (enforced by trigger) — different timelines may select different "
            "builds for the same character after a branch."
        ),
    ),
    *_timestamps(),
    PrimaryKeyConstraint("timeline_id", "character_id"),
    schema="campaign",
    comment=(
        "Current combat/vitals state for a character on a timeline: HP, exhaustion, "
        "death saves, initiative when in an encounter, and current transformed form. "
        "One row per (timeline, character) — see the module docstring on why there is "
        "no event-linked history yet."
    ),
)

Index("ix_character_state_character_id", character_state.c.character_id)
Index(
    "ix_character_state_transformed_into_id",
    character_state.c.transformed_into_id,
    postgresql_where=character_state.c.transformed_into_id.isnot(None),
)
Index(
    "ix_character_state_character_build_id",
    character_state.c.character_build_id,
    postgresql_where=character_state.c.character_build_id.isnot(None),
)

character_conditions = Table(
    "character_conditions",
    metadata,
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "condition_id",
        UUID(),
        ForeignKey("rules.conditions.condition_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("source_description", Text()),
    Column("applied_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("timeline_id", "character_id", "condition_id"),
    schema="campaign",
    comment=(
        "A condition currently active on a character in a timeline. "
        "source_description is free text for now — a causal event reference arrives "
        "in Phase 6."
    ),
)

Index("ix_character_conditions_character_id", character_conditions.c.character_id)
Index("ix_character_conditions_condition_id", character_conditions.c.condition_id)

character_resources = Table(
    "character_resources",
    metadata,
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "resource_definition_id",
        UUID(),
        ForeignKey("rules.resource_definitions.resource_definition_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("current_amount", NONNEGATIVE_INTEGER, nullable=False),
    Column("maximum_amount", NONNEGATIVE_INTEGER, nullable=False),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("timeline_id", "character_id", "resource_definition_id"),
    schema="campaign",
    comment=(
        "Current and maximum amount of a depletable/rechargeable resource (spell "
        "slots, ki points, rage uses, ...) a character has in a timeline."
    ),
)

Index("ix_character_resources_character_id", character_resources.c.character_id)
Index(
    "ix_character_resources_resource_definition_id",
    character_resources.c.resource_definition_id,
)


# ---------------------------------------------------------------------------
# world — location hierarchy (revision 038)
# ---------------------------------------------------------------------------

locations = Table(
    "locations",
    metadata,
    Column(
        "location_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "parent_location_id",
        UUID(),
        ForeignKey("world.locations.location_id", ondelete="RESTRICT"),
        comment=(
            "The location this one is contained within, e.g. a building's settlement, a "
            "settlement's region. NULL for top-level locations (planes, continents). Must "
            "belong to the same world as this location, enforced by trigger."
        ),
    ),
    *_timestamps(),
    schema="world",
    comment=(
        "Class-table-inheritance root for every spatial entity. Containment is "
        "expressed through parent_location_id; general semantic relationships "
        "(adjacency, claims, portals, trade routes, disputed control) use the "
        "universal relationship model instead (docs/architecture/DATABASE_MODEL.md §9.1)."
    ),
)

Index(
    "ix_locations_parent_location_id",
    locations.c.parent_location_id,
    postgresql_where=locations.c.parent_location_id.isnot(None),
)

settlements = Table(
    "settlements",
    metadata,
    Column(
        "settlement_id",
        UUID(),
        ForeignKey("world.locations.location_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("population", NONNEGATIVE_INTEGER),
    *_timestamps(),
    schema="world",
    comment=(
        "Marks a location as a populated settlement. Deliberately minimal (population "
        "only) — government, factions, and economy are later-phase concepts; districts "
        "are plain child locations; control/damage state is timeline state "
        "(campaign.location_state, revision 040). See this revision's docstring."
    ),
)

buildings = Table(
    "buildings",
    metadata,
    Column(
        "building_id",
        UUID(),
        ForeignKey("world.locations.location_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("building_use", Text()),
    *_timestamps(),
    schema="world",
    comment=(
        "Marks a location as a constructed building. building_use is free text "
        "(tavern, temple, shop, warehouse, ...) — no documented controlled vocabulary "
        "exists yet (docs/DOMAIN_MODEL.md §9.3)."
    ),
)


# ---------------------------------------------------------------------------
# world — dungeon structures (revision 039)
# ---------------------------------------------------------------------------

dungeons = Table(
    "dungeons",
    metadata,
    Column(
        "dungeon_id",
        UUID(),
        ForeignKey("world.locations.location_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("danger_level", RATING_1_10),
    *_timestamps(),
    schema="world",
    comment=(
        "Marks a location as a dungeon: a location composed of connected areas and "
        "stateful gameplay elements (docs/DOMAIN_MODEL.md §9.4). danger_level is an "
        "optional GM-facing difficulty rating."
    ),
)

dungeon_areas = Table(
    "dungeon_areas",
    metadata,
    Column(
        "dungeon_area_id",
        UUID(),
        ForeignKey("world.locations.location_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("area_type", Text()),
    Column(
        "dimensions",
        Text(),
        comment=(
            'Free-text size description (e.g. "30 ft by 40 ft"). No structured unit '
            "system exists yet."
        ),
    ),
    Column("environmental_properties", Text()),
    *_timestamps(),
    schema="world",
    comment=(
        "A room, chamber, corridor, platform, cavern, or similar navigable unit "
        "(docs/DOMAIN_MODEL.md §9.5). Parent dungeon is expressed through "
        "world.locations.parent_location_id, required to be a dungeon-typed location "
        "by trigger."
    ),
)

connection_types = _lookup_table(
    "world",
    "connection_types",
    "connection_type_id",
    "Kinds of link between two dungeon areas (door, secret door, passage, portal, "
    "stair, ladder, pit, bridge, teleportation link) — docs/DOMAIN_MODEL.md §9.6.",
)

area_connections = Table(
    "area_connections",
    metadata,
    _uuid_pk("area_connection_id"),
    Column(
        "from_dungeon_area_id",
        UUID(),
        ForeignKey("world.dungeon_areas.dungeon_area_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "to_dungeon_area_id",
        UUID(),
        ForeignKey("world.dungeon_areas.dungeon_area_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "connection_type_id",
        UUID(),
        ForeignKey("world.connection_types.connection_type_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "is_one_way",
        Boolean(),
        nullable=False,
        server_default=text("false"),
        comment=(
            "True for a connection traversable only from from_dungeon_area_id to "
            "to_dungeon_area_id (a one-way chute, a collapsing bridge behind the party, ...)."
        ),
    ),
    Column("is_hidden", Boolean(), nullable=False, server_default=text("false")),
    Column("description", Text()),
    # Added by revision 047: the descriptive half of "conditional routes"
    # (docs/PLAN.md §9.2). Evaluating the condition is deferred — see the
    # column comments and PLAN.md Phase 6's first-time obligations.
    Column(
        "is_conditional",
        Boolean(),
        nullable=False,
        server_default=text("false"),
        comment=(
            "True for a conditional route (docs/PLAN.md §9.2) — traversable only when "
            "some condition holds. Descriptive only: evaluating the condition requires "
            "interaction/check resolution (Phase 6) or quest state (Phase 7), neither "
            "of which exists yet. See PLAN.md Phase 6's first-time obligations."
        ),
    ),
    Column(
        "condition_description",
        Text(),
        comment=(
            'Free-text description of what the condition is (e.g. "requires the brass '
            'key" or "only open while the beacon is lit"). Not yet machine-evaluable — '
            "same placeholder shape as campaign.character_conditions.source_description."
        ),
    ),
    *_timestamps(),
    schema="world",
    comment=(
        "A link between two dungeon areas (docs/DOMAIN_MODEL.md §9.6). Not an entity — "
        "a structural child of the areas it joins. is_hidden is a fact about the "
        "connection itself (built to be concealed), never about whether any party has "
        "found it — party knowledge is tracked separately (docs/architecture/"
        "DATABASE_MODEL.md §9.3, revision 041)."
    ),
)

Index("ix_area_connections_from_dungeon_area_id", area_connections.c.from_dungeon_area_id)
Index("ix_area_connections_to_dungeon_area_id", area_connections.c.to_dungeon_area_id)
Index("ix_area_connections_connection_type_id", area_connections.c.connection_type_id)

area_features = Table(
    "area_features",
    metadata,
    _uuid_pk("area_feature_id"),
    Column(
        "dungeon_area_id",
        UUID(),
        ForeignKey("world.dungeon_areas.dungeon_area_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("feature_type", Text()),
    Column("description", Text()),
    Column("is_hidden", Boolean(), nullable=False, server_default=text("false")),
    *_timestamps(),
    schema="world",
    comment=(
        "A notable but not necessarily interactive part of an area — mural, blood "
        "trail, altar, broken machinery, drag marks, statue (docs/DOMAIN_MODEL.md §9.7). "
        "Not an entity. is_hidden is a fact about the feature itself, never party "
        "knowledge (see world.area_connections comment)."
    ),
)

Index("ix_area_features_dungeon_area_id", area_features.c.dungeon_area_id)

area_hazards = Table(
    "area_hazards",
    metadata,
    _uuid_pk("area_hazard_id"),
    Column(
        "dungeon_area_id",
        UUID(),
        ForeignKey("world.dungeon_areas.dungeon_area_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("hazard_type", Text()),
    Column("description", Text()),
    Column("severity", RATING_1_10),
    Column("is_hidden", Boolean(), nullable=False, server_default=text("false")),
    *_timestamps(),
    schema="world",
    comment=(
        "A dangerous environmental object or condition — trap, collapsing floor, "
        "electrical arc, poisonous gas, magical ward (docs/DOMAIN_MODEL.md §9.8). Not "
        "an entity. is_hidden is a fact about the hazard itself, never party knowledge "
        "(see world.area_connections comment)."
    ),
)

Index("ix_area_hazards_dungeon_area_id", area_hazards.c.dungeon_area_id)

area_interactables = Table(
    "area_interactables",
    metadata,
    _uuid_pk("area_interactable_id"),
    Column(
        "dungeon_area_id",
        UUID(),
        ForeignKey("world.dungeon_areas.dungeon_area_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("interactable_type", Text()),
    Column("description", Text()),
    Column("is_hidden", Boolean(), nullable=False, server_default=text("false")),
    *_timestamps(),
    schema="world",
    comment=(
        "An object or mechanism intended to receive actions — lever, control panel, "
        "lock, pylon, puzzle component, sealed hatch (docs/DOMAIN_MODEL.md §9.9). Not "
        "an entity. is_hidden is a fact about the interactable itself, never party "
        "knowledge (see world.area_connections comment)."
    ),
)

Index("ix_area_interactables_dungeon_area_id", area_interactables.c.dungeon_area_id)


# ---------------------------------------------------------------------------
# campaign — dungeon timeline state (revision 040)
# ---------------------------------------------------------------------------

location_state = Table(
    "location_state",
    metadata,
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "location_id",
        UUID(),
        ForeignKey("world.locations.location_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("is_searched", Boolean(), nullable=False, server_default=text("false")),
    Column("is_destroyed", Boolean(), nullable=False, server_default=text("false")),
    Column("alarm_level", NONNEGATIVE_INTEGER, nullable=False, server_default=text("0")),
    Column("condition_notes", Text()),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("timeline_id", "location_id"),
    schema="campaign",
    comment=(
        "Current per-timeline condition of a location: searched, destroyed, alarm "
        'level, free-text notes (e.g. "flooded", "smoldering ruins"). One row per '
        "(timeline, location) — see this revision's docstring on event linkage."
    ),
)

Index("ix_location_state_location_id", location_state.c.location_id)

connection_statuses = _lookup_table(
    "campaign",
    "connection_statuses",
    "connection_status_id",
    "Current condition of an area connection (open, closed, locked, broken, "
    "destroyed) — docs/architecture/DATABASE_MODEL.md §17.",
)

area_connection_state = Table(
    "area_connection_state",
    metadata,
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "area_connection_id",
        UUID(),
        ForeignKey("world.area_connections.area_connection_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "connection_status_id",
        UUID(),
        ForeignKey("campaign.connection_statuses.connection_status_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("timeline_id", "area_connection_id"),
    schema="campaign",
    comment=(
        "Current per-timeline condition of an area connection. Deliberately separate "
        "from whether any party has discovered the connection exists — that is "
        "knowledge state (docs/architecture/DATABASE_MODEL.md §9.3, revision 041), "
        "never stored here."
    ),
)

Index(
    "ix_area_connection_state_area_connection_id",
    area_connection_state.c.area_connection_id,
)
Index(
    "ix_area_connection_state_connection_status_id",
    area_connection_state.c.connection_status_id,
)

area_feature_state = Table(
    "area_feature_state",
    metadata,
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "area_feature_id",
        UUID(),
        ForeignKey("world.area_features.area_feature_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("is_destroyed", Boolean(), nullable=False, server_default=text("false")),
    Column("condition_notes", Text()),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("timeline_id", "area_feature_id"),
    schema="campaign",
    comment=(
        "Current per-timeline condition of an area feature (defaced, destroyed, "
        "altered) — never whether a party has noticed it (revision 041)."
    ),
)

Index("ix_area_feature_state_area_feature_id", area_feature_state.c.area_feature_id)

hazard_statuses = _lookup_table(
    "campaign",
    "hazard_statuses",
    "hazard_status_id",
    "Current status of a hazard (armed, triggered, reset, bypassed, disarmed) — "
    "docs/architecture/DATABASE_MODEL.md §17.",
)

hazard_state = Table(
    "hazard_state",
    metadata,
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "area_hazard_id",
        UUID(),
        ForeignKey("world.area_hazards.area_hazard_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "hazard_status_id",
        UUID(),
        ForeignKey("campaign.hazard_statuses.hazard_status_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("timeline_id", "area_hazard_id"),
    schema="campaign",
    comment=(
        "Current per-timeline status of a hazard. Separate from whether any party "
        "knows the hazard exists (revision 041)."
    ),
)

Index("ix_hazard_state_area_hazard_id", hazard_state.c.area_hazard_id)
Index("ix_hazard_state_hazard_status_id", hazard_state.c.hazard_status_id)

interactable_statuses = _lookup_table(
    "campaign",
    "interactable_statuses",
    "interactable_status_id",
    "Current status of an interactable (active, inactive, activated, "
    "deactivated, broken, locked) — docs/architecture/DATABASE_MODEL.md §17.",
)

interactable_state = Table(
    "interactable_state",
    metadata,
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "area_interactable_id",
        UUID(),
        ForeignKey("world.area_interactables.area_interactable_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "interactable_status_id",
        UUID(),
        ForeignKey("campaign.interactable_statuses.interactable_status_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("timeline_id", "area_interactable_id"),
    schema="campaign",
    comment=(
        "Current per-timeline status of an interactable (a shrine activated, a lever "
        "thrown, a pylon powered). Separate from whether any party knows it exists "
        "(revision 041)."
    ),
)

Index(
    "ix_interactable_state_area_interactable_id",
    interactable_state.c.area_interactable_id,
)
Index(
    "ix_interactable_state_interactable_status_id",
    interactable_state.c.interactable_status_id,
)


# ---------------------------------------------------------------------------
# knowledge — knowledge items, entity knowledge, party discoveries (revision 041)
# ---------------------------------------------------------------------------

knowledge_types = _lookup_table(
    "knowledge",
    "knowledge_types",
    "knowledge_type_id",
    "The kind of claim a knowledge item represents (claim, belief, secret, "
    "rumor, memory, instruction, theory) — docs/DOMAIN_MODEL.md §15.1.",
)

truth_statuses = _lookup_table(
    "knowledge",
    "truth_statuses",
    "truth_status_id",
    "How a knowledge item relates to canonical truth (true, false, partially "
    "true, disputed, unknown, no objective truth) — "
    "docs/DATABASE_CONVENTIONS.md §15.2.",
)

knowledge_items = Table(
    "knowledge_items",
    metadata,
    Column(
        "knowledge_item_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "knowledge_type_id",
        UUID(),
        ForeignKey("knowledge.knowledge_types.knowledge_type_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "truth_status_id",
        UUID(),
        ForeignKey("knowledge.truth_statuses.truth_status_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("canonical_statement", Text(), nullable=False),
    Column(
        "sensitivity",
        Text(),
        nullable=False,
        server_default=text("'public'::text"),
        comment=(
            "A fixed, universal classification (public, restricted, secret, dangerous), "
            "not a lookup — same reasoning as character.characters.size_category (Phase 4)."
        ),
    ),
    Column(
        "subject_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="SET NULL"),
        comment=(
            "The core.entities row this knowledge is about (an NPC, a location, an "
            "organization, ...), when it has one. At most one subject_* column is set."
        ),
    ),
    Column(
        "subject_area_connection_id",
        UUID(),
        ForeignKey("world.area_connections.area_connection_id", ondelete="SET NULL"),
        comment=(
            'The area connection this knowledge is about (e.g. "a secret door exists '
            'here"), when it has one. Connections are not entities (revision 039), so '
            "this direct reference exists alongside subject_entity_id rather than "
            "through it."
        ),
    ),
    Column(
        "subject_area_feature_id",
        UUID(),
        ForeignKey("world.area_features.area_feature_id", ondelete="SET NULL"),
    ),
    Column(
        "subject_area_hazard_id",
        UUID(),
        ForeignKey("world.area_hazards.area_hazard_id", ondelete="SET NULL"),
    ),
    Column(
        "subject_area_interactable_id",
        UUID(),
        ForeignKey("world.area_interactables.area_interactable_id", ondelete="SET NULL"),
    ),
    *_timestamps(),
    schema="knowledge",
    comment=(
        "A specific claim, belief, secret, rumor, memory, instruction, or theory "
        "(docs/DOMAIN_MODEL.md §15.1). Entity-rooted like any other important world "
        "object. subject_* columns are a deliberately simplified single-subject "
        "reference — see this revision's docstring."
    ),
)

Index("ix_knowledge_items_knowledge_type_id", knowledge_items.c.knowledge_type_id)
Index("ix_knowledge_items_truth_status_id", knowledge_items.c.truth_status_id)
Index(
    "ix_knowledge_items_subject_entity_id",
    knowledge_items.c.subject_entity_id,
    postgresql_where=knowledge_items.c.subject_entity_id.isnot(None),
)
Index(
    "ix_knowledge_items_subject_area_connection_id",
    knowledge_items.c.subject_area_connection_id,
    postgresql_where=knowledge_items.c.subject_area_connection_id.isnot(None),
)
Index(
    "ix_knowledge_items_subject_area_feature_id",
    knowledge_items.c.subject_area_feature_id,
    postgresql_where=knowledge_items.c.subject_area_feature_id.isnot(None),
)
Index(
    "ix_knowledge_items_subject_area_hazard_id",
    knowledge_items.c.subject_area_hazard_id,
    postgresql_where=knowledge_items.c.subject_area_hazard_id.isnot(None),
)
Index(
    "ix_knowledge_items_subject_area_interactable_id",
    knowledge_items.c.subject_area_interactable_id,
    postgresql_where=knowledge_items.c.subject_area_interactable_id.isnot(None),
)

entity_knowledge = Table(
    "entity_knowledge",
    metadata,
    _uuid_pk("entity_knowledge_id"),
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "knowledge_item_id",
        UUID(),
        ForeignKey("knowledge.knowledge_items.knowledge_item_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "knower_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("awareness_level", Text(), nullable=False, server_default=text("'aware'::text")),
    Column("confidence", PERCENTAGE_0_100),
    Column("interpretation", Text()),
    Column(
        "learned_source",
        Text(),
        comment=(
            "Free-text placeholder for how this was learned until interaction/event "
            "records exist (Phase 6) to reference instead."
        ),
    ),
    Column(
        "learned_at_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="SET NULL"),
    ),
    Column("willing_to_share", Boolean(), nullable=False, server_default=text("true")),
    *_timestamps(),
    UniqueConstraint(
        "timeline_id", "knowledge_item_id", "knower_entity_id", name="ux_entity_knowledge_current"
    ),
    schema="knowledge",
    comment=(
        "What a knower believes about a knowledge item on a timeline: awareness, "
        "confidence, interpretation, source, sharing willingness "
        "(docs/DOMAIN_MODEL.md §15.3). A false belief is valid game data and is never "
        "overwritten merely because the canonical truth is known elsewhere. One row "
        "per (timeline, knowledge item, knower) — see revision 021's docstring on "
        "event linkage, which applies unchanged here."
    ),
)

Index("ix_entity_knowledge_knowledge_item_id", entity_knowledge.c.knowledge_item_id)
Index("ix_entity_knowledge_knower_entity_id", entity_knowledge.c.knower_entity_id)
Index(
    "ix_entity_knowledge_learned_at_world_time_id",
    entity_knowledge.c.learned_at_world_time_id,
    postgresql_where=entity_knowledge.c.learned_at_world_time_id.isnot(None),
)

party_discoveries = Table(
    "party_discoveries",
    metadata,
    _uuid_pk("party_discovery_id"),
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "knowledge_item_id",
        UUID(),
        ForeignKey("knowledge.knowledge_items.knowledge_item_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("party_id", UUID(), ForeignKey("campaign.parties.party_id", ondelete="CASCADE")),
    Column("knower_entity_id", UUID(), ForeignKey("core.entities.entity_id", ondelete="CASCADE")),
    Column(
        "discovered_at_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="SET NULL"),
    ),
    Column(
        "discovery_method",
        Text(),
        comment=(
            "Free-text placeholder for how this was discovered until interaction/event "
            "records exist (Phase 6) to reference instead."
        ),
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    schema="knowledge",
    comment=(
        "The discovery record: when and how a party or individual knower learned a "
        "knowledge item (docs/architecture/DATABASE_MODEL.md §15). Recipient is "
        "exactly one of party_id (party-level discovery) or knower_entity_id "
        "(individual character, NPC, or organization discovery) — public/regional "
        "discovery (knowledge.public_knowledge) is deferred to Phase 7."
    ),
)

Index("ix_party_discoveries_knowledge_item_id", party_discoveries.c.knowledge_item_id)
Index(
    "ix_party_discoveries_party_id",
    party_discoveries.c.party_id,
    postgresql_where=party_discoveries.c.party_id.isnot(None),
)
Index(
    "ix_party_discoveries_knower_entity_id",
    party_discoveries.c.knower_entity_id,
    postgresql_where=party_discoveries.c.knower_entity_id.isnot(None),
)
Index(
    "ix_party_discoveries_discovered_at_world_time_id",
    party_discoveries.c.discovered_at_world_time_id,
    postgresql_where=party_discoveries.c.discovered_at_world_time_id.isnot(None),
)
Index(
    "ux_party_discoveries_party",
    party_discoveries.c.timeline_id,
    party_discoveries.c.knowledge_item_id,
    party_discoveries.c.party_id,
    unique=True,
    postgresql_where=party_discoveries.c.party_id.isnot(None),
)
Index(
    "ux_party_discoveries_knower",
    party_discoveries.c.timeline_id,
    party_discoveries.c.knowledge_item_id,
    party_discoveries.c.knower_entity_id,
    unique=True,
    postgresql_where=party_discoveries.c.knower_entity_id.isnot(None),
)


# ---------------------------------------------------------------------------
# campaign — character_location_history (revision 042)
# ---------------------------------------------------------------------------

character_location_history = Table(
    "character_location_history",
    metadata,
    _uuid_pk("character_location_history_id"),
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "location_id",
        UUID(),
        ForeignKey("world.locations.location_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "arrived_at_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
        nullable=False,
        comment=(
            "Required — the interval's finite start (ADR 0010). Renamed in spirit to "
            "effective_from: every history row needs a real endpoint to participate in "
            "range overlap."
        ),
    ),
    Column(
        "departed_at_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
        comment=(
            "NULL means the character is still at this location — the single "
            'representation of "current location", same convention as '
            "campaign.party_memberships.effective_to_world_time_id."
        ),
    ),
    # Added by revision 043, replacing the revision-042 partial unique index
    # with the full ADR 0010 interval contract.
    Column(
        "location_period",
        INT8RANGE(),
        comment=(
            "Derived, never client-authoritative: an INT8RANGE over "
            "arrived_at_world_time_id/departed_at_world_time_id's sort_key values, "
            "rebuilt by trigger on every INSERT and UPDATE — same role as "
            "campaign.party_memberships.effective_period (ADR 0010)."
        ),
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    schema="campaign",
    comment=(
        "Where a character has been on a timeline. The row with "
        "departed_at_world_time_id IS NULL is the character's current location — at "
        "most one per (timeline, character), enforced by a partial unique index. "
        "Deferred from Phase 4 until world.locations existed "
        "(docs/architecture/DATABASE_MODEL.md §17)."
    ),
)

# The exclusion constraint (ex_character_location_history_no_overlap,
# revision 043) is intentionally absent from this metadata, same reasoning as
# campaign.party_memberships — alembic check does not compare exclusion
# constraints. Covered by tests/database/test_character_location_temporal_integrity.py.
Index("ix_character_location_history_character_id", character_location_history.c.character_id)
Index("ix_character_location_history_location_id", character_location_history.c.location_id)
Index(
    "ix_character_location_history_arrived_at_world_time_id",
    character_location_history.c.arrived_at_world_time_id,
)
Index(
    "ix_character_location_history_departed_at_world_time_id",
    character_location_history.c.departed_at_world_time_id,
    postgresql_where=character_location_history.c.departed_at_world_time_id.isnot(None),
)
