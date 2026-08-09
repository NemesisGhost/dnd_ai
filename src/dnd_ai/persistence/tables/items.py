"""Item domain tables — rules, world, campaign, and knowledge schemas
(revision 077).

Part of the src/dnd_ai/persistence/tables package. See
src/dnd_ai/persistence/tables/__init__.py for the metadata-authority note
this module inherits: this is compared against the live database by
`alembic check`, so declared tables/columns/comments must match migrations
exactly.

CHECK constraints, exclusion constraints, triggers, and the
campaign.character_inventory view are not declared here — see that same
__init__.py note for why (alembic does not compare them; tests cover the
constraints/triggers, and views are not autogenerate-tracked at all).
"""

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ._shared import (
    NONNEGATIVE_INTEGER,
    PERCENTAGE_0_100,
    _lookup_table,
    _provenance_columns,
    _timestamps,
    _uuid_pk,
    metadata,
)

# ---------------------------------------------------------------------------
# rules — item_categories, item_definitions
# ---------------------------------------------------------------------------

item_categories = _lookup_table(
    "rules",
    "item_categories",
    "item_category_id",
    "The mechanical category of an item definition (docs/DOMAIN_MODEL.md "
    "§12.1) — weapon, armor, shield, ammunition, potion, scroll, ring, rod, "
    "staff, wand, wondrous_item, tool, gear, treasure, other. Global, not "
    "ruleset-scoped: the taxonomy itself is stable across rulesets even "
    "though individual item definitions are not.",
)

item_definitions = Table(
    "item_definitions",
    metadata,
    _uuid_pk("item_definition_id"),
    Column(
        "ruleset_version_id",
        UUID(),
        ForeignKey("rules.ruleset_versions.ruleset_version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "item_category_id",
        UUID(),
        ForeignKey("rules.item_categories.item_category_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    Column("rarity", Text(), nullable=False, server_default=text("'common'::text")),
    Column("requires_attunement", Boolean(), nullable=False, server_default=text("false")),
    Column("weight", Numeric(8, 2)),
    Column("base_cost_gp", Numeric(12, 2)),
    Column(
        "properties_jsonb",
        JSONB(),
        comment=(
            "Category-specific mechanical stats (damage dice, AC bonus, charges, ...) — "
            "ruleset-specific calculation detail, an explicitly acceptable JSONB use "
            "(conventions §5.7). NULL for items with no mechanical effect beyond their "
            "description."
        ),
    ),
    *_provenance_columns(),
    *_timestamps(),
    UniqueConstraint("ruleset_version_id", "code", name="ux_item_definitions_ruleset_version_code"),
    schema="rules",
    comment=(
        "A reusable mechanical item definition (docs/DOMAIN_MODEL.md §12.1) — a generic "
        "longsword, a healing potion, a spell scroll. world.item_instances (below) "
        "references this for a particular object in the world; definition and instance "
        "are deliberately never the same row (conventions §34)."
    ),
)

Index("ix_item_definitions_ruleset_version_id", item_definitions.c.ruleset_version_id)
Index("ix_item_definitions_item_category_id", item_definitions.c.item_category_id)
Index(
    "ix_item_definitions_source_id",
    item_definitions.c.source_id,
    postgresql_where=item_definitions.c.source_id.isnot(None),
)
Index("ix_item_definitions_canon_status_id", item_definitions.c.canon_status_id)

# ---------------------------------------------------------------------------
# world — item_instances, item_containers
# ---------------------------------------------------------------------------

item_instances = Table(
    "item_instances",
    metadata,
    Column(
        "item_instance_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "item_definition_id",
        UUID(),
        ForeignKey("rules.item_definitions.item_definition_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "origin_notes",
        Text(),
        comment=(
            "Free-text provenance/lore for this specific instance (crafted by, found "
            "where, ...) — distinct from core.sources, which records where the "
            "definition's rules text came from."
        ),
    ),
    *_timestamps(),
    schema="world",
    comment=(
        "A particular object in the world (docs/DOMAIN_MODEL.md §12.2) — a named "
        "legendary sword, a specific healing potion in a chest. Entity-rooted: title, "
        "summary, canon status, and source are inherited from core.entities. "
        "item_definition_id is the reusable mechanical definition this is an example "
        "of. Current location, possessor, owner, condition, charges, and equipped "
        "state are timeline state (campaign.item_state/.item_ownership/."
        "inventory_entries, below), not columns here — the same definition/state "
        "split world.organizations draws against campaign.organization_state."
    ),
)

Index("ix_item_instances_item_definition_id", item_instances.c.item_definition_id)

item_containers = Table(
    "item_containers",
    metadata,
    Column(
        "container_id",
        UUID(),
        ForeignKey("world.item_instances.item_instance_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("capacity_weight", Numeric(8, 2)),
    Column("capacity_items", NONNEGATIVE_INTEGER),
    *_timestamps(),
    schema="world",
    comment=(
        "Marks an item instance as capable of holding other items (a backpack, a "
        "quiver, a chest) — a 1:1 extension of world.item_instances, not every item "
        "is a container, and not a second core.entity_types subtype "
        "(docs/DOMAIN_MODEL.md §12). capacity_weight/capacity_items are optional "
        "mechanical limits. campaign.inventory_entries.container_id (below) "
        "references this table for items currently stored inside one."
    ),
)

# ---------------------------------------------------------------------------
# campaign — item_state, item_ownership, inventory_entries, item_attunements
# ---------------------------------------------------------------------------

item_state = Table(
    "item_state",
    metadata,
    _uuid_pk("item_state_id"),
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "item_instance_id",
        UUID(),
        ForeignKey("world.item_instances.item_instance_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("quantity", NONNEGATIVE_INTEGER, nullable=False, server_default=text("1")),
    Column("condition_percentage", PERCENTAGE_0_100),
    Column("charges_current", NONNEGATIVE_INTEGER),
    Column("charges_maximum", NONNEGATIVE_INTEGER),
    Column("is_equipped", Boolean(), nullable=False, server_default=text("false")),
    Column("is_destroyed", Boolean(), nullable=False, server_default=text("false")),
    Column(
        "last_event_id",
        UUID(),
        ForeignKey("narrative.events.event_id", ondelete="SET NULL"),
        comment=(
            "The event that produced this row's current values, when there was one "
            "(conventions §13.4). NULL for administrative/import-driven changes with "
            "no causing event."
        ),
    ),
    *_timestamps(),
    UniqueConstraint("timeline_id", "item_instance_id", name="ux_item_state_timeline_item"),
    schema="campaign",
    comment=(
        "Tracks an item instance's current condition for a timeline "
        "(docs/architecture/DATABASE_MODEL.md §17) — quantity (for stackable items), "
        "condition, charges, equipped and destroyed status. Can diverge after a "
        "branch and evolve from events, unlike the stable world.item_instances "
        "definition row. One current row per (timeline, item instance)."
    ),
)

Index("ix_item_state_timeline_id", item_state.c.timeline_id)
Index("ix_item_state_item_instance_id", item_state.c.item_instance_id)
Index(
    "ix_item_state_last_event_id",
    item_state.c.last_event_id,
    postgresql_where=item_state.c.last_event_id.isnot(None),
)

item_ownership = Table(
    "item_ownership",
    metadata,
    _uuid_pk("item_ownership_id"),
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "item_instance_id",
        UUID(),
        ForeignKey("world.item_instances.item_instance_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "owner_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="SET NULL"),
    ),
    Column(
        "acquired_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="SET NULL"),
    ),
    Column(
        "last_event_id",
        UUID(),
        ForeignKey("narrative.events.event_id", ondelete="SET NULL"),
    ),
    *_timestamps(),
    UniqueConstraint("timeline_id", "item_instance_id", name="ux_item_ownership_timeline_item"),
    schema="campaign",
    comment=(
        "Tracks an item instance's current legal owner for a timeline — distinct "
        "from who currently possesses it (campaign.inventory_entries, below), per "
        "docs/DOMAIN_MODEL.md §12.4. owner_entity_id NULL means unowned/unclaimed "
        "(loose treasure). One current row per (timeline, item instance)."
    ),
)

Index("ix_item_ownership_timeline_id", item_ownership.c.timeline_id)
Index("ix_item_ownership_item_instance_id", item_ownership.c.item_instance_id)
Index(
    "ix_item_ownership_owner_entity_id",
    item_ownership.c.owner_entity_id,
    postgresql_where=item_ownership.c.owner_entity_id.isnot(None),
)
Index(
    "ix_item_ownership_acquired_world_time_id",
    item_ownership.c.acquired_world_time_id,
    postgresql_where=item_ownership.c.acquired_world_time_id.isnot(None),
)
Index(
    "ix_item_ownership_last_event_id",
    item_ownership.c.last_event_id,
    postgresql_where=item_ownership.c.last_event_id.isnot(None),
)

inventory_entries = Table(
    "inventory_entries",
    metadata,
    _uuid_pk("inventory_entry_id"),
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "item_instance_id",
        UUID(),
        ForeignKey("world.item_instances.item_instance_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "holder_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="SET NULL"),
    ),
    Column(
        "container_id",
        UUID(),
        ForeignKey("world.item_containers.container_id", ondelete="SET NULL"),
    ),
    Column(
        "location_id",
        UUID(),
        ForeignKey("world.locations.location_id", ondelete="SET NULL"),
    ),
    Column(
        "last_event_id",
        UUID(),
        ForeignKey("narrative.events.event_id", ondelete="SET NULL"),
    ),
    *_timestamps(),
    UniqueConstraint("timeline_id", "item_instance_id", name="ux_inventory_entries_timeline_item"),
    schema="campaign",
    comment=(
        "Tracks who or what currently possesses an item instance for a timeline — "
        "distinct from who legally owns it (campaign.item_ownership, above), per "
        "docs/DOMAIN_MODEL.md §12.4. At most one of holder_entity_id (carried by a "
        "character/creature), container_id (stored inside another item), or "
        "location_id (lying at a place) is set; zero set means not yet placed. One "
        "current row per (timeline, item instance)."
    ),
)

Index("ix_inventory_entries_timeline_id", inventory_entries.c.timeline_id)
Index("ix_inventory_entries_item_instance_id", inventory_entries.c.item_instance_id)
Index(
    "ix_inventory_entries_holder_entity_id",
    inventory_entries.c.holder_entity_id,
    postgresql_where=inventory_entries.c.holder_entity_id.isnot(None),
)
Index(
    "ix_inventory_entries_container_id",
    inventory_entries.c.container_id,
    postgresql_where=inventory_entries.c.container_id.isnot(None),
)
Index(
    "ix_inventory_entries_location_id",
    inventory_entries.c.location_id,
    postgresql_where=inventory_entries.c.location_id.isnot(None),
)
Index(
    "ix_inventory_entries_last_event_id",
    inventory_entries.c.last_event_id,
    postgresql_where=inventory_entries.c.last_event_id.isnot(None),
)

item_attunements = Table(
    "item_attunements",
    metadata,
    _uuid_pk("item_attunement_id"),
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "item_instance_id",
        UUID(),
        ForeignKey("world.item_instances.item_instance_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "attuned_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
    ),
    Column(
        "broken_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
    ),
    Column(
        "last_event_id",
        UUID(),
        ForeignKey("narrative.events.event_id", ondelete="SET NULL"),
    ),
    *_timestamps(),
    schema="campaign",
    comment=(
        "A character's attunement to an item instance on a timeline "
        "(docs/DOMAIN_MODEL.md §12.3). broken_world_time_id NULL means the "
        "attunement is still active. ux_item_attunements_active_per_item (below) "
        "enforces the D&D rule that only one creature may be attuned to a given "
        'item at a time; the "at most 3 items per character" rule is a '
        "command-layer concern (see this revision's docstring)."
    ),
)

Index("ix_item_attunements_timeline_id", item_attunements.c.timeline_id)
Index("ix_item_attunements_item_instance_id", item_attunements.c.item_instance_id)
Index("ix_item_attunements_character_id", item_attunements.c.character_id)
Index(
    "ix_item_attunements_attuned_world_time_id",
    item_attunements.c.attuned_world_time_id,
    postgresql_where=item_attunements.c.attuned_world_time_id.isnot(None),
)
Index(
    "ix_item_attunements_broken_world_time_id",
    item_attunements.c.broken_world_time_id,
    postgresql_where=item_attunements.c.broken_world_time_id.isnot(None),
)
Index(
    "ix_item_attunements_last_event_id",
    item_attunements.c.last_event_id,
    postgresql_where=item_attunements.c.last_event_id.isnot(None),
)
Index(
    "ux_item_attunements_active_per_item",
    item_attunements.c.timeline_id,
    item_attunements.c.item_instance_id,
    unique=True,
    postgresql_where=item_attunements.c.broken_world_time_id.is_(None),
)

# ---------------------------------------------------------------------------
# knowledge — item_identification
# ---------------------------------------------------------------------------

item_identification = Table(
    "item_identification",
    metadata,
    _uuid_pk("item_identification_id"),
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "item_instance_id",
        UUID(),
        ForeignKey("world.item_instances.item_instance_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "knower_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "identification_level",
        Text(),
        nullable=False,
        server_default=text("'unidentified'::text"),
    ),
    Column(
        "known_properties_jsonb",
        JSONB(),
        comment=(
            "Which of rules.item_definitions.properties_jsonb's keys this knower "
            "currently knows, when identification is partial — ruleset-specific "
            "detail, an acceptable JSONB use (conventions §5.7). NULL is normal for "
            "unidentified or fully identified rows."
        ),
    ),
    Column(
        "identified_at_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="SET NULL"),
    ),
    Column(
        "last_event_id",
        UUID(),
        ForeignKey("narrative.events.event_id", ondelete="SET NULL"),
    ),
    *_timestamps(),
    UniqueConstraint(
        "timeline_id",
        "item_instance_id",
        "knower_entity_id",
        name="ux_item_identification_timeline_item_knower",
    ),
    schema="knowledge",
    comment=(
        "What a knower currently knows about an item instance's hidden properties, "
        "per timeline (docs/DOMAIN_MODEL.md §12.5) — different characters may know "
        "different properties of the same item. One row per (timeline, item "
        "instance, knower)."
    ),
)

Index("ix_item_identification_timeline_id", item_identification.c.timeline_id)
Index("ix_item_identification_item_instance_id", item_identification.c.item_instance_id)
Index("ix_item_identification_knower_entity_id", item_identification.c.knower_entity_id)
Index(
    "ix_item_identification_identified_at_world_time_id",
    item_identification.c.identified_at_world_time_id,
    postgresql_where=item_identification.c.identified_at_world_time_id.isnot(None),
)
Index(
    "ix_item_identification_last_event_id",
    item_identification.c.last_event_id,
    postgresql_where=item_identification.c.last_event_id.isnot(None),
)
