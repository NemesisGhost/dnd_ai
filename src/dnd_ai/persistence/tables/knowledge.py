"""Knowledge tables — knowledge schema.

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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

from ._shared import (
    PERCENTAGE_0_100,
    _lookup_table,
    _timestamps,
    _uuid_pk,
    metadata,
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
