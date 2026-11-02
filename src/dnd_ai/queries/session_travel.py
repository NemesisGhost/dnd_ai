"""Travel entries for a session's detail and review (Session travel fix, checkpoint C2).

A `characters_traveled` event linked to a session carries one `current_location_id` effect per
traveler (previous and new place). This module turns the session's already-filtered event list
into readable entries: who moved, from where and to where, and when in the world. It is the only
place that resolves those ids to names for the session surfaces.

Audience, applied here and nowhere else:

- The caller passes the events `get_session_view` already returned, so the draft/voided and
  per-session filtering is inherited, not repeated.
- Names pass through `discoverable_entity_ids` with the caller's `WorldEntityVisibility`, the same
  projection the relationship list uses. A leg whose traveler is not discoverable is omitted
  (no placeholder, no count). A place that is not discoverable becomes `unavailable` for that side.
  A raw id is never returned in a name field.
- The GM note (`details`) is returned only when `include_gm_note` is set.
- Nothing here writes: reading travel grants no knowledge, exposure or access.

Legs are never merged: each carries its own origin, so travelers who left from different places
stay on different lines. `from` is `unrecorded` when the traveler had no earlier location.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from .session import SessionEventView
from .world_explorer import WorldEntityVisibility, discoverable_entity_ids

TRAVEL_EVENT_TYPE = "characters_traveled"

NAMED = "named"
UNRECORDED = "unrecorded"
UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class TravelPlace:
    state: str
    entity_id: uuid.UUID | None = None
    name: str | None = None


@dataclass(frozen=True)
class TravelLeg:
    traveler_id: uuid.UUID
    traveler_name: str
    origin: TravelPlace
    destination: TravelPlace


@dataclass(frozen=True)
class SessionTravelEntry:
    event_id: uuid.UUID
    world_time_id: uuid.UUID
    world_time: str
    note: str | None
    legs: tuple[TravelLeg, ...] = field(default_factory=tuple)


def _as_uuid(value: object) -> uuid.UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def list_session_travel(
    connection: Connection,
    *,
    events: Sequence[SessionEventView],
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    visibility: WorldEntityVisibility,
    include_gm_note: bool,
    any_event_type: bool = False,
) -> tuple[SessionTravelEntry, ...]:
    """Entries for the travel events among `events`, in the order given (in-world time, then
    creation). `any_event_type` also reads the `current_location_id` effects of other event types
    (a recorded move), which the event explanations share with travel."""
    travel_events = [e for e in events if any_event_type or e.event_type_code == TRAVEL_EVENT_TYPE]
    if not travel_events:
        return ()
    event_ids = [e.event_id for e in travel_events]
    effect_rows = connection.execute(
        text("""
            SELECT event_id, target_entity_id, previous_value, new_value
            FROM narrative.event_effects
            WHERE event_id = ANY(CAST(:events AS uuid[]))
              AND target_component = 'current_location_id'
              AND target_entity_id IS NOT NULL
        """),
        {"events": event_ids},
    ).all()
    # (event, traveler, previous id or None, previous readable?, new id or None)
    raw: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID | None, bool, uuid.UUID | None]] = []
    candidates: set[uuid.UUID] = set()
    for row in effect_rows:
        previous = _as_uuid(row.previous_value)
        previous_unrecorded = row.previous_value is None
        new = _as_uuid(row.new_value)
        raw.append((row.event_id, row.target_entity_id, previous, previous_unrecorded, new))
        candidates.add(row.target_entity_id)
        candidates.update(i for i in (previous, new) if i is not None)

    names: dict[uuid.UUID, str] = {}
    if candidates:
        visible = discoverable_entity_ids(
            connection,
            sorted(candidates),
            world_id=world_id,
            timeline_id=timeline_id,
            visibility=visibility,
        )
        if visible:
            names = {
                r.entity_id: str(r.canonical_name)
                for r in connection.execute(
                    text(
                        "SELECT entity_id, canonical_name FROM core.entities "
                        "WHERE entity_id = ANY(CAST(:ids AS uuid[])) AND world_id = :w"
                    ),
                    {"ids": sorted(visible), "w": world_id},
                )
            }

    def place(entity_id: uuid.UUID | None, *, unrecorded: bool = False) -> TravelPlace:
        if unrecorded:
            return TravelPlace(UNRECORDED)
        if entity_id is not None and entity_id in names:
            return TravelPlace(NAMED, entity_id, names[entity_id])
        return TravelPlace(UNAVAILABLE)

    notes: dict[uuid.UUID, str | None] = {}
    if include_gm_note:
        notes = {
            r.event_id: r.details
            for r in connection.execute(
                text(
                    "SELECT event_id, details FROM narrative.events "
                    "WHERE event_id = ANY(CAST(:events AS uuid[]))"
                ),
                {"events": event_ids},
            )
        }

    legs_by_event: dict[uuid.UUID, list[TravelLeg]] = {}
    for event_id, traveler, previous, previous_unrecorded, new in raw:
        if traveler not in names:
            continue
        legs_by_event.setdefault(event_id, []).append(
            TravelLeg(
                traveler_id=traveler,
                traveler_name=names[traveler],
                origin=place(previous, unrecorded=previous_unrecorded),
                destination=place(new),
            )
        )
    return tuple(
        SessionTravelEntry(
            event_id=e.event_id,
            world_time_id=e.world_time_id,
            world_time=e.world_time,
            note=notes.get(e.event_id),
            legs=tuple(
                sorted(
                    legs_by_event.get(e.event_id, []),
                    key=lambda leg: (leg.traveler_name.lower(), str(leg.traveler_id)),
                )
            ),
        )
        for e in travel_events
    )
