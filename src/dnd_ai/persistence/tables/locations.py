"""World and dungeon locations tables — world schema.

Part of the src/dnd_ai/persistence/tables package. See
src/dnd_ai/persistence/tables/__init__.py for the metadata-authority note
this module inherits: this is compared against the live database by
`alembic check`, so declared tables/columns/comments must match migrations
exactly.
"""

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from ._shared import (
    NONNEGATIVE_INTEGER,
    RATING_1_10,
    _lookup_table,
    _timestamps,
    _uuid_pk,
    metadata,
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
            'key" or "only open while the beacon is lit"). Required when is_conditional '
            "is true, and must contain at least one non-whitespace character — space, "
            "tab, newline, and carriage-return-only values are all treated as blank and "
            "rejected (ck_area_connections_conditional_description_paired). Must be "
            "NULL when is_conditional is false. Not yet machine-evaluable — same "
            "placeholder shape as campaign.character_conditions.source_description."
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
