"""Session-ending command endpoint, plus the session list/detail read side.

Exposes `end_session` as `POST /campaigns/
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

Phase 13D backend-readiness workstream added the read side:
`GET /campaigns/{campaign_id}/sessions` (list) and `GET /campaigns/
{campaign_id}/sessions/{session_id}` (detail) — see `dnd_ai.queries.
session`'s own module docstring for the full authorization/audience-
filtering contract (`campaign.view`, plus an optional per-session
`resource_grants` deny/allow, plus the same draft-event visibility rule
`dnd_ai.api.summary` already applies to its own recent-events list). These
are reads: no idempotency key, no `audit.change_log` row, for the same
reasons every other query router in this package has neither.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.commands.sessions import _end_session_impl
from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.session import get_session_view, list_campaign_sessions

from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .errors import NotFoundError
from .idempotency import IdempotentReplay, begin_idempotent_request, complete_idempotent_request

router = APIRouter(tags=["sessions"])

# Narrative/GM bookkeeping, the same first-cut scoping every other command
# router in this codebase chose — see this module's own docstring.
_CANON_EDIT_CAPABILITY = "canon.edit"

# The read-only counterpart to _CANON_EDIT_CAPABILITY — the base gate every
# other read endpoint in this package uses (dnd_ai.api.dungeon/.characters/
# .quests/.knowledge/.summary all name the identical capability).
_SESSION_VIEW_CAPABILITY = "campaign.view"

# A caller holding this for the target session's own core.entities-less
# session_id resource-grant target additionally sees draft events linked to
# it — same split dnd_ai.api.summary already applies campaign-wide.
_DRAFT_EVENTS_CAPABILITY = "canon.edit"

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


# ---------------------------------------------------------------------------
# Read side (Phase 13D backend readiness) — response contracts
# ---------------------------------------------------------------------------


class SessionListItemResponse(BaseModel):
    session_id: uuid.UUID
    session_number: int
    title: str | None
    status_code: str
    started_at: datetime | None
    ended_at: datetime | None


class SessionEventResponse(BaseModel):
    event_id: uuid.UUID
    name: str
    summary: str | None
    event_type_code: str
    event_status_code: str
    world_time_id: uuid.UUID
    details: str | None


class SessionDetailResponse(BaseModel):
    session_id: uuid.UUID
    session_number: int
    title: str | None
    status_code: str
    started_at: datetime | None
    ended_at: datetime | None
    summary: str | None
    start_world_time_id: uuid.UUID | None
    end_world_time_id: uuid.UUID | None
    events: list[SessionEventResponse]


# ---------------------------------------------------------------------------
# Read side — routes
# ---------------------------------------------------------------------------


@router.get(
    "/campaigns/{campaign_id}/sessions",
    response_model=list[SessionListItemResponse],
    status_code=200,
)
def list_sessions_endpoint(
    campaign_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_SESSION_VIEW_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> list[SessionListItemResponse]:
    denied_session_ids, _allowed_session_ids = access.resource_grant_targets(
        _SESSION_VIEW_CAPABILITY, field_name="session_id"
    )
    items = list_campaign_sessions(
        connection, campaign_id=campaign_id, denied_session_ids=denied_session_ids
    )
    return [
        SessionListItemResponse(
            session_id=item.session_id,
            session_number=item.session_number,
            title=item.title,
            status_code=item.status_code,
            started_at=item.started_at,
            ended_at=item.ended_at,
        )
        for item in items
    ]


@router.get(
    "/campaigns/{campaign_id}/sessions/{session_id}",
    response_model=SessionDetailResponse,
    status_code=200,
)
def get_session_endpoint(
    campaign_id: uuid.UUID,
    session_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_SESSION_VIEW_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> SessionDetailResponse:
    if not access.has_capability(_SESSION_VIEW_CAPABILITY, session_id=session_id):
        # A per-session resource-grant deny — indistinguishable from a
        # nonexistent session, matching every other resource-scoped denial
        # in this codebase (dnd_ai.api.access's own module docstring).
        raise NotFoundError()

    denied_draft_event_ids, allowed_draft_event_ids = access.resource_grant_targets(
        _DRAFT_EVENTS_CAPABILITY, field_name="event_id"
    )
    view = get_session_view(
        connection,
        session_id=session_id,
        campaign_id=campaign_id,
        include_draft_events=access.has_capability(_DRAFT_EVENTS_CAPABILITY),
        denied_draft_event_ids=denied_draft_event_ids,
        allowed_draft_event_ids=allowed_draft_event_ids,
    )

    return SessionDetailResponse(
        session_id=view.session_id,
        session_number=view.session_number,
        title=view.title,
        status_code=view.status_code,
        started_at=view.started_at,
        ended_at=view.ended_at,
        summary=view.summary,
        start_world_time_id=view.start_world_time_id,
        end_world_time_id=view.end_world_time_id,
        events=[
            SessionEventResponse(
                event_id=e.event_id,
                name=e.name,
                summary=e.summary,
                event_type_code=e.event_type_code,
                event_status_code=e.event_status_code,
                world_time_id=e.world_time_id,
                details=e.details,
            )
            for e in view.events
        ],
    )
