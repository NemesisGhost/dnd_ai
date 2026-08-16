"""Narrative tables — narrative schema.

Part of the src/dnd_ai/persistence/tables package. See
src/dnd_ai/persistence/tables/__init__.py for the metadata-authority note
this module inherits: this is compared against the live database by
`alembic check`, so declared tables/columns/comments must match migrations
exactly.
"""

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

from ._shared import (
    NONNEGATIVE_INTEGER,
    _lookup_table,
    _timestamps,
    _uuid_pk,
    metadata,
)

# ---------------------------------------------------------------------------
# narrative — events, participants, locations, causes, effects, observations
# (revision 057)
# ---------------------------------------------------------------------------

event_statuses = _lookup_table(
    "narrative",
    "event_statuses",
    "event_status_id",
    "Lifecycle status of a recorded event (draft, recorded, voided, "
    "corrected) — docs/ENTITY_LIFECYCLE.md §15.",
)

event_types = _lookup_table(
    "narrative",
    "event_types",
    "event_type_id",
    "The kind of occurrence an event represents. An illustrative, "
    "extensible starter set, not an exhaustive "
    "taxonomy.",
)

event_participant_roles = _lookup_table(
    "narrative",
    "event_participant_roles",
    "event_participant_role_id",
    "How an entity relates to an event it participated in — docs/DOMAIN_MODEL.md §13.2.",
)

events = Table(
    "events",
    metadata,
    Column(
        "event_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "timeline_id",
        UUID(),
        ForeignKey("campaign.timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "campaign_id",
        UUID(),
        ForeignKey("campaign.campaigns.campaign_id", ondelete="SET NULL"),
    ),
    Column(
        "session_id",
        UUID(),
        ForeignKey("campaign.sessions.session_id", ondelete="SET NULL"),
    ),
    Column(
        "event_type_id",
        UUID(),
        ForeignKey("narrative.event_types.event_type_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "event_status_id",
        UUID(),
        ForeignKey("narrative.event_statuses.event_status_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
        nullable=False,
        comment=(
            "The effective world time (or approximate period, via "
            "core.world_times's own label/precision support) at which this event "
            "occurred. Distinct from created_at, which is when it was recorded "
            "in the database."
        ),
    ),
    Column(
        "details",
        Text(),
        comment=(
            "Long-form narrative text. core.entities.canonical_name/summary "
            "cover the event's title and short summary."
        ),
    ),
    *_timestamps(),
    schema="narrative",
    comment=(
        "A significant occurrence in a timeline (docs/DOMAIN_MODEL.md §13.1). "
        "Entity-rooted like any other important world object — title, "
        "summary, source and recording time are inherited from core.entities "
        "rather than duplicated here. May reference a campaign and session "
        "when produced during play."
    ),
)

Index("ix_events_timeline_id", events.c.timeline_id)
Index(
    "ix_events_campaign_id",
    events.c.campaign_id,
    postgresql_where=events.c.campaign_id.isnot(None),
)
Index(
    "ix_events_session_id",
    events.c.session_id,
    postgresql_where=events.c.session_id.isnot(None),
)
Index("ix_events_event_type_id", events.c.event_type_id)
Index("ix_events_event_status_id", events.c.event_status_id)
Index("ix_events_world_time_id", events.c.world_time_id)

event_participants = Table(
    "event_participants",
    metadata,
    _uuid_pk("event_participant_id"),
    Column(
        "event_id",
        UUID(),
        ForeignKey("narrative.events.event_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "participant_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "participant_role_id",
        UUID(),
        ForeignKey(
            "narrative.event_participant_roles.event_participant_role_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("notes", Text()),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint(
        "event_id",
        "participant_entity_id",
        "participant_role_id",
        name="ux_event_participants_event_entity_role",
    ),
    schema="narrative",
    comment=(
        "Relates an entity to an event with a role — actor, target, "
        "witness, victim, beneficiary, organizer, location_controller "
        "(docs/DOMAIN_MODEL.md §13.2). Append-only."
    ),
)

Index("ix_event_participants_event_id", event_participants.c.event_id)
Index(
    "ix_event_participants_participant_entity_id",
    event_participants.c.participant_entity_id,
)
Index(
    "ix_event_participants_participant_role_id",
    event_participants.c.participant_role_id,
)

event_locations = Table(
    "event_locations",
    metadata,
    _uuid_pk("event_location_id"),
    Column(
        "event_id",
        UUID(),
        ForeignKey("narrative.events.event_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "location_id",
        UUID(),
        ForeignKey("world.locations.location_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "event_location_role",
        Text(),
        nullable=False,
        server_default=text("'occurred_at'::text"),
        comment=(
            "occurred_at (where the event took place) or affected (a location "
            "the event changed without being the site of the event). Fixed "
            "small vocabulary, not a lookup — same reasoning as "
            "knowledge_items.sensitivity (revision 041)."
        ),
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint(
        "event_id",
        "location_id",
        "event_location_role",
        name="ux_event_locations_event_location_role",
    ),
    schema="narrative",
    comment=(
        "Identifies where an event occurred or what locations it affected "
        "(docs/DOMAIN_MODEL.md §13.3). Append-only."
    ),
)

Index("ix_event_locations_event_id", event_locations.c.event_id)
Index("ix_event_locations_location_id", event_locations.c.location_id)

event_causes = Table(
    "event_causes",
    metadata,
    _uuid_pk("event_cause_id"),
    Column(
        "event_id",
        UUID(),
        ForeignKey("narrative.events.event_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "cause_event_id",
        UUID(),
        ForeignKey("narrative.events.event_id", ondelete="SET NULL"),
    ),
    Column(
        "cause_interaction_id",
        UUID(),
        ForeignKey("interaction.interactions.interaction_id", ondelete="SET NULL"),
        comment=(
            "The interaction that caused this event, when it was a recorded "
            "interaction rather than a prior event or an undocumented decision/"
            "condition. Closes the placeholder revision 057's docstring recorded."
        ),
    ),
    Column(
        "cause_encounter_id",
        UUID(),
        ForeignKey("narrative.encounters.encounter_id", ondelete="SET NULL"),
        comment=(
            "The encounter that caused this event, e.g. a character killed "
            "mid-combat — a fourth alternative alongside cause_event_id/"
            "cause_interaction_id/cause_description (conventions §9.4), closing "
            "this revision's own forward reference."
        ),
    ),
    Column(
        "cause_description",
        Text(),
        comment=(
            "Free-text placeholder for undocumented decisions or conditions — "
            "causes that are neither a prior event (cause_event_id) nor a "
            "recorded interaction (cause_interaction_id), e.g. a GM ruling or "
            "an ambient world condition."
        ),
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    schema="narrative",
    comment=(
        "Links an event to a prior event, a recorded interaction, or a "
        "free-text decision/condition, that caused it (docs/DOMAIN_MODEL.md "
        "§13.4). Exactly one of the three is set. Append-only."
    ),
)

Index("ix_event_causes_event_id", event_causes.c.event_id)
Index(
    "ix_event_causes_cause_event_id",
    event_causes.c.cause_event_id,
    postgresql_where=event_causes.c.cause_event_id.isnot(None),
)
Index(
    "ix_event_causes_cause_interaction_id",
    event_causes.c.cause_interaction_id,
    postgresql_where=event_causes.c.cause_interaction_id.isnot(None),
)
Index(
    "ix_event_causes_cause_encounter_id",
    event_causes.c.cause_encounter_id,
    postgresql_where=event_causes.c.cause_encounter_id.isnot(None),
)

event_effects = Table(
    "event_effects",
    metadata,
    _uuid_pk("event_effect_id"),
    Column(
        "event_id",
        UUID(),
        ForeignKey("narrative.events.event_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "target_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="SET NULL"),
        comment=(
            "The core.entities row this effect changed, when it has one. At "
            "most one target_* column is set — same pattern as "
            "knowledge.knowledge_items.subject_entity_id (revision 041)."
        ),
    ),
    Column(
        "target_area_connection_id",
        UUID(),
        ForeignKey("world.area_connections.area_connection_id", ondelete="SET NULL"),
    ),
    Column(
        "target_area_feature_id",
        UUID(),
        ForeignKey("world.area_features.area_feature_id", ondelete="SET NULL"),
    ),
    Column(
        "target_area_hazard_id",
        UUID(),
        ForeignKey("world.area_hazards.area_hazard_id", ondelete="SET NULL"),
    ),
    Column(
        "target_area_interactable_id",
        UUID(),
        ForeignKey("world.area_interactables.area_interactable_id", ondelete="SET NULL"),
    ),
    Column(
        "target_quest_objective_id",
        UUID(),
        ForeignKey("narrative.quest_objectives.quest_objective_id", ondelete="SET NULL"),
        comment=(
            "The quest objective this event advanced or failed, when it has one — "
            "the sixth target_* column in the at-most-one-of-N pattern (revision 057)."
        ),
    ),
    Column(
        "target_component",
        Text(),
        nullable=False,
        comment=(
            'Machine-readable path to the affected field, e.g. "hit_points_current" '
            'or "hazard_status_id".'
        ),
    ),
    Column("previous_value", JSONB()),
    Column("new_value", JSONB()),
    Column(
        "effective_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="SET NULL"),
    ),
    Column("application_status", Text(), nullable=False, server_default=text("'applied'::text")),
    *_timestamps(),
    # Added by revision 076, once world.relationships existed to point at —
    # the seventh column in the at-most-one-target pattern.
    Column(
        "target_relationship_id",
        UUID(),
        ForeignKey("world.relationships.relationship_id", ondelete="SET NULL"),
        comment=(
            "The relationship this event changed, when it has one — the "
            "seventh target_* column in the at-most-one-of-N pattern "
            "(revision 057, last extended by revision 073)."
        ),
    ),
    schema="narrative",
    comment=(
        "A change caused by an event: target, affected component, old/new "
        "value, effective time, application status (docs/DOMAIN_MODEL.md "
        "§13.5). Common effects should also update the corresponding typed "
        "state table in the same transaction (conventions §14.4)."
    ),
)

Index("ix_event_effects_event_id", event_effects.c.event_id)
Index(
    "ix_event_effects_target_entity_id",
    event_effects.c.target_entity_id,
    postgresql_where=event_effects.c.target_entity_id.isnot(None),
)
Index(
    "ix_event_effects_target_area_connection_id",
    event_effects.c.target_area_connection_id,
    postgresql_where=event_effects.c.target_area_connection_id.isnot(None),
)
Index(
    "ix_event_effects_target_area_feature_id",
    event_effects.c.target_area_feature_id,
    postgresql_where=event_effects.c.target_area_feature_id.isnot(None),
)
Index(
    "ix_event_effects_target_area_hazard_id",
    event_effects.c.target_area_hazard_id,
    postgresql_where=event_effects.c.target_area_hazard_id.isnot(None),
)
Index(
    "ix_event_effects_target_area_interactable_id",
    event_effects.c.target_area_interactable_id,
    postgresql_where=event_effects.c.target_area_interactable_id.isnot(None),
)
Index(
    "ix_event_effects_effective_world_time_id",
    event_effects.c.effective_world_time_id,
    postgresql_where=event_effects.c.effective_world_time_id.isnot(None),
)
Index(
    "ix_event_effects_target_quest_objective_id",
    event_effects.c.target_quest_objective_id,
    postgresql_where=event_effects.c.target_quest_objective_id.isnot(None),
)
Index(
    "ix_event_effects_target_relationship_id",
    event_effects.c.target_relationship_id,
    postgresql_where=event_effects.c.target_relationship_id.isnot(None),
)

event_observations = Table(
    "event_observations",
    metadata,
    _uuid_pk("event_observation_id"),
    Column(
        "event_id",
        UUID(),
        ForeignKey("narrative.events.event_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "observer_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("observation_text", Text(), nullable=False),
    Column(
        "observed_at_world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="SET NULL"),
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    schema="narrative",
    comment=(
        "What an observer perceived about an event, distinct from its "
        "objective facts (docs/DOMAIN_MODEL.md §13.6). Append-only."
    ),
)

Index("ix_event_observations_event_id", event_observations.c.event_id)
Index("ix_event_observations_observer_entity_id", event_observations.c.observer_entity_id)
Index(
    "ix_event_observations_observed_at_world_time_id",
    event_observations.c.observed_at_world_time_id,
    postgresql_where=event_observations.c.observed_at_world_time_id.isnot(None),
)

# ---------------------------------------------------------------------------
# narrative — story arcs, quests, stages, objectives, dependencies,
# participants, outcomes, rewards (revision 073)
# ---------------------------------------------------------------------------

story_arcs = Table(
    "story_arcs",
    metadata,
    _uuid_pk("story_arc_id"),
    Column(
        "world_id", UUID(), ForeignKey("core.worlds.world_id", ondelete="CASCADE"), nullable=False
    ),
    Column("name", Text(), nullable=False),
    Column("description", Text()),
    Column("status", Text(), nullable=False, server_default=text("'active'::text")),
    Column("source_id", UUID(), ForeignKey("core.sources.source_id", ondelete="SET NULL")),
    *_timestamps(),
    schema="narrative",
    comment=(
        "Groups related quests, events, themes, and outcomes (docs/DOMAIN_MODEL.md "
        "§14.1). Not entity-rooted — a world-scoped grouping record with no "
        "independent canonical identity, same reasoning as world.area_connections "
        "(revision 039) and interaction.interactions (revision 061)."
    ),
)

Index("ix_story_arcs_world_id", story_arcs.c.world_id)
Index(
    "ix_story_arcs_source_id",
    story_arcs.c.source_id,
    postgresql_where=story_arcs.c.source_id.isnot(None),
)

quests = Table(
    "quests",
    metadata,
    Column(
        "quest_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "story_arc_id", UUID(), ForeignKey("narrative.story_arcs.story_arc_id", ondelete="SET NULL")
    ),
    *_timestamps(),
    schema="narrative",
    comment=(
        "A structured narrative challenge or objective set (docs/DOMAIN_MODEL.md "
        "§14.2). Entity-rooted — title, summary, canon status, and source are "
        "inherited from core.entities rather than duplicated here. A quest may be "
        "persistent world content while its active progress is scoped to a "
        "timeline/campaign/party (campaign.quest_state, below)."
    ),
)

Index(
    "ix_quests_story_arc_id",
    quests.c.story_arc_id,
    postgresql_where=quests.c.story_arc_id.isnot(None),
)

quest_stages = Table(
    "quest_stages",
    metadata,
    _uuid_pk("quest_stage_id"),
    Column(
        "quest_id",
        UUID(),
        ForeignKey("narrative.quests.quest_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", Text(), nullable=False),
    Column("description", Text()),
    Column("sequence_number", NONNEGATIVE_INTEGER, nullable=False, server_default=text("0")),
    Column(
        "stage_type",
        Text(),
        nullable=False,
        server_default=text("'sequential'::text"),
        comment=(
            "sequential, optional, conditional, or mutually_exclusive "
            "(docs/DOMAIN_MODEL.md §14.3) — fixed small vocabulary, not a lookup, "
            "same reasoning as knowledge_items.sensitivity (revision 041)."
        ),
    ),
    *_timestamps(),
    schema="narrative",
    comment=(
        "Groups objectives into a phase (docs/DOMAIN_MODEL.md §14.3). "
        "sequence_number orders stages within a quest; not unique, since "
        "mutually_exclusive stages (alternative branches) may legitimately "
        "share a position."
    ),
)

Index("ix_quest_stages_quest_id", quest_stages.c.quest_id)

objective_types = _lookup_table(
    "narrative",
    "objective_types",
    "objective_type_id",
    "The kind of completion/failure condition a quest objective defines "
    "(docs/DOMAIN_MODEL.md §14.4).",
)

quest_objectives = Table(
    "quest_objectives",
    metadata,
    _uuid_pk("quest_objective_id"),
    Column(
        "quest_stage_id",
        UUID(),
        ForeignKey("narrative.quest_stages.quest_stage_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "objective_type_id",
        UUID(),
        ForeignKey("narrative.objective_types.objective_type_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("name", Text(), nullable=False),
    Column("description", Text()),
    Column(
        "requirement_level",
        Text(),
        nullable=False,
        server_default=text("'required'::text"),
        comment="required, optional, or hidden (docs/DOMAIN_MODEL.md §14.4).",
    ),
    Column("completion_mode", Text(), nullable=False, server_default=text("'automatic'::text")),
    Column("target_entity_id", UUID(), ForeignKey("core.entities.entity_id", ondelete="SET NULL")),
    Column(
        "target_area_connection_id",
        UUID(),
        ForeignKey("world.area_connections.area_connection_id", ondelete="SET NULL"),
    ),
    Column(
        "target_area_feature_id",
        UUID(),
        ForeignKey("world.area_features.area_feature_id", ondelete="SET NULL"),
    ),
    Column(
        "target_area_hazard_id",
        UUID(),
        ForeignKey("world.area_hazards.area_hazard_id", ondelete="SET NULL"),
    ),
    Column(
        "target_area_interactable_id",
        UUID(),
        ForeignKey("world.area_interactables.area_interactable_id", ondelete="SET NULL"),
    ),
    Column(
        "quantity_required",
        Integer(),
        comment=(
            'For objectives counted in units, e.g. "activate three pylons" '
            "(docs/DOMAIN_MODEL.md §14). NULL for objectives with no quantity."
        ),
    ),
    Column(
        "completion_rule",
        JSONB(),
        comment=(
            "Structured completion-rule metadata, for example "
            '{"rule": "quantity_threshold", "threshold": 3} — distinct from '
            "completion_mode (automatic vs. GM-confirmed, i.e. who decides) and from "
            "quantity_required (a single scalar). NULL when the objective's "
            "completion condition needs no structured metadata beyond its type and "
            "target."
        ),
    ),
    Column(
        "visibility_policy",
        Text(),
        nullable=False,
        server_default=text("'visible'::text"),
        comment=(
            "Whether and when this objective is shown to players "
            "— distinct from requirement_level='hidden' (whether the objective is "
            "mandatory for quest completion, not whether players can see it). An "
            "inferred, illustrative vocabulary rather than "
            "policy values, only the concept."
        ),
    ),
    *_timestamps(),
    schema="narrative",
    comment=(
        "Defines a completion or failure condition (docs/DOMAIN_MODEL.md §14.4). "
        "target_* columns reuse the knowledge_items/event_effects at-most-one-typed- "
        "target pattern; world.locations and knowledge.knowledge_items are both "
        'entity-rooted, so target_entity_id alone covers "reach a location" and '
        '"discover knowledge" objectives.'
    ),
)

Index("ix_quest_objectives_quest_stage_id", quest_objectives.c.quest_stage_id)
Index("ix_quest_objectives_objective_type_id", quest_objectives.c.objective_type_id)
Index(
    "ix_quest_objectives_target_entity_id",
    quest_objectives.c.target_entity_id,
    postgresql_where=quest_objectives.c.target_entity_id.isnot(None),
)
Index(
    "ix_quest_objectives_target_area_connection_id",
    quest_objectives.c.target_area_connection_id,
    postgresql_where=quest_objectives.c.target_area_connection_id.isnot(None),
)
Index(
    "ix_quest_objectives_target_area_feature_id",
    quest_objectives.c.target_area_feature_id,
    postgresql_where=quest_objectives.c.target_area_feature_id.isnot(None),
)
Index(
    "ix_quest_objectives_target_area_hazard_id",
    quest_objectives.c.target_area_hazard_id,
    postgresql_where=quest_objectives.c.target_area_hazard_id.isnot(None),
)
Index(
    "ix_quest_objectives_target_area_interactable_id",
    quest_objectives.c.target_area_interactable_id,
    postgresql_where=quest_objectives.c.target_area_interactable_id.isnot(None),
)

objective_dependencies = Table(
    "objective_dependencies",
    metadata,
    _uuid_pk("objective_dependency_id"),
    Column(
        "objective_id",
        UUID(),
        ForeignKey("narrative.quest_objectives.quest_objective_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "depends_on_objective_id",
        UUID(),
        ForeignKey("narrative.quest_objectives.quest_objective_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("dependency_type", Text(), nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint(
        "objective_id",
        "depends_on_objective_id",
        "dependency_type",
        name="ux_objective_dependencies_edge",
    ),
    schema="narrative",
    comment=(
        "Prerequisite, blocking, exclusion, or branching relationships between "
        "objectives (docs/DOMAIN_MODEL.md §14.5). Append-only."
    ),
)

Index("ix_objective_dependencies_objective_id", objective_dependencies.c.objective_id)
Index(
    "ix_objective_dependencies_depends_on_objective_id",
    objective_dependencies.c.depends_on_objective_id,
)

quest_participants = Table(
    "quest_participants",
    metadata,
    _uuid_pk("quest_participant_id"),
    Column(
        "quest_id",
        UUID(),
        ForeignKey("narrative.quests.quest_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "participant_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("participant_role", Text(), nullable=False, server_default=text("'involved'::text")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint(
        "quest_id",
        "participant_entity_id",
        "participant_role",
        name="ux_quest_participants_quest_entity_role",
    ),
    schema="narrative",
    comment=(
        "Relates an entity (NPC, character) to a quest with a role. Not described "
        "in detail by docs/DOMAIN_MODEL.md §14 beyond naming the table — "
        "participant_role's vocabulary is an inferred, illustrative default, same "
        "latitude the platform already takes for narrative.event_locations."
        "event_location_role (revision 057)."
    ),
)

Index("ix_quest_participants_quest_id", quest_participants.c.quest_id)
Index("ix_quest_participants_participant_entity_id", quest_participants.c.participant_entity_id)

quest_outcomes = Table(
    "quest_outcomes",
    metadata,
    _uuid_pk("quest_outcome_id"),
    Column(
        "quest_id",
        UUID(),
        ForeignKey("narrative.quests.quest_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("code", Text(), nullable=False),
    Column("name", Text(), nullable=False),
    Column("description", Text()),
    Column("outcome_category", Text(), nullable=False, server_default=text("'success'::text")),
    *_timestamps(),
    UniqueConstraint("quest_id", "code", name="ux_quest_outcomes_quest_code"),
    schema="narrative",
    comment=(
        "Defines a meaningful resolution and its downstream effects "
        "(docs/DOMAIN_MODEL.md §14.8). code is quest-scoped (unique per quest, not "
        "globally), unlike a lookup table's code — each quest's outcomes are its "
        "own narrative vocabulary."
    ),
)

Index("ix_quest_outcomes_quest_id", quest_outcomes.c.quest_id)

quest_rewards = Table(
    "quest_rewards",
    metadata,
    _uuid_pk("quest_reward_id"),
    Column(
        "quest_outcome_id",
        UUID(),
        ForeignKey("narrative.quest_outcomes.quest_outcome_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("reward_type", Text(), nullable=False),
    Column("description", Text(), nullable=False),
    Column(
        "reward_knowledge_item_id",
        UUID(),
        ForeignKey("knowledge.knowledge_items.knowledge_item_id", ondelete="SET NULL"),
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    schema="narrative",
    comment=(
        "A reward granted by a specific quest outcome. item/currency rewards have "
        "no typed target; reward_knowledge_item_id is the supported typed reward."
    ),
)

Index("ix_quest_rewards_quest_outcome_id", quest_rewards.c.quest_outcome_id)
Index(
    "ix_quest_rewards_reward_knowledge_item_id",
    quest_rewards.c.reward_knowledge_item_id,
    postgresql_where=quest_rewards.c.reward_knowledge_item_id.isnot(None),
)
