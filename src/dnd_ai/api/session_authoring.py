"""Session definition endpoints (Phase 15 checkpoint 15.2D-1, decision D-13).

    POST /campaigns/{id}/sessions                         (canon.edit)
    POST /campaigns/{id}/sessions/{session_id}/update     (canon.edit)
    POST /campaigns/{id}/sessions/{session_id}/archive    (canon.edit)
    POST /campaigns/{id}/sessions/{session_id}/restore    (canon.edit)

Reads stay on `dnd_ai.api.sessions` (list and detail). The session number is
assigned by the server. Writes use the campaign idempotency store, re-check
authority under lock, answer with an id-only receipt that carries the number, and
write one audit row (title is content and is redacted; the number and the planned
start are structural).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection

from dnd_ai.commands.session_authoring import (
    SessionResult,
    archive_session,
    restore_session,
    schedule_session,
    update_session,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authoring import DESCRIPTION_MAX_LENGTH, NAME_MAX_LENGTH, REASON_MAX_LENGTH

from ._authoring import (
    BaseAuthoringRequest,
    finish_campaign_idempotency,
    start_campaign_idempotency,
)
from ._content_support import clean_note
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key

router = APIRouter(tags=["session-authoring"])

_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]
_Edit = Annotated[AccessContext, Depends(require_campaign_capability("canon.edit"))]

_BASE = "/campaigns/{campaign_id}/sessions"


class SessionFields(BaseAuthoringRequest):
    title: str | None = Field(default=None, max_length=NAME_MAX_LENGTH)
    scheduled_for: datetime | None = None
    summary: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)


class UpdateSessionRequest(SessionFields):
    expected_row_version: int = Field(ge=1)


class ArchiveSessionRequest(BaseAuthoringRequest):
    expected_row_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=REASON_MAX_LENGTH)


class RestoreSessionRequest(BaseAuthoringRequest):
    expected_row_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=REASON_MAX_LENGTH)


def _run(
    *,
    command_name: str,
    access: AccessContext,
    connection: Connection,
    idempotency_key: str | None,
    correlation_id: str | None,
    payload: dict[str, Any],
    command: Any,
    status_code: int,
    reason: str | None = None,
    lifecycle_action: str | None = None,
) -> Any:
    idem = start_campaign_idempotency(
        connection,
        actor_user_id=access.user_id,
        campaign_id=access.campaign_id,
        idempotency_key=idempotency_key,
        command_name=command_name,
        payload=payload,
        correlation_id=correlation_id,
    )
    if idem.replay is not None:
        return idem.replay
    result: SessionResult = command()
    if result.changed:
        record_change_log(
            connection,
            change_action_code=lifecycle_action or ("created" if result.created else "updated"),
            schema_name="campaign",
            table_name="sessions",
            record_id=result.session_id,
            entity_id=None,
            world_id=result.world_id,
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=command_name,
            event_id=None,
            previous_status=result.previous_lifecycle_status if lifecycle_action else None,
            new_status=result.lifecycle_status if lifecycle_action else None,
            changed_fields=result.changed_fields or None,
            reason=clean_note(reason),
        )
    receipt = {
        "session_id": str(result.session_id),
        "session_number": result.session_number,
        "row_version": result.row_version,
        "created": result.created,
        "changed": result.changed,
    }
    finish_campaign_idempotency(connection, idem, status_code=status_code, body=receipt)
    return JSONResponse(status_code=status_code, content=receipt)


@router.post(_BASE, status_code=201)
def schedule_session_endpoint(
    body: SessionFields,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="schedule_session",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=body.model_dump(mode="json"),
        status_code=201,
        command=lambda: schedule_session(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            title=body.title,
            scheduled_for=body.scheduled_for,
            summary=body.summary,
        ),
    )


@router.post(_BASE + "/{session_id}/update")
def update_session_endpoint(
    session_id: uuid.UUID,
    body: UpdateSessionRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="update_session",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"session_id": str(session_id), **body.model_dump(mode="json")},
        status_code=200,
        command=lambda: update_session(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            session_id=session_id,
            expected_row_version=body.expected_row_version,
            title=body.title,
            scheduled_for=body.scheduled_for,
            summary=body.summary,
        ),
    )


@router.post(_BASE + "/{session_id}/archive")
def archive_session_endpoint(
    session_id: uuid.UUID,
    body: ArchiveSessionRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="archive_session",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"session_id": str(session_id), **body.model_dump(mode="json")},
        status_code=200,
        reason=body.reason,
        lifecycle_action="archived",
        command=lambda: archive_session(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            session_id=session_id,
            expected_row_version=body.expected_row_version,
            reason=body.reason,
        ),
    )


@router.post(_BASE + "/{session_id}/restore")
def restore_session_endpoint(
    session_id: uuid.UUID,
    body: RestoreSessionRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="restore_session",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"session_id": str(session_id), **body.model_dump(mode="json")},
        status_code=200,
        reason=body.reason,
        lifecycle_action="restored",
        command=lambda: restore_session(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            session_id=session_id,
            expected_row_version=body.expected_row_version,
            reason=body.reason,
        ),
    )
