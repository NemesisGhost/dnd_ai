"""Editor read models for encounter preparation (Phase 15 checkpoint 15.3B-2a).

`canon.edit` only. Unlike `queries.encounter.get_encounter_view` (the audience-neutral record of
a running or finished encounter) these name each participant and the place, and say whether the
encounter can still be prepared (`pending`). Only encounters of the campaign are reachable.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, text


@dataclass(frozen=True)
class ParticipantRow:
    encounter_participant_id: uuid.UUID
    participant_entity_id: uuid.UUID
    name: str
    entity_type_code: str
    side: str
    initiative: int | None
    outcome: str | None = None
    current_hit_points: int | None = None
    maximum_hit_points: int | None = None


@dataclass(frozen=True)
class TurnRow:
    turn_order: int
    actor_name: str
    target_name: str | None
    action_kind: str | None
    hit: bool | None
    damage_amount: int | None


@dataclass(frozen=True)
class RoundRow:
    round_number: int
    turns: list[TurnRow]


@dataclass(frozen=True)
class EncounterPreparationView:
    encounter_id: uuid.UUID
    session_id: uuid.UUID | None
    status: str
    summary: str | None
    location_id: uuid.UUID | None
    location_name: str | None
    world_time_id: uuid.UUID
    current_round: int = 0
    resulting_event_id: uuid.UUID | None = None
    participants: list[ParticipantRow] = field(default_factory=list)
    rounds: list[RoundRow] = field(default_factory=list)

    @property
    def can_prepare(self) -> bool:
        return self.status == "pending"


@dataclass(frozen=True)
class EncounterSummary:
    encounter_id: uuid.UUID
    status: str
    summary: str | None
    location_name: str | None
    participant_count: int


def get_encounter_preparation(
    connection: Connection, *, campaign_id: uuid.UUID, encounter_id: uuid.UUID
) -> EncounterPreparationView | None:
    row = connection.execute(
        text("""
            SELECT en.session_id, en.status, en.summary, en.location_id, en.world_time_id,
                   en.current_round, en.resulting_event_id, en.timeline_id,
                   loc.canonical_name AS location_name
            FROM narrative.encounters en
            LEFT JOIN core.entities loc ON loc.entity_id = en.location_id
            WHERE en.encounter_id = :e AND en.campaign_id = :c
        """),
        {"e": encounter_id, "c": campaign_id},
    ).one_or_none()
    if row is None:
        return None
    participants = connection.execute(
        text("""
            SELECT p.encounter_participant_id, p.participant_entity_id, p.side, p.initiative,
                   p.outcome, e.canonical_name, et.code,
                   cs.current_hit_points, cs.maximum_hit_points
            FROM narrative.encounter_participants p
            JOIN core.entities e ON e.entity_id = p.participant_entity_id
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            LEFT JOIN campaign.character_state cs
                   ON cs.character_id = p.participant_entity_id AND cs.timeline_id = :t
            WHERE p.encounter_id = :e
            ORDER BY p.initiative DESC NULLS LAST, lower(e.canonical_name),
                     p.encounter_participant_id
        """),
        {"e": encounter_id, "t": row.timeline_id},
    ).all()
    turns = connection.execute(
        text("""
            SELECT r.round_number, t.turn_order, actor.canonical_name AS actor_name,
                   target.canonical_name AS target_name, ca.action_kind, ca.hit,
                   ca.damage_amount
            FROM narrative.encounter_turns t
            JOIN narrative.encounter_rounds r ON r.encounter_round_id = t.encounter_round_id
            JOIN narrative.encounter_participants p ON p.encounter_participant_id = t.participant_id
            JOIN core.entities actor ON actor.entity_id = p.participant_entity_id
            LEFT JOIN interaction.combat_actions ca ON ca.combat_action_id = t.combat_action_id
            LEFT JOIN interaction.targets tg ON tg.target_id = ca.target_id
            LEFT JOIN core.entities target ON target.entity_id = tg.target_entity_id
            WHERE r.encounter_id = :e
            ORDER BY r.round_number, t.turn_order
        """),
        {"e": encounter_id},
    ).all()
    by_round: dict[int, list[TurnRow]] = {}
    for t in turns:
        by_round.setdefault(int(t.round_number), []).append(
            TurnRow(
                turn_order=int(t.turn_order),
                actor_name=str(t.actor_name),
                target_name=None if t.target_name is None else str(t.target_name),
                action_kind=t.action_kind,
                hit=t.hit,
                damage_amount=t.damage_amount,
            )
        )
    return EncounterPreparationView(
        encounter_id=encounter_id,
        session_id=row.session_id,
        status=str(row.status),
        summary=row.summary,
        location_id=row.location_id,
        location_name=None if row.location_name is None else str(row.location_name),
        world_time_id=row.world_time_id,
        current_round=int(row.current_round),
        resulting_event_id=row.resulting_event_id,
        rounds=[RoundRow(round_number=n, turns=rows) for n, rows in sorted(by_round.items())],
        participants=[
            ParticipantRow(
                encounter_participant_id=p.encounter_participant_id,
                participant_entity_id=p.participant_entity_id,
                name=str(p.canonical_name),
                entity_type_code=str(p.code),
                side=str(p.side),
                initiative=p.initiative,
                outcome=p.outcome,
                current_hit_points=p.current_hit_points,
                maximum_hit_points=p.maximum_hit_points,
            )
            for p in participants
        ],
    )


def list_session_encounters(
    connection: Connection, *, campaign_id: uuid.UUID, session_id: uuid.UUID
) -> list[EncounterSummary]:
    rows = connection.execute(
        text("""
            SELECT en.encounter_id, en.status, en.summary, loc.canonical_name AS location_name,
                   (SELECT count(*) FROM narrative.encounter_participants p
                    WHERE p.encounter_id = en.encounter_id) AS participant_count
            FROM narrative.encounters en
            LEFT JOIN core.entities loc ON loc.entity_id = en.location_id
            WHERE en.campaign_id = :c AND en.session_id = :s
            ORDER BY en.created_at DESC, en.encounter_id
        """),
        {"c": campaign_id, "s": session_id},
    ).all()
    return [
        EncounterSummary(
            encounter_id=r.encounter_id,
            status=str(r.status),
            summary=r.summary,
            location_name=None if r.location_name is None else str(r.location_name),
            participant_count=int(r.participant_count),
        )
        for r in rows
    ]
