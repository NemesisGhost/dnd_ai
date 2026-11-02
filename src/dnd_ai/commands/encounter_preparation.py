"""Encounter preparation commands (Phase 15 checkpoint 15.3B-2a, decision D-23).

`create_encounter` prepares a `pending` encounter in a session; `update_encounter` changes its
location and summary; `add_encounter_participant`, `update_encounter_participant` and
`remove_encounter_participant` manage who takes part and on which side. Every command needs the
encounter to be pending (the status is the optimistic guard: once it starts, preparation is
over). No event is recorded: preparing nothing yet happened in the world. Starting, running and
ending an encounter are 15.3B-2b.

Lock order: operation scope (world, membership, account, campaign `FOR SHARE`), the session
`FOR SHARE` (it cannot be archived under the command), the encounter `FOR UPDATE` (which also
serializes two edits of one encounter), then the named characters and place `FOR SHARE` in id
order.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from dnd_ai.domain.content_authoring import diff_fields, initial_fields
from dnd_ai.domain.encounter_preparation import (
    MAX_PARTICIPANTS,
    PARTICIPANT_TYPE_CODES,
    EncounterFullError,
    EncounterNotPendingError,
    EncounterParticipantExistsError,
    EncounterParticipantInvalidError,
    EncounterParticipantNotFoundError,
    EncounterSessionNotUsableError,
    normalize_initiative,
    normalize_side,
    normalize_summary,
)

from ._operations import OperationScope, lock_operation_scope
from ._shared import require_state_targetable, validate_session_campaign
from .encounters import EncounterNotFoundError
from .quest_runtime import time_or_clock


@dataclass(frozen=True)
class PreparationResult:
    encounter_id: uuid.UUID
    world_id: uuid.UUID
    changed: bool
    table: str = "encounters"
    record_id: uuid.UUID | None = None
    action: str = "updated"
    changed_fields: dict[str, object] = field(default_factory=dict)


def _lock_session(connection: Connection, session_id: uuid.UUID) -> None:
    """The session must be active; held `FOR SHARE` so it cannot be archived meanwhile."""
    row = connection.execute(
        text("""
            SELECT ls.code FROM campaign.sessions s
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = s.lifecycle_status_id
            WHERE s.session_id = :s FOR SHARE OF s
        """),
        {"s": session_id},
    ).one_or_none()
    if row is None or row.code != "active":
        raise EncounterSessionNotUsableError(f"session {session_id} is not usable")


def _lock_pending(
    connection: Connection, scope: OperationScope, encounter_id: uuid.UUID
) -> tuple[uuid.UUID | None, str | None]:
    """Lock the campaign's pending encounter; return `(location_id, summary)`."""
    row = connection.execute(
        text("""
            SELECT campaign_id, location_id, status, summary
            FROM narrative.encounters WHERE encounter_id = :e FOR UPDATE
        """),
        {"e": encounter_id},
    ).one_or_none()
    if row is None or row.campaign_id != scope.campaign_id:
        raise EncounterNotFoundError(f"encounter {encounter_id} is not in this campaign")
    if row.status != "pending":
        raise EncounterNotPendingError(f"encounter {encounter_id} is {row.status}")
    return row.location_id, row.summary


def _require_location(
    connection: Connection, scope: OperationScope, location_id: uuid.UUID | None
) -> None:
    if location_id is None:
        return
    found = connection.execute(
        text("""
            SELECT 1 FROM world.locations l JOIN core.entities e ON e.entity_id = l.location_id
            WHERE l.location_id = :l AND e.world_id = :w
        """),
        {"l": location_id, "w": scope.world_id},
    ).scalar()
    if found is None:
        raise EncounterParticipantInvalidError(f"location {location_id} is not usable")
    require_state_targetable(connection, location_id)


def _require_character(
    connection: Connection, scope: OperationScope, character_id: uuid.UUID
) -> None:
    row = connection.execute(
        text("""
            SELECT e.world_id, et.code FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE e.entity_id = :c
        """),
        {"c": character_id},
    ).one_or_none()
    if row is None or row.world_id != scope.world_id or row.code not in PARTICIPANT_TYPE_CODES:
        raise EncounterParticipantInvalidError(f"{character_id} is not a character of this world")
    require_state_targetable(connection, character_id)


def _prepare(
    connection: Connection,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    encounter_id: uuid.UUID,
) -> tuple[OperationScope, uuid.UUID | None, str | None]:
    """Scope, the session, then the pending encounter; returns its location and summary."""
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    session_id = connection.execute(
        text("SELECT session_id FROM narrative.encounters WHERE encounter_id = :e"),
        {"e": encounter_id},
    ).scalar()
    if session_id is not None:
        _lock_session(connection, session_id)
    location, summary = _lock_pending(connection, scope, encounter_id)
    return scope, location, summary


def create_encounter(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    session_id: uuid.UUID,
    location_id: uuid.UUID | None = None,
    summary: str | None = None,
    world_time_id: uuid.UUID | None = None,
) -> PreparationResult:
    clean_summary = normalize_summary(summary)
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    validate_session_campaign(connection, campaign_id=campaign_id, session_id=session_id)
    _lock_session(connection, session_id)
    _require_location(connection, scope, location_id)
    time_id = time_or_clock(connection, scope, world_time_id)
    encounter_id = connection.execute(
        text("""
            INSERT INTO narrative.encounters
                (timeline_id, campaign_id, session_id, location_id, world_time_id, status,
                 summary)
            VALUES (:t, :c, :s, :l, :w, 'pending', :summary)
            RETURNING encounter_id
        """),
        {
            "t": scope.timeline_id,
            "c": campaign_id,
            "s": session_id,
            "l": location_id,
            "w": time_id,
            "summary": clean_summary,
        },
    ).scalar()
    assert isinstance(encounter_id, uuid.UUID)
    return PreparationResult(
        encounter_id=encounter_id,
        world_id=scope.world_id,
        changed=True,
        record_id=encounter_id,
        action="created",
        changed_fields=dict(
            initial_fields(
                {
                    "session_id": str(session_id),
                    "location_id": None if location_id is None else str(location_id),
                    "summary": clean_summary,
                }
            )
        ),
    )


def update_encounter(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    encounter_id: uuid.UUID,
    location_id: uuid.UUID | None,
    summary: str | None,
) -> PreparationResult:
    clean_summary = normalize_summary(summary)
    scope, current_location, current_summary = _prepare(
        connection, campaign_id, actor_user_id, encounter_id
    )
    _require_location(connection, scope, location_id)
    changed = diff_fields(
        {
            "location_id": None if current_location is None else str(current_location),
            "summary": current_summary,
        },
        {
            "location_id": None if location_id is None else str(location_id),
            "summary": clean_summary,
        },
    )
    if changed:
        connection.execute(
            text("""
                UPDATE narrative.encounters SET location_id = :l, summary = :s, updated_at = now()
                WHERE encounter_id = :e
            """),
            {"l": location_id, "s": clean_summary, "e": encounter_id},
        )
    return PreparationResult(
        encounter_id=encounter_id,
        world_id=scope.world_id,
        changed=bool(changed),
        record_id=encounter_id,
        changed_fields=dict(changed),
    )


def add_encounter_participant(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    encounter_id: uuid.UUID,
    participant_entity_id: uuid.UUID,
    side: str = "party",
    initiative: int | None = None,
) -> PreparationResult:
    clean_side = normalize_side(side)
    clean_initiative = normalize_initiative(initiative)
    scope, _, _ = _prepare(connection, campaign_id, actor_user_id, encounter_id)
    _require_character(connection, scope, participant_entity_id)
    existing = connection.execute(
        text("""
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE participant_entity_id = :p) AS same
            FROM narrative.encounter_participants WHERE encounter_id = :e
        """),
        {"e": encounter_id, "p": participant_entity_id},
    ).one()
    if existing.same:
        raise EncounterParticipantExistsError(f"{participant_entity_id} is already in")
    if existing.total >= MAX_PARTICIPANTS:
        raise EncounterFullError(f"encounter {encounter_id} is full")
    participant_id = connection.execute(
        text("""
            INSERT INTO narrative.encounter_participants
                (encounter_id, participant_entity_id, side, initiative)
            VALUES (:e, :p, :s, :i) RETURNING encounter_participant_id
        """),
        {"e": encounter_id, "p": participant_entity_id, "s": clean_side, "i": clean_initiative},
    ).scalar()
    assert isinstance(participant_id, uuid.UUID)
    return PreparationResult(
        encounter_id=encounter_id,
        world_id=scope.world_id,
        changed=True,
        table="encounter_participants",
        record_id=participant_id,
        action="created",
        changed_fields=dict(
            initial_fields(
                {
                    "participant_entity_id": str(participant_entity_id),
                    "side": clean_side,
                    "initiative": clean_initiative,
                }
            )
        ),
    )


def _participant(
    connection: Connection, encounter_id: uuid.UUID, participant_id: uuid.UUID
) -> tuple[str, int | None]:
    row = connection.execute(
        text("""
            SELECT side, initiative FROM narrative.encounter_participants
            WHERE encounter_participant_id = :p AND encounter_id = :e FOR UPDATE
        """),
        {"p": participant_id, "e": encounter_id},
    ).one_or_none()
    if row is None:
        raise EncounterParticipantNotFoundError(f"participant {participant_id} not found")
    return str(row.side), row.initiative


class _Keep:
    """Marks an initiative the caller did not send: the stored value stays."""


KEEP_INITIATIVE = _Keep()


def update_encounter_participant(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    encounter_id: uuid.UUID,
    encounter_participant_id: uuid.UUID,
    side: str,
    initiative: int | None | _Keep = KEEP_INITIATIVE,
) -> PreparationResult:
    clean_side = normalize_side(side)
    scope, _, _ = _prepare(connection, campaign_id, actor_user_id, encounter_id)
    current_side, current_initiative = _participant(
        connection, encounter_id, encounter_participant_id
    )
    # Omitting the initiative leaves a stored one untouched; sending null clears it.
    clean_initiative = (
        current_initiative if isinstance(initiative, _Keep) else normalize_initiative(initiative)
    )
    changed = diff_fields(
        {"side": current_side, "initiative": current_initiative},
        {"side": clean_side, "initiative": clean_initiative},
    )
    if changed:
        connection.execute(
            text("""
                UPDATE narrative.encounter_participants SET side = :s, initiative = :i,
                    updated_at = now() WHERE encounter_participant_id = :p
            """),
            {"s": clean_side, "i": clean_initiative, "p": encounter_participant_id},
        )
    return PreparationResult(
        encounter_id=encounter_id,
        world_id=scope.world_id,
        changed=bool(changed),
        table="encounter_participants",
        record_id=encounter_participant_id,
        changed_fields=dict(changed),
    )


def remove_encounter_participant(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    encounter_id: uuid.UUID,
    encounter_participant_id: uuid.UUID,
) -> PreparationResult:
    scope, _, _ = _prepare(connection, campaign_id, actor_user_id, encounter_id)
    _participant(connection, encounter_id, encounter_participant_id)
    connection.execute(
        text("DELETE FROM narrative.encounter_participants WHERE encounter_participant_id = :p"),
        {"p": encounter_participant_id},
    )
    return PreparationResult(
        encounter_id=encounter_id,
        world_id=scope.world_id,
        changed=True,
        table="encounter_participants",
        record_id=encounter_participant_id,
        action="deleted",
    )
