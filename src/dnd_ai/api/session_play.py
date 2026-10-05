"""Session play endpoints (Phase 15 checkpoint 15.2D-2, decisions D-13 and D-14).

    POST /campaigns/{id}/sessions/{session_id}/start
    POST /campaigns/{id}/sessions/{session_id}/end
    POST /campaigns/{id}/sessions/{session_id}/participants
    POST /campaigns/{id}/sessions/{session_id}/participants/{participant_id}/remove
    POST /campaigns/{id}/sessions/{session_id}/log

All `canon.edit`. Each uses the campaign idempotency store, re-checks authority under
lock in the command, answers with an id-only receipt, and writes one audit row (log
entries are redacted in audit; their `details` are GM-only and never returned to a
player, who sees only the entry text through the session detail). `end` replaces the
earlier ungated end route: it now needs the version the editor saw and a session that
is in progress.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection

from dnd_ai.commands.session_play import (
    PlayResult,
    add_session_participant,
    end_session,
    record_session_log_entry,
    remove_session_participant,
    start_session,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authoring import DESCRIPTION_MAX_LENGTH
from dnd_ai.domain.session_authoring import (
    LOG_DETAILS_MAX_LENGTH,
    LOG_ENTRY_MAX_LENGTH,
    PARTICIPATION_ROLES,
)

from ._authoring import (
    BaseAuthoringRequest,
    finish_campaign_idempotency,
    start_campaign_idempotency,
)
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key

router = APIRouter(tags=["session-play"])

_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]
_Edit = Annotated[AccessContext, Depends(require_campaign_capability("canon.edit"))]

_BASE = "/campaigns/{campaign_id}/sessions/{session_id}"


class StartSessionRequest(BaseAuthoringRequest):
    expected_row_version: int = Field(ge=1)
    # Defaults to the campaign clock when absent.
    start_world_time_id: uuid.UUID | None = None


class EndSessionRequest(BaseAuthoringRequest):
    expected_row_version: int = Field(ge=1)
    end_world_time_id: uuid.UUID | None = None
    summary: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)


class AddParticipantRequest(BaseAuthoringRequest):
    expected_row_version: int = Field(ge=1)
    character_id: uuid.UUID
    participation_role: str = Field(pattern="^(" + "|".join(PARTICIPATION_ROLES) + ")$")


class RemoveParticipantRequest(BaseAuthoringRequest):
    expected_row_version: int = Field(ge=1)


class LogEntryRequest(BaseAuthoringRequest):
    entry: str = Field(min_length=1, max_length=LOG_ENTRY_MAX_LENGTH)
    details: str | None = Field(default=None, max_length=LOG_DETAILS_MAX_LENGTH)
    world_time_id: uuid.UUID | None = None
    character_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


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
    table: str,
    action: str,
    record_of: Any,
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
    result: PlayResult = command()
    record_change_log(
        connection,
        change_action_code=action,
        schema_name="narrative" if table == "events" else "campaign",
        table_name=table,
        record_id=record_of(result),
        entity_id=result.event_id if table == "events" else result.character_id,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=command_name,
        event_id=result.event_id,
        changed_fields=result.changed_fields or None,
    )
    receipt: dict[str, Any] = {
        "session_id": str(result.session_id),
        "row_version": result.row_version,
        "changed": True,
    }
    if result.participant_id is not None:
        receipt["session_participant_id"] = str(result.participant_id)
    if result.event_id is not None:
        receipt["event_id"] = str(result.event_id)
    finish_campaign_idempotency(connection, idem, status_code=status_code, body=receipt)
    return JSONResponse(status_code=status_code, content=receipt)


@router.post(_BASE + "/start")
def start_session_endpoint(
    session_id: uuid.UUID,
    body: StartSessionRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="start_session",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"session_id": str(session_id), **body.model_dump(mode="json")},
        status_code=200,
        table="sessions",
        action="updated",
        record_of=lambda r: r.session_id,
        command=lambda: start_session(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            session_id=session_id,
            expected_row_version=body.expected_row_version,
            start_world_time_id=body.start_world_time_id,
        ),
    )


@router.post(_BASE + "/end")
def end_session_endpoint(
    session_id: uuid.UUID,
    body: EndSessionRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="end_session",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"session_id": str(session_id), **body.model_dump(mode="json")},
        status_code=200,
        table="sessions",
        action="updated",
        record_of=lambda r: r.session_id,
        command=lambda: end_session(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            session_id=session_id,
            expected_row_version=body.expected_row_version,
            end_world_time_id=body.end_world_time_id,
            summary=body.summary,
        ),
    )


@router.post(_BASE + "/participants", status_code=201)
def add_participant_endpoint(
    session_id: uuid.UUID,
    body: AddParticipantRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="add_session_participant",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"session_id": str(session_id), **body.model_dump(mode="json")},
        status_code=201,
        table="session_participants",
        action="created",
        record_of=lambda r: r.participant_id,
        command=lambda: add_session_participant(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            session_id=session_id,
            expected_row_version=body.expected_row_version,
            character_id=body.character_id,
            participation_role=body.participation_role,
        ),
    )


@router.post(_BASE + "/participants/{session_participant_id}/remove")
def remove_participant_endpoint(
    session_id: uuid.UUID,
    session_participant_id: uuid.UUID,
    body: RemoveParticipantRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="remove_session_participant",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={
            "session_id": str(session_id),
            "session_participant_id": str(session_participant_id),
            **body.model_dump(mode="json"),
        },
        status_code=200,
        table="session_participants",
        action="updated",
        record_of=lambda r: r.participant_id,
        command=lambda: remove_session_participant(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            session_id=session_id,
            expected_row_version=body.expected_row_version,
            session_participant_id=session_participant_id,
        ),
    )


@router.post(_BASE + "/log", status_code=201)
def log_entry_endpoint(
    session_id: uuid.UUID,
    body: LogEntryRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="record_session_log_entry",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"session_id": str(session_id), **body.model_dump(mode="json")},
        status_code=201,
        table="events",
        action="created",
        record_of=lambda r: r.event_id,
        command=lambda: record_session_log_entry(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            session_id=session_id,
            entry=body.entry,
            details=body.details,
            world_time_id=body.world_time_id,
            character_ids=tuple(body.character_ids),
        ),
    )
