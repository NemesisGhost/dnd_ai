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


@dataclass(frozen=True)
class EncounterPreparationView:
    encounter_id: uuid.UUID
    session_id: uuid.UUID | None
    status: str
    summary: str | None
    location_id: uuid.UUID | None
    location_name: str | None
    world_time_id: uuid.UUID
    participants: list[ParticipantRow] = field(default_factory=list)

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
                   e.canonical_name, et.code
            FROM narrative.encounter_participants p
            JOIN core.entities e ON e.entity_id = p.participant_entity_id
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE p.encounter_id = :e
            ORDER BY p.initiative DESC NULLS LAST, lower(e.canonical_name),
                     p.encounter_participant_id
        """),
        {"e": encounter_id},
    ).all()
    return EncounterPreparationView(
        encounter_id=encounter_id,
        session_id=row.session_id,
        status=str(row.status),
        summary=row.summary,
        location_id=row.location_id,
        location_name=None if row.location_name is None else str(row.location_name),
        world_time_id=row.world_time_id,
        participants=[
            ParticipantRow(
                encounter_participant_id=p.encounter_participant_id,
                participant_entity_id=p.participant_entity_id,
                name=str(p.canonical_name),
                entity_type_code=str(p.code),
                side=str(p.side),
                initiative=p.initiative,
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
