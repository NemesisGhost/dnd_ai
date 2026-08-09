"""StartEncounter, ResolveCombatTurn, and EndEncounter — the commands that
let a dungeon (or Foundry) combat session update persistent character and
world state (docs/PLAN.md Phase 9 exit criterion: "Foundry combat can update
persistent character and world state").

resolve_combat_turn mirrors dnd_ai.commands.relationships.
evolve_relationship_reaction's shape: lock a structural row that always
exists (narrative.encounters) before touching the round/turn rows, then
record the causing narrative.events row (citing the encounter via
narrative.event_causes.cause_encounter_id — revision 078), update
campaign.character_state to match, and link the two through a
narrative.event_effects row — all in one transaction. It builds its own
interaction.interactions/interaction.actions pair for the combat_action to
attach to, left at the default 'initiated' status: no check_requests are
created here, so the interaction-lifecycle locking revisions 067/070-072
added never engages, and there is no exit criterion requiring this
command to also close out the interaction's own lifecycle.
"""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from ._shared import lookup_id
from .events import EventParticipant, _insert_event_row


@dataclass(frozen=True)
class StartEncounterResult:
    encounter_id: uuid.UUID


@dataclass(frozen=True)
class ResolveCombatTurnResult:
    encounter_turn_id: uuid.UUID
    combat_action_id: uuid.UUID
    event_id: uuid.UUID | None
    previous_hit_points: int | None
    new_hit_points: int | None


@dataclass(frozen=True)
class EndEncounterResult:
    event_id: uuid.UUID


def start_encounter(
    engine: Engine,
    *,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    participant_entity_ids: tuple[uuid.UUID, ...],
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    summary: str | None = None,
) -> StartEncounterResult:
    """Create an encounter and its initial participants, atomically."""
    with engine.begin() as connection:
        encounter_id = connection.execute(
            text("""
                INSERT INTO narrative.encounters
                    (timeline_id, campaign_id, session_id, location_id, world_time_id, status,
                     summary)
                VALUES (:timeline, :campaign, :session, :location, :world_time, 'active', :summary)
                RETURNING encounter_id
            """),
            {
                "timeline": timeline_id,
                "campaign": campaign_id,
                "session": session_id,
                "location": location_id,
                "world_time": world_time_id,
                "summary": summary,
            },
        ).scalar()
        assert isinstance(encounter_id, uuid.UUID)

        for participant_entity_id in participant_entity_ids:
            connection.execute(
                text("""
                    INSERT INTO narrative.encounter_participants
                        (encounter_id, participant_entity_id)
                    VALUES (:encounter, :participant)
                """),
                {"encounter": encounter_id, "participant": participant_entity_id},
            )

    return StartEncounterResult(encounter_id=encounter_id)


def _lock_encounter(connection: Connection, encounter_id: uuid.UUID) -> uuid.UUID:
    """Acquire an exclusive row lock on the encounter (a structural row that
    always exists) before touching its rounds/turns, and return its
    timeline_id."""
    timeline_id = connection.execute(
        text("SELECT timeline_id FROM narrative.encounters WHERE encounter_id = :e FOR UPDATE"),
        {"e": encounter_id},
    ).scalar()
    if timeline_id is None:
        raise ValueError(f"encounter {encounter_id} does not exist")
    assert isinstance(timeline_id, uuid.UUID)
    return timeline_id


def _get_or_create_round(
    connection: Connection, *, encounter_id: uuid.UUID, round_number: int
) -> uuid.UUID:
    round_id = connection.execute(
        text("""
            SELECT encounter_round_id FROM narrative.encounter_rounds
            WHERE encounter_id = :encounter AND round_number = :round
            FOR UPDATE
        """),
        {"encounter": encounter_id, "round": round_number},
    ).scalar()
    if round_id is not None:
        assert isinstance(round_id, uuid.UUID)
        return round_id

    round_id = connection.execute(
        text("""
            INSERT INTO narrative.encounter_rounds (encounter_id, round_number)
            VALUES (:encounter, :round)
            RETURNING encounter_round_id
        """),
        {"encounter": encounter_id, "round": round_number},
    ).scalar()
    assert isinstance(round_id, uuid.UUID)
    return round_id


def _participant_id(
    connection: Connection, *, encounter_id: uuid.UUID, participant_entity_id: uuid.UUID
) -> uuid.UUID:
    value = connection.execute(
        text("""
            SELECT encounter_participant_id FROM narrative.encounter_participants
            WHERE encounter_id = :encounter AND participant_entity_id = :entity
        """),
        {"encounter": encounter_id, "entity": participant_entity_id},
    ).scalar()
    if value is None:
        raise ValueError(
            f"entity {participant_entity_id} is not a participant in encounter {encounter_id}"
        )
    assert isinstance(value, uuid.UUID)
    return value


def _character_hit_points(
    connection: Connection, *, timeline_id: uuid.UUID, character_id: uuid.UUID
) -> int | None:
    value = connection.execute(
        text("""
            SELECT current_hit_points FROM campaign.character_state
            WHERE timeline_id = :timeline AND character_id = :character
            FOR UPDATE
        """),
        {"timeline": timeline_id, "character": character_id},
    ).scalar()
    return value


def resolve_combat_turn(
    engine: Engine,
    *,
    encounter_id: uuid.UUID,
    round_number: int,
    turn_order: int,
    actor_entity_id: uuid.UUID,
    world_time_id: uuid.UUID,
    action_kind: str = "attack",
    target_entity_id: uuid.UUID | None = None,
    item_instance_id: uuid.UUID | None = None,
    spell_id: uuid.UUID | None = None,
    hit: bool | None = None,
    damage_amount: int | None = None,
    damage_type_id: uuid.UUID | None = None,
    resulting_condition_id: uuid.UUID | None = None,
    interaction_type_code: str = "attack",
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    event_details: str | None = None,
) -> ResolveCombatTurnResult:
    """Record one participant's turn — the interaction/action/combat_action
    it resolved via, and (when it dealt damage to a character with existing
    campaign.character_state on this timeline) the resulting HP change,
    with a causal narrative.events row citing the encounter — atomically.
    """
    with engine.begin() as connection:
        timeline_id = _lock_encounter(connection, encounter_id)
        encounter_round_id = _get_or_create_round(
            connection, encounter_id=encounter_id, round_number=round_number
        )
        participant_id = _participant_id(
            connection, encounter_id=encounter_id, participant_entity_id=actor_entity_id
        )

        world_id = connection.execute(
            text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :t"),
            {"t": timeline_id},
        ).scalar()
        assert isinstance(world_id, uuid.UUID)

        interaction_type_id = lookup_id(
            connection,
            "interaction",
            "interaction_types",
            "interaction_type_id",
            interaction_type_code,
        )
        interaction_id = connection.execute(
            text("""
                INSERT INTO interaction.interactions
                    (timeline_id, campaign_id, session_id, interaction_type_id, world_time_id)
                VALUES (:timeline, :campaign, :session, :itype, :world_time)
                RETURNING interaction_id
            """),
            {
                "timeline": timeline_id,
                "campaign": campaign_id,
                "session": session_id,
                "itype": interaction_type_id,
                "world_time": world_time_id,
            },
        ).scalar()
        assert isinstance(interaction_id, uuid.UUID)

        action_id = connection.execute(
            text("""
                INSERT INTO interaction.actions (interaction_id, actor_entity_id)
                VALUES (:interaction, :actor)
                RETURNING action_id
            """),
            {"interaction": interaction_id, "actor": actor_entity_id},
        ).scalar()
        assert isinstance(action_id, uuid.UUID)

        target_id = None
        if target_entity_id is not None:
            target_id = connection.execute(
                text("""
                    INSERT INTO interaction.targets (action_id, target_entity_id)
                    VALUES (:action, :entity)
                    RETURNING target_id
                """),
                {"action": action_id, "entity": target_entity_id},
            ).scalar()
            assert isinstance(target_id, uuid.UUID)

        combat_action_id = connection.execute(
            text("""
                INSERT INTO interaction.combat_actions
                    (action_id, target_id, action_kind, item_instance_id, spell_id, hit,
                     damage_amount, damage_type_id, resulting_condition_id)
                VALUES (:action, :target, :kind, :item, :spell, :hit, :damage, :damage_type,
                        :condition)
                RETURNING combat_action_id
            """),
            {
                "action": action_id,
                "target": target_id,
                "kind": action_kind,
                "item": item_instance_id,
                "spell": spell_id,
                "hit": hit,
                "damage": damage_amount,
                "damage_type": damage_type_id,
                "condition": resulting_condition_id,
            },
        ).scalar()
        assert isinstance(combat_action_id, uuid.UUID)

        encounter_turn_id = connection.execute(
            text("""
                INSERT INTO narrative.encounter_turns
                    (encounter_round_id, participant_id, turn_order, combat_action_id)
                VALUES (:round, :participant, :order, :combat_action)
                RETURNING encounter_turn_id
            """),
            {
                "round": encounter_round_id,
                "participant": participant_id,
                "order": turn_order,
                "combat_action": combat_action_id,
            },
        ).scalar()
        assert isinstance(encounter_turn_id, uuid.UUID)

        # Not every attack roll needs a permanent world event
        # (docs/architecture/DATABASE_MODEL.md §12.3) — only promote to a
        # narrative.events row when there was actual persistent state to
        # change: real damage, against a target with an existing
        # campaign.character_state row on this timeline. A miss, a
        # non-damaging action, or damage against an entity with no tracked
        # HP (e.g. an untracked monster) leaves only the turn/combat_action
        # record behind.
        event_id: uuid.UUID | None = None
        previous_hit_points: int | None = None
        new_hit_points: int | None = None

        if damage_amount is not None and damage_amount > 0 and target_entity_id is not None:
            previous_hit_points = _character_hit_points(
                connection, timeline_id=timeline_id, character_id=target_entity_id
            )

        if previous_hit_points is not None:
            assert target_entity_id is not None
            assert damage_amount is not None
            new_hit_points = previous_hit_points - damage_amount

            event_id = _insert_event_row(
                connection,
                world_id=world_id,
                timeline_id=timeline_id,
                world_time_id=world_time_id,
                event_type_code="combat_damage_dealt",
                name="Combat damage dealt",
                details=event_details,
                campaign_id=campaign_id,
                session_id=session_id,
                participants=(
                    EventParticipant(entity_id=actor_entity_id, role_code="actor"),
                    EventParticipant(entity_id=target_entity_id, role_code="victim"),
                ),
                cause_description=None,
            )
            connection.execute(
                text("""
                    INSERT INTO narrative.event_causes (event_id, cause_encounter_id)
                    VALUES (:event, :encounter)
                """),
                {"event": event_id, "encounter": encounter_id},
            )
            connection.execute(
                text("""
                    UPDATE campaign.character_state
                    SET current_hit_points = :hp, updated_at = now()
                    WHERE timeline_id = :timeline AND character_id = :character
                """),
                {"hp": new_hit_points, "timeline": timeline_id, "character": target_entity_id},
            )
            connection.execute(
                text("""
                    INSERT INTO narrative.event_effects
                        (event_id, target_entity_id, target_component, previous_value,
                         new_value, effective_world_time_id)
                    VALUES (:event, :character, 'current_hit_points', :previous, :new,
                            :world_time)
                """),
                {
                    "event": event_id,
                    "character": target_entity_id,
                    "previous": json.dumps(previous_hit_points),
                    "new": json.dumps(new_hit_points),
                    "world_time": world_time_id,
                },
            )

    return ResolveCombatTurnResult(
        encounter_turn_id=encounter_turn_id,
        combat_action_id=combat_action_id,
        event_id=event_id,
        previous_hit_points=previous_hit_points,
        new_hit_points=new_hit_points,
    )


def end_encounter(
    engine: Engine,
    *,
    encounter_id: uuid.UUID,
    world_time_id: uuid.UUID,
    outcomes: tuple[tuple[uuid.UUID, str], ...] = (),
    summary: str | None = None,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
) -> EndEncounterResult:
    """Mark an encounter completed, record each participant's outcome
    (defeated/escaped/surrendered/captured), and link the resulting event —
    atomically."""
    with engine.begin() as connection:
        timeline_id = _lock_encounter(connection, encounter_id)

        world_id = connection.execute(
            text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :t"),
            {"t": timeline_id},
        ).scalar()
        assert isinstance(world_id, uuid.UUID)

        event_id = _insert_event_row(
            connection,
            world_id=world_id,
            timeline_id=timeline_id,
            world_time_id=world_time_id,
            event_type_code="other",
            name="Encounter ended",
            details=summary,
            campaign_id=campaign_id,
            session_id=session_id,
        )
        connection.execute(
            text("""
                INSERT INTO narrative.event_causes (event_id, cause_encounter_id)
                VALUES (:event, :encounter)
            """),
            {"event": event_id, "encounter": encounter_id},
        )

        connection.execute(
            text("""
                UPDATE narrative.encounters
                SET status = 'completed', summary = COALESCE(:summary, summary),
                    resulting_event_id = :event, updated_at = now()
                WHERE encounter_id = :encounter
            """),
            {"summary": summary, "event": event_id, "encounter": encounter_id},
        )

        for participant_entity_id, outcome in outcomes:
            connection.execute(
                text("""
                    UPDATE narrative.encounter_participants
                    SET outcome = :outcome, updated_at = now()
                    WHERE encounter_id = :encounter AND participant_entity_id = :entity
                """),
                {"outcome": outcome, "encounter": encounter_id, "entity": participant_entity_id},
            )

    return EndEncounterResult(event_id=event_id)
