"""Core platform tables — core schema.

Part of the src/dnd_ai/persistence/tables package. See
src/dnd_ai/persistence/tables/__init__.py for the metadata-authority note
this module inherits: this is compared against the live database by
`alembic check`, so declared tables/columns/comments must match migrations
exactly.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.types import Integer

from ._shared import (
    NONNEGATIVE_INTEGER,
    _lookup_table,
    _timestamps,
    _uuid_pk,
    metadata,
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
    "Where an authored or imported fact came from.",
)

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
        "required_subtype_pk_column",
        Text(),
        comment=(
            'Primary-key column name of required_subtype_table (e.g. "dungeon_id" for '
            '"world.dungeons"). Set together with required_subtype_table — never one '
            "without the other. Lets core.enforce_entity_type_change() check for an "
            "existing subtype row without guessing a column name from the table name."
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
        "record should reference one where practical."
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
