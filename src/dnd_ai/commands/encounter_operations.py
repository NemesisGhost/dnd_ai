"""Encounter operation commands (Phase 15 checkpoint 15.3B-2b).

`start_prepared_encounter` moves a prepared (`pending`) encounter to `active`; `abort_encounter`
ends a pending or active encounter without a result. Recording turns and ending an encounter
with outcomes stay in `commands.encounters` (`resolve_combat_turn`, `end_encounter`), which the
Foundry combat sync also uses.

- Starting needs at least one participant and every participant still published; it opens round
  1 and records an `other` event ("Encounter started") that the encounter causes.
- Aborting a pending encounter records nothing (nothing had happened). Aborting an active one
  records an "Encounter aborted" event that links as the encounter's resulting event. Turns
  already recorded stay as history. A completed or aborted encounter cannot be aborted again.

Lock order: operation scope (world, membership rows, account, campaign `FOR SHARE`), the
encounter `FOR UPDATE` (its status is the optimistic guard, and it serializes with turns and
the end), then the participants `FOR SHARE` in id order.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import normalize_description
from dnd_ai.domain.encounter_operations import (
    EncounterFinishedError,
    EncounterNotReadyError,
)
from dnd_ai.domain.encounter_preparation import EncounterNotPendingError

from ._operations import OperationScope, lock_operation_scope
from ._shared import require_state_targetable, validate_session_campaign
from .encounters import EncounterNotFoundError
from .events import _insert_event_row
from .quest_runtime import time_or_clock


@dataclass(frozen=True)
class EncounterOperationResult:
    encounter_id: uuid.UUID
    world_id: uuid.UUID
    previous_status: str
    new_status: str
    event_id: uuid.UUID | None


def _lock(
    connection: Connection, scope: OperationScope, encounter_id: uuid.UUID
) -> tuple[str, uuid.UUID | None]:
    row = connection.execute(
        text("""
            SELECT campaign_id, status, session_id FROM narrative.encounters
            WHERE encounter_id = :e FOR UPDATE
        """),
        {"e": encounter_id},
    ).one_or_none()
    if row is None or row.campaign_id != scope.campaign_id:
        raise EncounterNotFoundError(f"encounter {encounter_id} is not in this campaign")
    return str(row.status), row.session_id


def _record(
    connection: Connection,
    scope: OperationScope,
    *,
    encounter_id: uuid.UUID,
    name: str,
    time_id: uuid.UUID,
    session_id: uuid.UUID | None,
    note: str | None,
) -> uuid.UUID:
    event_id = _insert_event_row(
        connection,
        world_id=scope.world_id,
        timeline_id=scope.timeline_id,
        world_time_id=time_id,
        event_type_code="other",
        name=name,
        details=note,
        campaign_id=scope.campaign_id,
        session_id=session_id,
    )
    connection.execute(
        text("INSERT INTO narrative.event_causes (event_id, cause_encounter_id) VALUES (:v, :e)"),
        {"v": event_id, "e": encounter_id},
    )
    return event_id


def start_prepared_encounter(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    encounter_id: uuid.UUID,
    world_time_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    note: str | None = None,
) -> EncounterOperationResult:
    details = normalize_description(note)
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    validate_session_campaign(connection, campaign_id=campaign_id, session_id=session_id)
    status, _ = _lock(connection, scope, encounter_id)
    if status != "pending":
        raise EncounterNotPendingError(f"encounter {encounter_id} is {status}")
    participants = [
        row[0]
        for row in connection.execute(
            text(
                "SELECT participant_entity_id FROM narrative.encounter_participants "
                "WHERE encounter_id = :e ORDER BY participant_entity_id"
            ),
            {"e": encounter_id},
        )
    ]
    if not participants:
        raise EncounterNotReadyError(f"encounter {encounter_id} has no participants")
    require_state_targetable(connection, *participants)
    time_id = time_or_clock(connection, scope, world_time_id)
    event_id = _record(
        connection,
        scope,
        encounter_id=encounter_id,
        name="Encounter started",
        time_id=time_id,
        session_id=session_id,
        note=details,
    )
    connection.execute(
        text("""
            INSERT INTO narrative.encounter_rounds (encounter_id, round_number)
            VALUES (:e, 1) ON CONFLICT DO NOTHING
        """),
        {"e": encounter_id},
    )
    connection.execute(
        text("""
            UPDATE narrative.encounters
            SET status = 'active', current_round = GREATEST(current_round, 1),
                world_time_id = :t, updated_at = now()
            WHERE encounter_id = :e
        """),
        {"t": time_id, "e": encounter_id},
    )
    return EncounterOperationResult(
        encounter_id=encounter_id,
        world_id=scope.world_id,
        previous_status="pending",
        new_status="active",
        event_id=event_id,
    )


def abort_encounter(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    encounter_id: uuid.UUID,
    world_time_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    note: str | None = None,
) -> EncounterOperationResult:
    details = normalize_description(note)
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    validate_session_campaign(connection, campaign_id=campaign_id, session_id=session_id)
    status, _ = _lock(connection, scope, encounter_id)
    if status not in ("pending", "active"):
        raise EncounterFinishedError(f"encounter {encounter_id} is {status}")
    event_id: uuid.UUID | None = None
    if status == "active":
        time_id = time_or_clock(connection, scope, world_time_id)
        event_id = _record(
            connection,
            scope,
            encounter_id=encounter_id,
            name="Encounter aborted",
            time_id=time_id,
            session_id=session_id,
            note=details,
        )
    connection.execute(
        text("""
            UPDATE narrative.encounters
            SET status = 'aborted', resulting_event_id = :v, updated_at = now()
            WHERE encounter_id = :e
        """),
        {"v": event_id, "e": encounter_id},
    )
    return EncounterOperationResult(
        encounter_id=encounter_id,
        world_id=scope.world_id,
        previous_status=status,
        new_status="aborted",
        event_id=event_id,
    )
