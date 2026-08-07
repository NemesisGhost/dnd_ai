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
from sqlalchemy.dialects.postgresql import INT8RANGE, TIMESTAMP, UUID

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
    # Added by revision 073 (ADR 0010 shape, no EXCLUDE — see that revision's
    # docstring for why both endpoints are nullable rather than a required start).
    Column(
        "effective_from_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
        comment=(
            "When this claim became true in the fictional world, if tracked (ADR "
            "0010). NULL means no validity window is tracked for this item at all "
            '— most claims ("the king is corrupt") have no meaningful start.'
        ),
    ),
    Column(
        "effective_to_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
        comment=(
            "When this claim stopped being true, if known. NULL with "
            "effective_from_world_time_id set means still current. Must be NULL if "
            "effective_from_world_time_id is NULL "
            "(ck_knowledge_items_validity_requires_start)."
        ),
    ),
    Column(
        "validity_period",
        INT8RANGE(),
        comment=(
            "Database-derived INT8RANGE over the two world-time columns' sort_key "
            "values (ADR 0010), half-open [from, to). NULL when no validity window "
            "is tracked. No EXCLUDE constraint: a knowledge item has exactly one "
            "validity row, so there is nothing for it to overlap."
        ),
    ),
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
Index(
    "ix_knowledge_items_effective_from_world_time_id",
    knowledge_items.c.effective_from_world_time_id,
    postgresql_where=knowledge_items.c.effective_from_world_time_id.isnot(None),
)
Index(
    "ix_knowledge_items_effective_to_world_time_id",
    knowledge_items.c.effective_to_world_time_id,
    postgresql_where=knowledge_items.c.effective_to_world_time_id.isnot(None),
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
        "learned_at_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="SET NULL"),
    ),
    Column("willing_to_share", Boolean(), nullable=False, server_default=text("true")),
    *_timestamps(),
    # Added by revision 063, once interaction.interactions/narrative.events
    # existed to point at — replaces the revision-041 learned_source TEXT
    # placeholder.
    Column(
        "learned_via_interaction_id",
        UUID(),
        ForeignKey("interaction.interactions.interaction_id", ondelete="SET NULL"),
        comment=(
            "The interaction through which this knower learned this, when recorded. "
            "At most one of learned_via_interaction_id/learned_via_event_id is set; "
            "both NULL means an unrecorded or administrative source (e.g. seeded "
            "starting knowledge). Closes the free-text learned_source placeholder "
            "(revision 041)."
        ),
    ),
    Column(
        "learned_via_event_id",
        UUID(),
        ForeignKey("narrative.events.event_id", ondelete="SET NULL"),
        comment=(
            "The event through which this knower learned this (e.g. witnessing it "
            "directly), when recorded. See learned_via_interaction_id."
        ),
    ),
    # Added by revision 073, once knowledge.knowledge_versions existed to
    # point at — closes revision 041's own "nothing to version yet" placeholder.
    Column(
        "knowledge_version_id",
        UUID(),
        ForeignKey("knowledge.knowledge_versions.knowledge_version_id", ondelete="SET NULL"),
        comment=(
            "The specific (possibly distorted) version this knower heard, when it "
            "was a distorted retelling rather than the canonical statement. Closes "
            "revision 041's own documented placeholder (\"references a bare "
            "knowledge_item_id, not a version, since nothing to version exists "
            'yet") now that knowledge.knowledge_versions exists. NULL is still the '
            "common case — most beliefs reference the item directly."
        ),
    ),
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
Index(
    "ix_entity_knowledge_learned_via_interaction_id",
    entity_knowledge.c.learned_via_interaction_id,
    postgresql_where=entity_knowledge.c.learned_via_interaction_id.isnot(None),
)
Index(
    "ix_entity_knowledge_learned_via_event_id",
    entity_knowledge.c.learned_via_event_id,
    postgresql_where=entity_knowledge.c.learned_via_event_id.isnot(None),
)
Index(
    "ix_entity_knowledge_knowledge_version_id",
    entity_knowledge.c.knowledge_version_id,
    postgresql_where=entity_knowledge.c.knowledge_version_id.isnot(None),
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
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    # Added by revision 063, once interaction.interactions/narrative.events
    # existed to point at — replaces the revision-041 discovery_method TEXT
    # placeholder.
    Column(
        "discovered_via_interaction_id",
        UUID(),
        ForeignKey("interaction.interactions.interaction_id", ondelete="SET NULL"),
        comment=(
            "The interaction through which this was discovered (a search check, a "
            "conversation), when recorded. At most one of "
            "discovered_via_interaction_id/discovered_via_event_id is set; both NULL "
            "means an unrecorded or administrative source. Closes the free-text "
            "discovery_method placeholder (revision 041)."
        ),
    ),
    Column(
        "discovered_via_event_id",
        UUID(),
        ForeignKey("narrative.events.event_id", ondelete="SET NULL"),
        comment=(
            "The event through which this was discovered, when recorded. See "
            "discovered_via_interaction_id."
        ),
    ),
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
    "ix_party_discoveries_discovered_via_interaction_id",
    party_discoveries.c.discovered_via_interaction_id,
    postgresql_where=party_discoveries.c.discovered_via_interaction_id.isnot(None),
)
Index(
    "ix_party_discoveries_discovered_via_event_id",
    party_discoveries.c.discovered_via_event_id,
    postgresql_where=party_discoveries.c.discovered_via_event_id.isnot(None),
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
# knowledge — versions, expertise, information transfers, public knowledge
# (revision 073)
# ---------------------------------------------------------------------------

knowledge_versions = Table(
    "knowledge_versions",
    metadata,
    _uuid_pk("knowledge_version_id"),
    Column(
        "knowledge_item_id",
        UUID(),
        ForeignKey("knowledge.knowledge_items.knowledge_item_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("version_statement", Text(), nullable=False),
    Column(
        "distortion_type",
        Text(),
        nullable=False,
        server_default=text("'embellishment'::text"),
        comment=(
            "An inferred, illustrative starter vocabulary — docs/DOMAIN_MODEL.md "
            "§15.2 does not enumerate distortion kinds, only the concept."
        ),
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    schema="knowledge",
    comment=(
        "A changed or distorted form of a knowledge item, supporting rumor "
        "mutation and incomplete reports (docs/DOMAIN_MODEL.md §15.2). Append-only "
        "— a new distortion is a new version, not an edit of an existing one."
    ),
)

Index("ix_knowledge_versions_knowledge_item_id", knowledge_versions.c.knowledge_item_id)

expertise_domains = _lookup_table(
    "knowledge",
    "expertise_domains",
    "expertise_domain_id",
    "An illustrative, extensible starter set of fields a character can have "
    "expertise in (docs/architecture/DATABASE_MODEL.md §15).",
)

character_expertise = Table(
    "character_expertise",
    metadata,
    _uuid_pk("character_expertise_id"),
    Column(
        "character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "expertise_domain_id",
        UUID(),
        ForeignKey("knowledge.expertise_domains.expertise_domain_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("proficiency_level", Text(), nullable=False, server_default=text("'trained'::text")),
    Column("notes", Text()),
    *_timestamps(),
    UniqueConstraint(
        "character_id", "expertise_domain_id", name="ux_character_expertise_character_domain"
    ),
    schema="knowledge",
    comment=(
        "What fields a character has expertise in (docs/architecture/DATABASE_MODEL.md "
        "§15). Character-level, not timeline-scoped state — expertise is treated as "
        "a stable trait of the character definition, the same latitude "
        "character.characters.size_category (revision 017) already takes."
    ),
)

Index("ix_character_expertise_character_id", character_expertise.c.character_id)
Index("ix_character_expertise_expertise_domain_id", character_expertise.c.expertise_domain_id)

information_transfers = Table(
    "information_transfers",
    metadata,
    _uuid_pk("information_transfer_id"),
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "source_entity_knowledge_id",
        UUID(),
        ForeignKey("knowledge.entity_knowledge.entity_knowledge_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "recipient_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "modified_interpretation",
        Text(),
        comment=(
            "The interpretation actually conveyed to the recipient, when it "
            "differs from the source's own entity_knowledge.interpretation — this "
            "is what supports rumor propagation and misinformation."
        ),
    ),
    Column("transfer_method", Text(), nullable=False, server_default=text("'dialogue'::text")),
    Column(
        "caused_by_interaction_id",
        UUID(),
        ForeignKey("interaction.interactions.interaction_id", ondelete="SET NULL"),
    ),
    Column(
        "caused_by_event_id",
        UUID(),
        ForeignKey("narrative.events.event_id", ondelete="SET NULL"),
    ),
    Column(
        "occurred_at_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="SET NULL"),
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    schema="knowledge",
    comment=(
        "Records communication between entities (docs/DOMAIN_MODEL.md §15.6): "
        "dialogue, written messages, public announcements, rumors, telepathy, "
        "magical visions. source_entity_knowledge_id identifies the source knower, "
        "their belief, and their interpretation together (knowledge.entity_knowledge "
        "already carries all three); modified_interpretation records what was "
        "actually conveyed, when it differs."
    ),
)

Index("ix_information_transfers_timeline_id", information_transfers.c.timeline_id)
Index(
    "ix_information_transfers_source_entity_knowledge_id",
    information_transfers.c.source_entity_knowledge_id,
)
Index(
    "ix_information_transfers_recipient_entity_id",
    information_transfers.c.recipient_entity_id,
)
Index(
    "ix_information_transfers_caused_by_interaction_id",
    information_transfers.c.caused_by_interaction_id,
    postgresql_where=information_transfers.c.caused_by_interaction_id.isnot(None),
)
Index(
    "ix_information_transfers_caused_by_event_id",
    information_transfers.c.caused_by_event_id,
    postgresql_where=information_transfers.c.caused_by_event_id.isnot(None),
)
Index(
    "ix_information_transfers_occurred_at_world_time_id",
    information_transfers.c.occurred_at_world_time_id,
    postgresql_where=information_transfers.c.occurred_at_world_time_id.isnot(None),
)

public_knowledge = Table(
    "public_knowledge",
    metadata,
    _uuid_pk("public_knowledge_id"),
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
        "location_id",
        UUID(),
        ForeignKey("world.locations.location_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("awareness_level", Text(), nullable=False, server_default=text("'aware'::text")),
    Column(
        "known_since_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="SET NULL"),
    ),
    *_timestamps(),
    UniqueConstraint(
        "timeline_id",
        "knowledge_item_id",
        "location_id",
        name="ux_public_knowledge_timeline_item_location",
    ),
    schema="knowledge",
    comment=(
        "What is known publicly within a location (a settlement, a region — "
        "regions are themselves locations via world.locations.parent_location_id, "
        "revision 038) independent of any one knower or party "
        "(docs/architecture/DATABASE_MODEL.md §15). Distinct from "
        "knowledge.entity_knowledge (a specific knower's belief) and "
        "knowledge.party_discoveries (a specific discovery event)."
    ),
)

Index("ix_public_knowledge_timeline_id", public_knowledge.c.timeline_id)
Index("ix_public_knowledge_knowledge_item_id", public_knowledge.c.knowledge_item_id)
Index("ix_public_knowledge_location_id", public_knowledge.c.location_id)
Index(
    "ix_public_knowledge_known_since_world_time_id",
    public_knowledge.c.known_since_world_time_id,
    postgresql_where=public_knowledge.c.known_since_world_time_id.isnot(None),
)
