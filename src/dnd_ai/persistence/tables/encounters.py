"""Encounter domain tables — narrative and interaction schemas (revision 078).

Part of the src/dnd_ai/persistence/tables package. See
src/dnd_ai/persistence/tables/__init__.py for the metadata-authority note
this module inherits: this is compared against the live database by
`alembic check`, so declared tables/columns/comments must match migrations
exactly.

CHECK constraints and triggers are not declared here — see that same
__init__.py note for why (alembic does not compare them; tests cover them).
"""

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

from ._shared import NONNEGATIVE_INTEGER, _timestamps, _uuid_pk, metadata

# ---------------------------------------------------------------------------
# narrative — encounters, encounter_participants, encounter_rounds
# ---------------------------------------------------------------------------

encounters = Table(
    "encounters",
    metadata,
    _uuid_pk("encounter_id"),
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
        "location_id",
        UUID(),
        ForeignKey("world.locations.location_id", ondelete="SET NULL"),
    ),
    Column(
        "world_time_id",
        UUID(),
        ForeignKey("core.world_times.world_time_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("status", Text(), nullable=False, server_default=text("'pending'::text")),
    Column("current_round", NONNEGATIVE_INTEGER, nullable=False, server_default=text("0")),
    Column("summary", Text()),
    Column(
        "resulting_event_id",
        UUID(),
        ForeignKey("narrative.events.event_id", ondelete="SET NULL"),
        comment=(
            "The event this encounter produced, when its outcome was "
            "significant enough to promote — mirrors "
            "interaction.interactions.resulting_event_id. Individual mid-"
            "combat events (a character killed) cite the encounter directly "
            "via narrative.event_causes.cause_encounter_id instead."
        ),
    ),
    *_timestamps(),
    schema="narrative",
    comment=(
        "A combat or tactical encounter (docs/DOMAIN_MODEL.md §17.1) — not "
        "entity-rooted, a structural session record like "
        "interaction.interactions (revision 061), distinct from "
        "narrative.events. FoundryVTT may remain the detailed tactical "
        "authority during live combat; this table captures synchronized "
        "state and meaningful outcomes (docs/architecture/DATABASE_MODEL.md "
        "§13), not every tactical decision."
    ),
)

Index("ix_encounters_timeline_id", encounters.c.timeline_id)
Index(
    "ix_encounters_campaign_id",
    encounters.c.campaign_id,
    postgresql_where=encounters.c.campaign_id.isnot(None),
)
Index(
    "ix_encounters_session_id",
    encounters.c.session_id,
    postgresql_where=encounters.c.session_id.isnot(None),
)
Index(
    "ix_encounters_location_id",
    encounters.c.location_id,
    postgresql_where=encounters.c.location_id.isnot(None),
)
Index("ix_encounters_world_time_id", encounters.c.world_time_id)
Index(
    "ix_encounters_resulting_event_id",
    encounters.c.resulting_event_id,
    postgresql_where=encounters.c.resulting_event_id.isnot(None),
)

encounter_participants = Table(
    "encounter_participants",
    metadata,
    _uuid_pk("encounter_participant_id"),
    Column(
        "encounter_id",
        UUID(),
        ForeignKey("narrative.encounters.encounter_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "participant_entity_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("side", Text(), nullable=False, server_default=text("'party'::text")),
    Column("initiative", Integer()),
    Column("outcome", Text()),
    *_timestamps(),
    UniqueConstraint(
        "encounter_id", "participant_entity_id", name="ux_encounter_participants_encounter_entity"
    ),
    schema="narrative",
    comment=(
        "An entity taking part in an encounter (docs/DOMAIN_MODEL.md §17.2) "
        "— side, initiative, and outcome (defeated/escaped/surrendered/"
        "captured) once resolved. outcome NULL means still in progress or "
        "the encounter ended without a tracked individual outcome for this "
        "participant."
    ),
)

Index("ix_encounter_participants_encounter_id", encounter_participants.c.encounter_id)
Index(
    "ix_encounter_participants_participant_entity_id",
    encounter_participants.c.participant_entity_id,
)

encounter_rounds = Table(
    "encounter_rounds",
    metadata,
    _uuid_pk("encounter_round_id"),
    Column(
        "encounter_id",
        UUID(),
        ForeignKey("narrative.encounters.encounter_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("round_number", NONNEGATIVE_INTEGER, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("encounter_id", "round_number", name="ux_encounter_rounds_encounter_round"),
    schema="narrative",
    comment=(
        "One round of an encounter (docs/DOMAIN_MODEL.md §17). Carries no "
        "world_time_id of its own — a tactical sub-step of the encounter's "
        "single narrative moment (narrative.encounters.world_time_id), the "
        "same way interaction.actions carry no world_time_id independent of "
        "their parent interaction. Append-only."
    ),
)

Index("ix_encounter_rounds_encounter_id", encounter_rounds.c.encounter_id)

# ---------------------------------------------------------------------------
# interaction — combat_actions (child of interaction.actions)
# ---------------------------------------------------------------------------

combat_actions = Table(
    "combat_actions",
    metadata,
    _uuid_pk("combat_action_id"),
    Column(
        "action_id",
        UUID(),
        ForeignKey("interaction.actions.action_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "target_id",
        UUID(),
        ForeignKey("interaction.targets.target_id", ondelete="SET NULL"),
    ),
    Column("action_kind", Text(), nullable=False),
    Column(
        "item_instance_id",
        UUID(),
        ForeignKey("world.item_instances.item_instance_id", ondelete="SET NULL"),
    ),
    Column(
        "spell_id",
        UUID(),
        ForeignKey("rules.spells.spell_id", ondelete="SET NULL"),
    ),
    Column("hit", Boolean()),
    Column("damage_amount", NONNEGATIVE_INTEGER),
    Column(
        "damage_type_id",
        UUID(),
        ForeignKey("rules.damage_types.damage_type_id", ondelete="RESTRICT"),
    ),
    Column(
        "resulting_condition_id",
        UUID(),
        ForeignKey("rules.conditions.condition_id", ondelete="RESTRICT"),
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    schema="interaction",
    comment=(
        "Combat-specific detail for an action (docs/DOMAIN_MODEL.md §17), a "
        "sibling of interaction.check_requests under interaction.actions — "
        "an attack roll is already representable as check_kind = "
        "'ability_check' on check_requests/check_results (revision 061); "
        "this table adds what those cannot: action kind, item/spell used, "
        "hit/miss, and damage/condition outcome. Append-only."
    ),
)

Index("ix_combat_actions_action_id", combat_actions.c.action_id)
Index(
    "ix_combat_actions_target_id",
    combat_actions.c.target_id,
    postgresql_where=combat_actions.c.target_id.isnot(None),
)
Index(
    "ix_combat_actions_item_instance_id",
    combat_actions.c.item_instance_id,
    postgresql_where=combat_actions.c.item_instance_id.isnot(None),
)
Index(
    "ix_combat_actions_spell_id",
    combat_actions.c.spell_id,
    postgresql_where=combat_actions.c.spell_id.isnot(None),
)
Index(
    "ix_combat_actions_damage_type_id",
    combat_actions.c.damage_type_id,
    postgresql_where=combat_actions.c.damage_type_id.isnot(None),
)
Index(
    "ix_combat_actions_resulting_condition_id",
    combat_actions.c.resulting_condition_id,
    postgresql_where=combat_actions.c.resulting_condition_id.isnot(None),
)

# ---------------------------------------------------------------------------
# narrative — encounter_turns
# ---------------------------------------------------------------------------

encounter_turns = Table(
    "encounter_turns",
    metadata,
    _uuid_pk("encounter_turn_id"),
    Column(
        "encounter_round_id",
        UUID(),
        ForeignKey("narrative.encounter_rounds.encounter_round_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "participant_id",
        UUID(),
        ForeignKey("narrative.encounter_participants.encounter_participant_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("turn_order", NONNEGATIVE_INTEGER, nullable=False),
    Column(
        "combat_action_id",
        UUID(),
        ForeignKey("interaction.combat_actions.combat_action_id", ondelete="SET NULL"),
    ),
    Column("notes", Text()),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint(
        "encounter_round_id", "participant_id", name="ux_encounter_turns_round_participant"
    ),
    schema="narrative",
    comment=(
        "One participant's turn within an encounter round "
        "(docs/architecture/DATABASE_MODEL.md §13) — initiative order used, "
        "and the combat_action (if any) that resolved it. Marks whose "
        "initiative slot is active, not a full log of every action taken — "
        "see this revision's docstring on why a character with multiple "
        "attacks does not get multiple turn rows. Append-only."
    ),
)

Index("ix_encounter_turns_encounter_round_id", encounter_turns.c.encounter_round_id)
Index("ix_encounter_turns_participant_id", encounter_turns.c.participant_id)
Index(
    "ix_encounter_turns_combat_action_id",
    encounter_turns.c.combat_action_id,
    postgresql_where=encounter_turns.c.combat_action_id.isnot(None),
)
