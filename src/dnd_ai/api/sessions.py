"""Command endpoint over `dnd_ai.commands.sessions` — docs/PLAN.md §25
step 14 ("End the session and generate a summary"), the write half `dnd_ai
.api.summary`'s existing `GET /campaigns/{campaign_id}/summary`
(workstream 22) never had. Exposes `end_session` as `POST /campaigns/
{campaign_id}/sessions/{session_id}/end`.

Authorization: requires `canon.edit`, the same GM/adapter-level scoping
`dnd_ai.api.interactions`/`.movement` use — ending a session is a
narrative/GM bookkeeping action, not access administration.

Idempotency: `end_session` is already idempotent for the common case
(ending an already-ended session is a no-op — see `dnd_ai.commands.
sessions`'s docstring), but this route still uses the durable `security.
idempotent_requests` mechanism every other create/mutate endpoint uses,
protecting the *first* end call against a dropped-response retry the same
way `dnd_ai.api.movement.enter_location_endpoint` does for its own
first-move call.

Auditing: one `audit.change_log` row per call that actually ended the
session (`result.already_ended is False`); a replay against an
already-ended session records nothing further, since nothing changed.
`entity_id` is `None` — `campaign.sessions` is not a `core.entities` row.
`world_id` is resolved server-side from the campaign's own pinned
timeline, never caller-supplied.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.commands.sessions import _end_session_impl
from dnd_ai.domain.access import AccessContext

from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .idempotency import IdempotentReplay, begin_idempotent_request, complete_idempotent_request

router = APIRouter(tags=["sessions"])

# Narrative/GM bookkeeping, the same first-cut scoping every other command
# router in this codebase chose — see this module's own docstring.
_CANON_EDIT_CAPABILITY = "canon.edit"

_END_SESSION_COMMAND_NAME = "end_session"
_UPDATED_CHANGE_ACTION = "updated"


class EndSessionRequest(BaseModel):
    end_world_time_id: uuid.UUID
    summary: str | None = None


class EndSessionResponse(BaseModel):
    session_id: uuid.UUID
    already_ended: bool


@router.post(
    "/campaigns/{campaign_id}/sessions/{session_id}/end",
    response_model=EndSessionResponse,
    status_code=200,
)
def end_session_endpoint(
    campaign_id: uuid.UUID,
    session_id: uuid.UUID,
    body: EndSessionRequest,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_CANON_EDIT_CAPABILITY))],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> EndSessionResponse:
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "session_id": str(session_id),
            **body.model_dump(mode="json"),
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_END_SESSION_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return EndSessionResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = _end_session_impl(
        connection,
        session_id=session_id,
        campaign_id=campaign_id,
        end_world_time_id=body.end_world_time_id,
        summary=body.summary,
    )

    if not result.already_ended:
        record_change_log(
            connection,
            change_action_code=_UPDATED_CHANGE_ACTION,
            schema_name="campaign",
            table_name="sessions",
            record_id=session_id,
            entity_id=None,
            world_id=timeline_world_id(connection, access.timeline_id),
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=_END_SESSION_COMMAND_NAME,
            event_id=None,
        )

    response = EndSessionResponse(session_id=result.session_id, already_ended=result.already_ended)

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=200,
            response_body=response.model_dump(mode="json"),
        )

    return response
