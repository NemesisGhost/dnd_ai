"""Effective encounter query (docs/PLAN.md Phase 10 deliverable "query
services for the effective dungeon, character, quest, relationship,
inventory, encounter, and knowledge state required by the vertical
slice").

`narrative.encounters`/`.encounter_participants`/`.encounter_rounds`/
`.encounter_turns` and `interaction.combat_actions` together are already
the current, timeline-scoped record of a combat encounter — unlike every
other domain this package queries, there is no separate "definition versus
state" split here (docs/architecture/DATABASE_MODEL.md §13: "the database
captures synchronized state and meaningful outcomes rather than
duplicating every tactical decision"), so this module reassembles one
encounter's full history directly rather than layering a definition query
over a state query.

Audience filtering: nothing in this domain distinguishes GM-only from
player-visible combat detail — a round, a turn, and its combat action are
each already a *resolved* outcome (a roll already made, damage already
applied), the same "observations and consequences" every participant in
an interaction already witnesses (§16). Unlike `dnd_ai.queries.dungeon`'s
undiscovered secrets or `dnd_ai.queries.quest`'s `gm_only` objectives, no
caller-supplied party/character perspective or GM bypass is needed here —
any caller authorized for the campaign at all sees the full encounter.

Cross-campaign ownership: `narrative.encounters.campaign_id` is a direct
column (unlike the world-scoped domains `dnd_ai.queries.dungeon`/
`.character`/`.quest`/`.relationship` query, which have no `campaign_id`
column at all) — this module reuses `dnd_ai.commands.encounters.
EncounterNotFoundError` directly rather than defining a duplicate, since
both raise the identical fixed, non-disclosing 404 for the identical
"doesn't exist or belongs to a different campaign" case.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.commands.encounters import EncounterNotFoundError

__all__ = ["EncounterNotFoundError", "get_encounter_view"]


@dataclass(frozen=True)
class EncounterParticipantView:
    encounter_participant_id: uuid.UUID
    participant_entity_id: uuid.UUID
    side: str
    initiative: int | None
    outcome: str | None


@dataclass(frozen=True)
class CombatActionView:
    action_kind: str
    item_instance_id: uuid.UUID | None
    spell_id: uuid.UUID | None
    hit: bool | None
    damage_amount: int | None
    damage_type_code: str | None
    resulting_condition_code: str | None


@dataclass(frozen=True)
class EncounterTurnView:
    encounter_turn_id: uuid.UUID
    participant_id: uuid.UUID
    turn_order: int
    notes: str | None
    combat_action: CombatActionView | None


@dataclass(frozen=True)
class EncounterRoundView:
    encounter_round_id: uuid.UUID
    round_number: int
    turns: tuple[EncounterTurnView, ...]


@dataclass(frozen=True)
class EncounterView:
    encounter_id: uuid.UUID
    status: str
    current_round: int
    summary: str | None
    location_id: uuid.UUID | None
    world_time_id: uuid.UUID
    resulting_event_id: uuid.UUID | None
    participants: tuple[EncounterParticipantView, ...]
    rounds: tuple[EncounterRoundView, ...]


def get_encounter_view(
    connection: Connection, *, encounter_id: uuid.UUID, campaign_id: uuid.UUID
) -> EncounterView:
    """The full current record of one encounter: its participants and
    every round/turn/combat action so far. Raises `EncounterNotFoundError`
    for a nonexistent encounter or one belonging to a different campaign
    than `campaign_id` (always the URL's own already-authorized campaign)
    — identically, so a caller can never distinguish the two."""
    row = (
        connection.execute(
            text("""
                SELECT encounter_id, status, current_round, summary, location_id, world_time_id,
                       resulting_event_id
                FROM narrative.encounters
                WHERE encounter_id = :encounter AND campaign_id = :campaign
            """),
            {"encounter": encounter_id, "campaign": campaign_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise EncounterNotFoundError(
            f"encounter {encounter_id} does not exist in campaign {campaign_id}"
        )

    participant_rows = connection.execute(
        text("""
            SELECT encounter_participant_id, participant_entity_id, side, initiative, outcome
            FROM narrative.encounter_participants
            WHERE encounter_id = :encounter
            ORDER BY encounter_participant_id
        """),
        {"encounter": encounter_id},
    ).mappings()
    participants = tuple(
        EncounterParticipantView(
            encounter_participant_id=p["encounter_participant_id"],
            participant_entity_id=p["participant_entity_id"],
            side=p["side"],
            initiative=p["initiative"],
            outcome=p["outcome"],
        )
        for p in participant_rows
    )

    turn_rows = connection.execute(
        text("""
            SELECT t.encounter_round_id, t.encounter_turn_id, t.participant_id, t.turn_order,
                   t.notes,
                   ca.action_kind, ca.item_instance_id, ca.spell_id, ca.hit, ca.damage_amount,
                   dt.code AS damage_type_code, rc.code AS resulting_condition_code
            FROM narrative.encounter_turns t
            JOIN narrative.encounter_rounds r ON r.encounter_round_id = t.encounter_round_id
            LEFT JOIN interaction.combat_actions ca ON ca.combat_action_id = t.combat_action_id
            LEFT JOIN rules.damage_types dt ON dt.damage_type_id = ca.damage_type_id
            LEFT JOIN rules.conditions rc ON rc.condition_id = ca.resulting_condition_id
            WHERE r.encounter_id = :encounter
            ORDER BY t.turn_order
        """),
        {"encounter": encounter_id},
    ).mappings()
    turns_by_round: dict[uuid.UUID, list[EncounterTurnView]] = {}
    for t in turn_rows:
        combat_action = (
            None
            if t["action_kind"] is None
            else CombatActionView(
                action_kind=t["action_kind"],
                item_instance_id=t["item_instance_id"],
                spell_id=t["spell_id"],
                hit=t["hit"],
                damage_amount=t["damage_amount"],
                damage_type_code=t["damage_type_code"],
                resulting_condition_code=t["resulting_condition_code"],
            )
        )
        turns_by_round.setdefault(t["encounter_round_id"], []).append(
            EncounterTurnView(
                encounter_turn_id=t["encounter_turn_id"],
                participant_id=t["participant_id"],
                turn_order=t["turn_order"],
                notes=t["notes"],
                combat_action=combat_action,
            )
        )

    round_rows = connection.execute(
        text("""
            SELECT encounter_round_id, round_number
            FROM narrative.encounter_rounds
            WHERE encounter_id = :encounter
            ORDER BY round_number
        """),
        {"encounter": encounter_id},
    ).mappings()
    rounds = tuple(
        EncounterRoundView(
            encounter_round_id=r["encounter_round_id"],
            round_number=r["round_number"],
            turns=tuple(turns_by_round.get(r["encounter_round_id"], [])),
        )
        for r in round_rows
    )

    return EncounterView(
        encounter_id=row["encounter_id"],
        status=row["status"],
        current_round=row["current_round"],
        summary=row["summary"],
        location_id=row["location_id"],
        world_time_id=row["world_time_id"],
        resulting_event_id=row["resulting_event_id"],
        participants=participants,
        rounds=rounds,
    )
