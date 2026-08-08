"""Interaction tables — interaction schema.

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
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.types import Integer

from ._shared import (
    NONNEGATIVE_INTEGER,
    _lookup_table,
    _timestamps,
    _uuid_pk,
    metadata,
)

# ---------------------------------------------------------------------------
# interaction — interactions, actions, targets, checks, consequences,
# external messages (revision 061)
# ---------------------------------------------------------------------------

interaction_types = _lookup_table(
    "interaction",
    "interaction_types",
    "interaction_type_id",
    "The kind of structured attempt to affect or examine the world "
    "(docs/DOMAIN_MODEL.md §16.1). Illustrative starter set, extensible.",
)

interactions = Table(
    "interactions",
    metadata,
    _uuid_pk("interaction_id"),
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
        "interaction_type_id",
        UUID(),
        ForeignKey("interaction.interaction_types.interaction_type_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("status", Text(), nullable=False, server_default=text("'initiated'::text")),
    Column("summary", Text()),
    Column(
        "resulting_event_id",
        UUID(),
        ForeignKey("narrative.events.event_id", ondelete="SET NULL"),
        comment=(
            "The event this interaction produced, when its outcome was significant "
            "enough to promote (conventions §14.5) — most interactions have none."
        ),
    ),
    *_timestamps(),
    schema="interaction",
    comment=(
        "A structured attempt by one or more actors to affect or examine the "
        "world (docs/DOMAIN_MODEL.md §16.1). Not entity-rooted — a high-volume "
        "log record, distinct from narrative.events (this revision's docstring). "
        "May reference a campaign and session when produced during play."
    ),
)

Index("ix_interactions_timeline_id", interactions.c.timeline_id)
Index(
    "ix_interactions_campaign_id",
    interactions.c.campaign_id,
    postgresql_where=interactions.c.campaign_id.isnot(None),
)
Index(
    "ix_interactions_session_id",
    interactions.c.session_id,
    postgresql_where=interactions.c.session_id.isnot(None),
)
Index("ix_interactions_interaction_type_id", interactions.c.interaction_type_id)
Index("ix_interactions_world_time_id", interactions.c.world_time_id)
Index(
    "ix_interactions_resulting_event_id",
    interactions.c.resulting_event_id,
    postgresql_where=interactions.c.resulting_event_id.isnot(None),
)

actions = Table(
    "actions",
    metadata,
    _uuid_pk("action_id"),
    Column(
        "interaction_id",
        UUID(),
        ForeignKey("interaction.interactions.interaction_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "actor_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("sequence_number", NONNEGATIVE_INTEGER, nullable=False, server_default=text("0")),
    Column("description", Text()),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("interaction_id", "sequence_number", name="ux_actions_interaction_sequence"),
    schema="interaction",
    comment=(
        "An individual operation within an interaction (docs/DOMAIN_MODEL.md "
        "§16.2). A complex interaction may contain several, ordered by "
        "sequence_number, each with its own actor. Append-only."
    ),
)

Index("ix_actions_interaction_id", actions.c.interaction_id)
Index("ix_actions_actor_entity_id", actions.c.actor_entity_id)

targets = Table(
    "targets",
    metadata,
    _uuid_pk("target_id"),
    Column(
        "action_id",
        UUID(),
        ForeignKey("interaction.actions.action_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "target_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="SET NULL"),
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
    Column("target_component", Text()),
    Column(
        "target_description",
        Text(),
        comment=(
            "Free-text description for abstract objectives with no typed "
            'target_* reference, e.g. "the far wall" or "anyone listening".'
        ),
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    schema="interaction",
    comment=(
        "Identifies entities, components, areas, or abstract objectives "
        "affected by an action (docs/DOMAIN_MODEL.md §16.3). A typed target "
        "(at most one) or a free-text target_description (for abstract "
        "objectives with no typed reference) must be present. Append-only."
    ),
)

Index("ix_targets_action_id", targets.c.action_id)
Index(
    "ix_targets_target_entity_id",
    targets.c.target_entity_id,
    postgresql_where=targets.c.target_entity_id.isnot(None),
)
Index(
    "ix_targets_target_area_connection_id",
    targets.c.target_area_connection_id,
    postgresql_where=targets.c.target_area_connection_id.isnot(None),
)
Index(
    "ix_targets_target_area_feature_id",
    targets.c.target_area_feature_id,
    postgresql_where=targets.c.target_area_feature_id.isnot(None),
)
Index(
    "ix_targets_target_area_hazard_id",
    targets.c.target_area_hazard_id,
    postgresql_where=targets.c.target_area_hazard_id.isnot(None),
)
Index(
    "ix_targets_target_area_interactable_id",
    targets.c.target_area_interactable_id,
    postgresql_where=targets.c.target_area_interactable_id.isnot(None),
)

check_requests = Table(
    "check_requests",
    metadata,
    _uuid_pk("check_request_id"),
    Column(
        "action_id",
        UUID(),
        ForeignKey("interaction.actions.action_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "actor_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("check_kind", Text(), nullable=False),
    Column(
        "ability_id",
        UUID(),
        ForeignKey("rules.abilities.ability_id", ondelete="RESTRICT"),
        comment=(
            "Set for ability_check/saving_throw. NULL for skill_check, where the "
            "governing ability is reached through skill_id -> rules.skills.ability_id "
            "instead of being duplicated here."
        ),
    ),
    Column(
        "skill_id",
        UUID(),
        ForeignKey("rules.skills.skill_id", ondelete="RESTRICT"),
        comment="Set only for skill_check — see ck_check_requests_kind_reference.",
    ),
    Column("difficulty", NONNEGATIVE_INTEGER, nullable=False),
    Column("advantage_state", Text(), nullable=False, server_default=text("'normal'::text")),
    Column("modifiers", JSONB()),
    Column("stakes", Text()),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    # Added by revision 064, closing a modeling gap: nothing previously said
    # which of an action's (possibly several) targets a given check resolves.
    Column(
        "target_id",
        UUID(),
        ForeignKey("interaction.targets.target_id", ondelete="SET NULL"),
        comment=(
            "The specific target (of the same action) this check resolves, when the "
            "check is about a specific target rather than the action in the "
            "abstract. NULL when there is no single relevant target. Must belong to "
            "the same action_id as this check request — enforced by "
            "interaction.enforce_check_request_target_action()."
        ),
    ),
    schema="interaction",
    comment=(
        "A required rules resolution for an action: actor, ability or skill, "
        "difficulty, advantage/disadvantage, modifiers, stakes "
        "(docs/DOMAIN_MODEL.md §16.4). Append-only."
    ),
)

Index("ix_check_requests_action_id", check_requests.c.action_id)
Index("ix_check_requests_actor_entity_id", check_requests.c.actor_entity_id)
Index(
    "ix_check_requests_ability_id",
    check_requests.c.ability_id,
    postgresql_where=check_requests.c.ability_id.isnot(None),
)
Index(
    "ix_check_requests_skill_id",
    check_requests.c.skill_id,
    postgresql_where=check_requests.c.skill_id.isnot(None),
)
Index(
    "ix_check_requests_target_id",
    check_requests.c.target_id,
    postgresql_where=check_requests.c.target_id.isnot(None),
)

check_results = Table(
    "check_results",
    metadata,
    _uuid_pk("check_result_id"),
    Column(
        "check_request_id",
        UUID(),
        ForeignKey("interaction.check_requests.check_request_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("roll", NONNEGATIVE_INTEGER),
    Column("total_modifier", Integer()),
    Column("total", Integer()),
    Column("degree_of_success", Text(), nullable=False),
    Column(
        "is_visible_to_players",
        Boolean(),
        nullable=False,
        server_default=text("true"),
        comment=(
            "False for a roll the GM makes secretly (e.g. a passive check the "
            "party is not meant to know happened)."
        ),
    ),
    Column("external_system_source", Text()),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("check_request_id", name="ux_check_results_one_per_request"),
    schema="interaction",
    comment=(
        "The resolved roll, modifiers, total, degree of success, visibility, "
        "and external system source for a check request "
        "(docs/DOMAIN_MODEL.md §16.5). At most one per check_request_id — a "
        "re-roll is a new check_requests row, not a mutation here. Append-only."
    ),
)

Index("ix_check_results_check_request_id", check_results.c.check_request_id)

consequences = Table(
    "consequences",
    metadata,
    _uuid_pk("consequence_id"),
    Column(
        "interaction_id",
        UUID(),
        ForeignKey("interaction.interactions.interaction_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("consequence_type", Text(), nullable=False),
    Column("status", Text(), nullable=False, server_default=text("'proposed'::text")),
    Column(
        "resulting_event_id",
        UUID(),
        ForeignKey("narrative.events.event_id", ondelete="SET NULL"),
    ),
    Column(
        "resulting_party_discovery_id",
        UUID(),
        ForeignKey("knowledge.party_discoveries.party_discovery_id", ondelete="SET NULL"),
    ),
    Column("description", Text()),
    *_timestamps(),
    # Added by revision 073, once campaign.objective_state existed to point
    # at — closes this table's own documented quest_change placeholder.
    Column(
        "resulting_quest_objective_state_id",
        UUID(),
        ForeignKey("campaign.objective_state.objective_state_id", ondelete="SET NULL"),
        comment=(
            "The objective-state row a quest_change consequence produced, when it "
            "has one. Closes revision 061's own documented placeholder "
            '("quest_change ... consequence types have no FK target at all yet ... '
            'Phase 7/8 domains do not exist") for its quest half; '
            "relationship_change remains Phase 8's job."
        ),
    ),
    # Added by revision 076, once campaign.relationship_state existed to
    # point at — closes this table's own documented relationship_change
    # placeholder.
    Column(
        "resulting_relationship_state_id",
        UUID(),
        ForeignKey("campaign.relationship_state.relationship_state_id", ondelete="SET NULL"),
        comment=(
            "The relationship-state row a relationship_change consequence "
            "produced, when it has one. Closes revision 061's own documented "
            'placeholder ("relationship_change ... consequence types have no '
            'FK target at all yet ... Phase 7/8 domains do not exist") for '
            "its relationship half."
        ),
    ),
    schema="interaction",
    comment=(
        "A proposed or resolved outcome of an interaction — observations, "
        "events, state changes, discoveries, quest changes, or relationship "
        "changes (docs/DOMAIN_MODEL.md §16.6). Interaction-level, not "
        "action-level. quest_change gained a typed FK target in revision 073 "
        "(resulting_quest_objective_state_id); relationship_change gained one "
        "in revision 076 (resulting_relationship_state_id, above)."
    ),
)

Index("ix_consequences_interaction_id", consequences.c.interaction_id)
Index(
    "ix_consequences_resulting_event_id",
    consequences.c.resulting_event_id,
    postgresql_where=consequences.c.resulting_event_id.isnot(None),
)
Index(
    "ix_consequences_resulting_party_discovery_id",
    consequences.c.resulting_party_discovery_id,
    postgresql_where=consequences.c.resulting_party_discovery_id.isnot(None),
)
Index(
    "ix_consequences_resulting_quest_objective_state_id",
    consequences.c.resulting_quest_objective_state_id,
    postgresql_where=consequences.c.resulting_quest_objective_state_id.isnot(None),
)
Index(
    "ix_consequences_resulting_relationship_state_id",
    consequences.c.resulting_relationship_state_id,
    postgresql_where=consequences.c.resulting_relationship_state_id.isnot(None),
)

external_messages = Table(
    "external_messages",
    metadata,
    _uuid_pk("external_message_id"),
    Column(
        "interaction_id",
        UUID(),
        ForeignKey("interaction.interactions.interaction_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("source_system", Text(), nullable=False),
    Column("external_id", Text(), nullable=False),
    Column("raw_payload", JSONB()),
    Column("received_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint(
        "source_system", "external_id", name="ux_external_messages_source_external_id"
    ),
    schema="interaction",
    comment=(
        "The Discord/Foundry message or command that originated an "
        "interaction, so external actions create or reference interaction "
        "records rather than writing directly to arbitrary tables "
        "(docs/architecture/DATABASE_MODEL.md §16, conventions §16.2). "
        "Unique per (source_system, external_id) so re-delivery cannot "
        "double-ingest the same external message."
    ),
)

Index("ix_external_messages_interaction_id", external_messages.c.interaction_id)
