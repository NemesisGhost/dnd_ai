"""Command endpoint over `dnd_ai.commands.movement` — docs/PLAN.md §25
step 7 ("Move the party into the dungeon"), the write path `dnd_ai.
queries.character.get_character_view` (Phase 10 workstream 13) already
assumed existed. Exposes `enter_location` as `POST /campaigns/{campaign_id}
/characters/{character_id}/location`, on the same already-delivered OIDC
authentication, transaction management, and access resolution every other
command router uses.

Authorization: requires `canon.edit`, the same GM/adapter-level scoping
`dnd_ai.api.interactions` uses for interactions and check resolutions —
movement is not itself a check-gated action (see `dnd_ai.commands.
movement`'s own docstring for why), but recording where a character now
stands is still a canon-affecting mutation, not a bare read.

Idempotency: `enter_location` is already idempotent for the common case —
re-entering the character's own current location is a defined no-op (see
`dnd_ai.commands.movement`'s docstring) — but a genuine move (a location
change) is not naturally deduplicated the same way, so this route still
uses the durable `security.idempotent_requests` mechanism every other
create/mutate endpoint uses, protecting against a dropped-response retry
that would otherwise record two separate movement events for the same
logical request.

Auditing: one `audit.change_log` row per call that actually recorded a
movement (`result.moved`); a same-location call that no-ops records
neither an event nor an audit row, since nothing changed. `entity_id` is
`character_id` — `campaign.character_location_history` is not itself a
`core.entities` row, but the character it concerns is, the same "owning
entity" indirection `dnd_ai.commands.quests`' workstream 7 correction pass
established. `world_id` is resolved server-side from the campaign's own
pinned timeline, never caller-supplied.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.commands.movement import _enter_location_impl
from dnd_ai.domain.access import AccessContext

from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .idempotency import IdempotentReplay, begin_idempotent_request, complete_idempotent_request

router = APIRouter(tags=["movement"])

# Canon-affecting mutation, same first-cut scoping every other command
# router in this codebase chose — see this module's own docstring.
_CANON_EDIT_CAPABILITY = "canon.edit"

_ENTER_LOCATION_COMMAND_NAME = "enter_location"
_CREATED_CHANGE_ACTION = "created"


class EnterLocationRequest(BaseModel):
    world_time_id: uuid.UUID
    location_id: uuid.UUID
    session_id: uuid.UUID | None = None
    details: str | None = None


class EnterLocationResponse(BaseModel):
    character_location_history_id: uuid.UUID
    event_id: uuid.UUID | None
    moved: bool


@router.post(
    "/campaigns/{campaign_id}/characters/{character_id}/location",
    response_model=EnterLocationResponse,
    status_code=200,
)
def enter_location_endpoint(
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    body: EnterLocationRequest,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_CANON_EDIT_CAPABILITY))],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> EnterLocationResponse:
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "character_id": str(character_id),
            **body.model_dump(mode="json"),
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_ENTER_LOCATION_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return EnterLocationResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = _enter_location_impl(
        connection,
        timeline_id=access.timeline_id,
        world_time_id=body.world_time_id,
        character_id=character_id,
        location_id=body.location_id,
        campaign_id=campaign_id,
        session_id=body.session_id,
        details=body.details,
    )

    if result.moved:
        record_change_log(
            connection,
            change_action_code=_CREATED_CHANGE_ACTION,
            schema_name="campaign",
            table_name="character_location_history",
            record_id=result.character_location_history_id,
            entity_id=character_id,
            world_id=timeline_world_id(connection, access.timeline_id),
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=_ENTER_LOCATION_COMMAND_NAME,
            event_id=result.event_id,
        )

    response = EnterLocationResponse(
        character_location_history_id=result.character_location_history_id,
        event_id=result.event_id,
        moved=result.moved,
    )

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=200,
            response_body=response.model_dump(mode="json"),
        )

    return response
