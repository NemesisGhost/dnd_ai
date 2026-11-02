"""Event read model for the correction surface (Phase 15 checkpoint 15.2E-1).

For `canon.edit` holders only (the route enforces it first). Events of the campaign's own
timeline only: an ancestor's or a sibling's event is absent here, the same as a missing one.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from .campaign_clock import world_time_point

_LOCATION_COMPONENT = "current_location_id"


def _as_uuid(value: object) -> uuid.UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class EventParticipantView:
    entity_id: uuid.UUID
    name: str
    role: str


@dataclass(frozen=True)
class EventEffectView:
    component: str
    target_entity_id: uuid.UUID | None
    previous: object
    new: object
    application_status: str
    # Readable names for a `current_location_id` effect (None when not a location effect, or the
    # id does not resolve to an entity of the event's world). The raw values above are unchanged.
    target_name: str | None = None
    previous_name: str | None = None
    new_name: str | None = None


@dataclass(frozen=True)
class EventCorrectionView:
    kind: str
    reason: str
    correcting_event_id: uuid.UUID
    replacement_event_id: uuid.UUID | None


@dataclass(frozen=True)
class EventAuthoringView:
    event_id: uuid.UUID
    name: str
    event_type_code: str
    status: str
    world_time_id: uuid.UUID
    world_time: str
    session_id: uuid.UUID | None
    details: str | None
    participants: list[EventParticipantView] = field(default_factory=list)
    effects: list[EventEffectView] = field(default_factory=list)
    correction: EventCorrectionView | None = None
    # When this event is itself a correction or a replacement: the event it concerns.
    corrects_event_id: uuid.UUID | None = None


def get_event_authoring_view(
    connection: Connection, *, timeline_id: uuid.UUID, event_id: uuid.UUID
) -> EventAuthoringView | None:
    row = connection.execute(
        text("""
            SELECT e.event_id, ce.canonical_name, et.code AS type_code, es.code AS status_code,
                   e.world_time_id, e.session_id, e.details, ce.world_id
            FROM narrative.events e
            JOIN core.entities ce ON ce.entity_id = e.event_id
            JOIN narrative.event_types et ON et.event_type_id = e.event_type_id
            JOIN narrative.event_statuses es ON es.event_status_id = e.event_status_id
            WHERE e.event_id = :e AND e.timeline_id = :t
        """),
        {"e": event_id, "t": timeline_id},
    ).one_or_none()
    if row is None:
        return None
    _, display = world_time_point(connection, row.world_time_id)
    participants = [
        EventParticipantView(entity_id=p.participant_entity_id, name=str(p.name), role=str(p.role))
        for p in connection.execute(
            text("""
                SELECT ep.participant_entity_id, pe.canonical_name AS name, r.code AS role
                FROM narrative.event_participants ep
                JOIN core.entities pe ON pe.entity_id = ep.participant_entity_id
                JOIN narrative.event_participant_roles r
                  ON r.event_participant_role_id = ep.participant_role_id
                WHERE ep.event_id = :e ORDER BY lower(pe.canonical_name), ep.participant_entity_id
            """),
            {"e": event_id},
        )
    ]
    effect_rows = connection.execute(
        text(
            "SELECT target_component, target_entity_id, previous_value, new_value, "
            "application_status FROM narrative.event_effects WHERE event_id = :e "
            "ORDER BY created_at, event_effect_id"
        ),
        {"e": event_id},
    ).all()
    location_ids: set[uuid.UUID] = set()
    for f in effect_rows:
        if f.target_component == _LOCATION_COMPONENT:
            location_ids.update(
                i
                for i in (f.target_entity_id, _as_uuid(f.previous_value), _as_uuid(f.new_value))
                if i is not None
            )
    names: dict[uuid.UUID, str] = {}
    if location_ids:
        names = {
            r.entity_id: str(r.canonical_name)
            for r in connection.execute(
                text(
                    "SELECT entity_id, canonical_name FROM core.entities "
                    "WHERE entity_id = ANY(CAST(:ids AS uuid[])) AND world_id = :w"
                ),
                {"ids": sorted(location_ids), "w": row.world_id},
            )
        }

    def named(entity_id: uuid.UUID | None, component: object) -> str | None:
        if component != _LOCATION_COMPONENT or entity_id is None:
            return None
        return names.get(entity_id)

    effects = [
        EventEffectView(
            component=str(f.target_component),
            target_entity_id=f.target_entity_id,
            previous=f.previous_value,
            new=f.new_value,
            application_status=str(f.application_status),
            target_name=named(f.target_entity_id, f.target_component),
            previous_name=named(_as_uuid(f.previous_value), f.target_component),
            new_name=named(_as_uuid(f.new_value), f.target_component),
        )
        for f in effect_rows
    ]
    correction_row = connection.execute(
        text(
            "SELECT correction_kind, reason, correcting_event_id, replacement_event_id "
            "FROM narrative.event_corrections WHERE corrected_event_id = :e"
        ),
        {"e": event_id},
    ).one_or_none()
    corrects = connection.execute(
        text(
            "SELECT corrected_event_id FROM narrative.event_corrections "
            "WHERE correcting_event_id = :e OR replacement_event_id = :e LIMIT 1"
        ),
        {"e": event_id},
    ).scalar()
    return EventAuthoringView(
        event_id=event_id,
        name=str(row.canonical_name),
        event_type_code=str(row.type_code),
        status=str(row.status_code),
        world_time_id=row.world_time_id,
        world_time=display,
        session_id=row.session_id,
        details=row.details,
        participants=participants,
        effects=effects,
        correction=(
            None
            if correction_row is None
            else EventCorrectionView(
                kind=str(correction_row.correction_kind),
                reason=str(correction_row.reason),
                correcting_event_id=correction_row.correcting_event_id,
                replacement_event_id=correction_row.replacement_event_id,
            )
        ),
        corrects_event_id=corrects,
    )
