"""Routes and travel endpoints (Phase 15 checkpoint 15.3A-2c, decision D-20).

    GET  /campaigns/{id}/authoring/routes?location_id=
    POST /campaigns/{id}/travel

Routes are created, edited, ended and archived through the relationship endpoints (kind
`route`: an origin and a destination place, distance, travel time and mode as text, and a flag
for a concealed route that only editors see); the list here is the editor's view of the routes
that touch one place. Travel records characters (or a party's current members) arriving at a
place together, with an optional route. Both are `canon.edit`; the write uses the campaign
idempotency store, re-checks authority under lock, answers with an id-only receipt and writes
one audit row.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection

from dnd_ai.commands.travel import record_travel
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authoring import DESCRIPTION_MAX_LENGTH
from dnd_ai.domain.relationship_authoring import MAX_TRAVELERS
from dnd_ai.queries.relationship_authoring import list_entity_relationships

from ._authoring import (
    BaseAuthoringRequest,
    finish_campaign_idempotency,
    start_campaign_idempotency,
)
from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key

router = APIRouter(tags=["travel"])

_Access = Annotated[AccessContext, Depends(require_campaign_capability("canon.edit"))]
_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]


class TravelRequest(BaseAuthoringRequest):
    destination_location_id: uuid.UUID
    character_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_TRAVELERS)
    party_id: uuid.UUID | None = None
    route_id: uuid.UUID | None = None
    world_time_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)


@router.get("/campaigns/{campaign_id}/authoring/routes")
def list_routes_endpoint(
    access: _Access, connection: _Conn, location_id: Annotated[uuid.UUID, Query()]
) -> dict[str, Any]:
    items = [
        i
        for i in list_entity_relationships(
            connection,
            world_id=timeline_world_id(connection, access.timeline_id),
            entity_id=location_id,
            include_archived=False,
        )
        if i.kind == "route"
    ]
    return {
        "items": [
            {
                "relationship_id": str(i.relationship_id),
                "description": i.description,
                "ended": i.ended,
                "row_version": i.row_version,
                "origin": next(
                    (
                        {"entity_id": str(p.entity_id), "name": p.name}
                        for p in i.participants
                        if p.role == "origin"
                    ),
                    None,
                ),
                "destination": next(
                    (
                        {"entity_id": str(p.entity_id), "name": p.name}
                        for p in i.participants
                        if p.role == "destination"
                    ),
                    None,
                ),
            }
            for i in items
        ]
    }


@router.post("/campaigns/{campaign_id}/travel")
def travel_endpoint(
    body: TravelRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    idem = start_campaign_idempotency(
        connection,
        actor_user_id=access.user_id,
        campaign_id=access.campaign_id,
        idempotency_key=idempotency_key,
        command_name="record_travel",
        payload=body.model_dump(mode="json"),
        correlation_id=correlation_id,
    )
    if idem.replay is not None:
        return idem.replay
    result = record_travel(
        connection,
        campaign_id=access.campaign_id,
        actor_user_id=access.user_id,
        destination_location_id=body.destination_location_id,
        character_ids=body.character_ids,
        party_id=body.party_id,
        route_id=body.route_id,
        world_time_id=body.world_time_id,
        note=body.note,
    )
    if result.changed:
        record_change_log(
            connection,
            change_action_code="updated",
            schema_name="campaign",
            table_name="character_location_history",
            record_id=result.event_id,
            entity_id=body.destination_location_id,
            world_id=result.world_id,
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name="record_travel",
            event_id=result.event_id,
            changed_fields={"traveler_count": {"from": None, "to": len(result.moved)}},
        )
    receipt: dict[str, Any] = {
        "destination_location_id": str(body.destination_location_id),
        "changed": result.changed,
        "moved": [str(c) for c in result.moved],
        "already_there": [str(c) for c in result.already_there],
    }
    if result.event_id is not None:
        receipt["event_id"] = str(result.event_id)
    finish_campaign_idempotency(connection, idem, status_code=200, body=receipt)
    return JSONResponse(status_code=200, content=receipt)
