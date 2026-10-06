"""Record travel: several characters, or a party's current members, arrive at a place together
(Phase 15 checkpoint 15.3A-2c, decision D-20).

One `characters_traveled` event is recorded for the whole journey, with an effect for every
character that moved, and each mover's `campaign.character_location_history` is updated in the
same transaction: the open row is closed at the arrival time and a new one opened. A traveler
already at the destination is left alone (reported, not an error); when nobody moves nothing is
written. An optional route (a `route` relationship, see `commands.world_relationships`) must be
active and join the traveler's current place to the destination in one direction or the other.

Lock order: operation scope, the campaign party (when named), the destination and the travelers
`FOR SHARE` in id order, the route's relationship row `FOR SHARE`, then, per traveler
in id order, an advisory lock on (timeline, traveler) and the open location row `FOR UPDATE` (so two
journeys sharing a traveler serialize, even from "nowhere").
"""

import json
import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from dnd_ai.domain.relationship_authoring import (
    MAX_TRAVELERS,
    PLACE_TYPE_CODES,
    RouteMismatchError,
    TravelInvalidError,
    TravelTimeInvalidError,
)

from ._content import lock_entities
from ._operations import lock_operation_scope
from ._shared import validate_campaign_party
from .events import EventParticipant, _insert_event_row
from .quest_runtime import time_or_clock

_TRAVELER_TYPES = frozenset({"npc", "player_character"})


@dataclass(frozen=True)
class TravelResult:
    world_id: uuid.UUID
    changed: bool
    event_id: uuid.UUID | None
    moved: list[uuid.UUID] = field(default_factory=list)
    already_there: list[uuid.UUID] = field(default_factory=list)


def _route_ends(
    connection: Connection, *, world_id: uuid.UUID, route_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    row = connection.execute(
        text("""
            SELECT r.lifecycle_status_id FROM world.relationships r
            JOIN world.route_relationships rr ON rr.relationship_id = r.relationship_id
            WHERE r.relationship_id = :r AND r.world_id = :w FOR SHARE OF r
        """),
        {"r": route_id, "w": world_id},
    ).one_or_none()
    if row is None:
        raise RouteMismatchError(f"{route_id} is not a route of this world")
    active = connection.execute(
        text(
            "SELECT 1 FROM core.lifecycle_statuses WHERE lifecycle_status_id = :s AND code = 'active'"
        ),
        {"s": row.lifecycle_status_id},
    ).scalar()
    if active is None:
        raise RouteMismatchError(f"route {route_id} is archived")
    ends = {
        str(p.role): p.entity_id
        for p in connection.execute(
            text(
                "SELECT p.entity_id, r.code AS role FROM world.relationship_participants p "
                "JOIN world.relationship_participant_roles r "
                "ON r.relationship_participant_role_id = p.participant_role_id "
                "WHERE p.relationship_id = :r"
            ),
            {"r": route_id},
        )
    }
    return ends["origin"], ends["destination"]


def record_travel(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    destination_location_id: uuid.UUID,
    character_ids: list[uuid.UUID],
    party_id: uuid.UUID | None = None,
    route_id: uuid.UUID | None = None,
    world_time_id: uuid.UUID | None = None,
    note: str | None = None,
) -> TravelResult:
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    travelers = set(character_ids)
    if party_id is not None:
        validate_campaign_party(
            connection, campaign_id=campaign_id, party_id=party_id, lock=True, require_active=True
        )
        travelers |= set(
            connection.execute(
                text(
                    "SELECT member_entity_id FROM campaign.party_memberships "
                    "WHERE timeline_id = :t AND party_id = :p "
                    "AND effective_to_world_time_id IS NULL"
                ),
                {"t": scope.timeline_id, "p": party_id},
            ).scalars()
        )
    ordered = sorted(travelers)
    if not ordered or len(ordered) > MAX_TRAVELERS:
        raise TravelInvalidError("travel needs one to fifty travelers")

    locked = lock_entities(
        connection, world_id=scope.world_id, share_ids=[destination_location_id, *ordered]
    )
    destination = locked.get(destination_location_id)
    if (
        destination is None
        or destination.entity_type_code not in PLACE_TYPE_CODES
        or destination.canon_status != "canon"
        or destination.lifecycle_status != "active"
    ):
        raise TravelInvalidError(f"{destination_location_id} is not a published place")
    for traveler_id in ordered:
        traveler = locked.get(traveler_id)
        if (
            traveler is None
            or traveler.entity_type_code not in _TRAVELER_TYPES
            or traveler.canon_status != "canon"
            or traveler.lifecycle_status != "active"
        ):
            raise TravelInvalidError(f"{traveler_id} cannot travel")
    ends = (
        None
        if route_id is None
        else _route_ends(connection, world_id=scope.world_id, route_id=route_id)
    )
    if ends is not None and destination_location_id not in ends:
        raise RouteMismatchError("the destination is not an end of that route")

    time_id = time_or_clock(connection, scope, world_time_id)
    new_key = connection.execute(
        text("SELECT sort_key FROM core.world_times WHERE world_time_id = :t"), {"t": time_id}
    ).scalar()
    movers: list[tuple[uuid.UUID, uuid.UUID | None, uuid.UUID | None]] = []
    already: list[uuid.UUID] = []
    for traveler_id in ordered:
        # A traveler with no open location row has nothing to lock, so serialize on the
        # traveler: two journeys that both start from "nowhere" cannot both open a row.
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"campaign.character_location:{scope.timeline_id}:{traveler_id}"},
        )
        current = connection.execute(
            text("""
                SELECT h.character_location_history_id, h.location_id, wt.sort_key
                FROM campaign.character_location_history h
                LEFT JOIN core.world_times wt ON wt.world_time_id = h.arrived_at_world_time_id
                WHERE h.timeline_id = :t AND h.character_id = :c
                  AND h.departed_at_world_time_id IS NULL
                FOR UPDATE OF h
            """),
            {"t": scope.timeline_id, "c": traveler_id},
        ).one_or_none()
        if current is not None and current.location_id == destination_location_id:
            already.append(traveler_id)
            continue
        if current is not None and current.sort_key is not None and new_key <= current.sort_key:
            raise TravelTimeInvalidError(f"{traveler_id} arrived there at or after that time")
        if ends is not None:
            other = ends[1] if destination_location_id == ends[0] else ends[0]
            if current is None or current.location_id != other:
                raise RouteMismatchError(f"{traveler_id} is not at the other end of the route")
        movers.append(
            (
                traveler_id,
                None if current is None else current.character_location_history_id,
                None if current is None else current.location_id,
            )
        )
    if not movers:
        return TravelResult(
            world_id=scope.world_id, changed=False, event_id=None, already_there=already
        )

    event_id = _insert_event_row(
        connection,
        world_id=scope.world_id,
        timeline_id=scope.timeline_id,
        world_time_id=time_id,
        event_type_code="characters_traveled",
        name="Characters traveled",
        details=(note.strip() or None) if note is not None else None,
        campaign_id=campaign_id,
        participants=tuple(EventParticipant(entity_id=c, role_code="actor") for c, _, _ in movers),
    )
    for traveler_id, history_id, previous_location in movers:
        if history_id is not None:
            connection.execute(
                text(
                    "UPDATE campaign.character_location_history "
                    "SET departed_at_world_time_id = :t WHERE character_location_history_id = :h"
                ),
                {"t": time_id, "h": history_id},
            )
        connection.execute(
            text("""
                INSERT INTO campaign.character_location_history
                    (timeline_id, character_id, location_id, arrived_at_world_time_id)
                VALUES (:t, :c, :l, :time)
            """),
            {
                "t": scope.timeline_id,
                "c": traveler_id,
                "l": destination_location_id,
                "time": time_id,
            },
        )
        connection.execute(
            text("""
                INSERT INTO narrative.event_effects
                    (event_id, target_entity_id, target_component, previous_value, new_value,
                     effective_world_time_id)
                VALUES (:e, :c, 'current_location_id', CAST(:previous AS jsonb),
                        CAST(:new AS jsonb), :time)
            """),
            {
                "e": event_id,
                "c": traveler_id,
                "previous": None
                if previous_location is None
                else json.dumps(str(previous_location)),
                "new": json.dumps(str(destination_location_id)),
                "time": time_id,
            },
        )
    return TravelResult(
        world_id=scope.world_id,
        changed=True,
        event_id=event_id,
        moved=[c for c, _, _ in movers],
        already_there=already,
    )


__all__ = ["TravelResult", "record_travel"]
