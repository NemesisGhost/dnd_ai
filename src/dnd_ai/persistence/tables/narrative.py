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
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

from ._shared import (
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
    "extensible starter set (docs/PLAN.md §13.3), not an exhaustive "
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
