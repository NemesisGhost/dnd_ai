"""RecordEvent — the command that creates a narrative.events row.

Events created through gameplay (as opposed to AI proposals, which stay at
canon_status = proposed until approved per docs/ENTITY_LIFECYCLE.md §10) are
recorded directly at canon_status = canon, lifecycle_status = active: they
are the record of something that has already, authoritatively, happened.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from ._shared import lookup_id


@dataclass(frozen=True)
class EventParticipant:
    entity_id: uuid.UUID
    role_code: str
    notes: str | None = None


@dataclass(frozen=True)
class RecordEventResult:
    event_id: uuid.UUID


def _insert_event_row(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    event_type_code: str,
    event_status_code: str = "recorded",
    details: str | None = None,
    name: str,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    participants: tuple[EventParticipant, ...] = (),
    cause_event_id: uuid.UUID | None = None,
    cause_interaction_id: uuid.UUID | None = None,
    cause_description: str | None = None,
) -> uuid.UUID:
    """Insert the core.entities + narrative.events pair and any participants/
    cause row, without opening or closing a transaction. Callers that are
    themselves composing a larger multi-step command (see resolve_check in
    interactions.py) call this directly inside their own transaction; the
    standalone record_event() command below is a thin wrapper that owns its
    own transaction for a caller with no other work to combine it with.
    """
    # Resolve every lookup code before writing anything, so an unknown code
    # fails clean rather than after a partial insert (still rolled back
    # either way, but this avoids relying on that for the common typo case).
    event_entity_type_id = lookup_id(connection, "core", "entity_types", "entity_type_id", "event")
    canon_status_id = lookup_id(connection, "core", "canon_statuses", "canon_status_id", "canon")
    lifecycle_status_id = lookup_id(
        connection, "core", "lifecycle_statuses", "lifecycle_status_id", "active"
    )
    event_type_id = lookup_id(
        connection, "narrative", "event_types", "event_type_id", event_type_code
    )
    event_status_id = lookup_id(
        connection, "narrative", "event_statuses", "event_status_id", event_status_code
    )

    event_id = connection.execute(
        text("""
            INSERT INTO core.entities
                (world_id, entity_type_id, canonical_name, canon_status_id, lifecycle_status_id)
            VALUES (:world, :etype, :name, :canon, :lifecycle)
            RETURNING entity_id
        """),
        {
            "world": world_id,
            "etype": event_entity_type_id,
            "name": name,
            "canon": canon_status_id,
            "lifecycle": lifecycle_status_id,
        },
    ).scalar()
    assert isinstance(event_id, uuid.UUID)

    connection.execute(
        text("""
            INSERT INTO narrative.events
                (event_id, timeline_id, campaign_id, session_id, event_type_id,
                 event_status_id, world_time_id, details)
            VALUES (:id, :timeline, :campaign, :session, :event_type, :event_status,
                    :world_time, :details)
        """),
        {
            "id": event_id,
            "timeline": timeline_id,
            "campaign": campaign_id,
            "session": session_id,
            "event_type": event_type_id,
            "event_status": event_status_id,
            "world_time": world_time_id,
            "details": details,
        },
    )

    for participant in participants:
        role_id = lookup_id(
            connection,
            "narrative",
            "event_participant_roles",
            "event_participant_role_id",
            participant.role_code,
        )
        connection.execute(
            text("""
                INSERT INTO narrative.event_participants
                    (event_id, participant_entity_id, participant_role_id, notes)
                VALUES (:event, :entity, :role, :notes)
            """),
            {
                "event": event_id,
                "entity": participant.entity_id,
                "role": role_id,
                "notes": participant.notes,
            },
        )

    has_cause = (
        cause_event_id is not None
        or cause_interaction_id is not None
        or cause_description is not None
    )
    if has_cause:
        connection.execute(
            text("""
                INSERT INTO narrative.event_causes
                    (event_id, cause_event_id, cause_interaction_id, cause_description)
                VALUES (:event, :cause_event, :cause_interaction, :cause_description)
            """),
            {
                "event": event_id,
                "cause_event": cause_event_id,
                "cause_interaction": cause_interaction_id,
                "cause_description": cause_description,
            },
        )

    return event_id


def record_event(
    engine: Engine,
    *,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    event_type_code: str,
    name: str,
    event_status_code: str = "recorded",
    details: str | None = None,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    participants: tuple[EventParticipant, ...] = (),
    cause_event_id: uuid.UUID | None = None,
    cause_interaction_id: uuid.UUID | None = None,
    cause_description: str | None = None,
) -> RecordEventResult:
    """Record a standalone narrative event — the `RecordEvent` command from
    docs/ENTITY_LIFECYCLE.md §21. Owns its own transaction: a caller with
    other state changes to commit alongside the event (e.g. resolve_check)
    should use _insert_event_row directly inside its own transaction instead.
    """
    with engine.begin() as connection:
        event_id = _insert_event_row(
            connection,
            world_id=world_id,
            timeline_id=timeline_id,
            world_time_id=world_time_id,
            event_type_code=event_type_code,
            event_status_code=event_status_code,
            details=details,
            name=name,
            campaign_id=campaign_id,
            session_id=session_id,
            participants=participants,
            cause_event_id=cause_event_id,
            cause_interaction_id=cause_interaction_id,
            cause_description=cause_description,
        )
    return RecordEventResult(event_id=event_id)
