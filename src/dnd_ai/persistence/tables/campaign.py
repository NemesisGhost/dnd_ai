"""Campaign and timeline state tables — campaign schema.

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
    PrimaryKeyConstraint,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import INT8RANGE, TIMESTAMP, UUID
from sqlalchemy.types import Integer

from ._shared import (
    NONNEGATIVE_INTEGER,
    _lookup_table,
    _timestamps,
    _uuid_pk,
    metadata,
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
        nullable=False,
        comment=(
            "Derived, never client-authoritative: an INT8RANGE over "
            "arrived_at_world_time_id/departed_at_world_time_id's sort_key values, "
            "rebuilt by trigger on every INSERT and UPDATE — same role and same NOT "
            "NULL contract as campaign.party_memberships.effective_period (ADR 0010)."
        ),
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    schema="campaign",
    comment=(
        "Where a character has been on a timeline. The row with "
        "departed_at_world_time_id IS NULL is the character's current location — the "
        "single current-location representation, enforced by the derived "
        "location_period range together with the ex_character_location_history_no_"
        "overlap exclusion constraint over (timeline_id, character_id, "
        "location_period), the same ADR 0010 shape as campaign.party_memberships. "
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
