"""Event correction endpoints (Phase 15 checkpoint 15.2E-1, decision D-15).

    GET  /campaigns/{id}/events/{event_id}                       (canon.edit)
    GET  /campaigns/{id}/events/{event_id}/correction-preview    (canon.edit)
    POST /campaigns/{id}/events/{event_id}/void                  (canon.edit)
    POST /campaigns/{id}/events/{event_id}/correct               (canon.edit)

Only events of the campaign's own timeline are reachable (an ancestor's, a sibling's, or a
missing event is one 404). The preview is read-only and says, for each effect, whether it
can be reversed now. The writes apply compensation and relink atomically (see
`dnd_ai.commands.event_corrections`), use the campaign idempotency store, answer with an
id-only receipt, and write two audit rows: the original event's status change and the new
correction record (the reason is GM-only and redacted). Human principals only: an AI
proposal or a Foundry credential has no membership to authorize these.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection

from dnd_ai.commands.event_corrections import (
    CorrectionResult,
    assess_event,
    correct_event,
    void_event,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authoring import REASON_MAX_LENGTH
from dnd_ai.domain.event_corrections import (
    EVENT_DETAILS_MAX_LENGTH,
    EVENT_NAME_MAX_LENGTH,
    RECORDABLE_NARRATIVE_TYPES,
    EventNotFoundError,
)
from dnd_ai.queries.event_authoring import get_event_authoring_view

from ._authoring import (
    BaseAuthoringRequest,
    finish_campaign_idempotency,
    start_campaign_idempotency,
)
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .errors import NotFoundError

router = APIRouter(tags=["event-corrections"])

_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]
_Edit = Annotated[AccessContext, Depends(require_campaign_capability("canon.edit"))]

_BASE = "/campaigns/{campaign_id}/events/{event_id}"


class VoidEventRequest(BaseAuthoringRequest):
    reason: str = Field(min_length=1, max_length=REASON_MAX_LENGTH)


class ReplacementBody(BaseAuthoringRequest):
    event_type_code: str = Field(pattern="^(" + "|".join(RECORDABLE_NARRATIVE_TYPES) + ")$")
    name: str = Field(min_length=1, max_length=EVENT_NAME_MAX_LENGTH)
    details: str | None = Field(default=None, max_length=EVENT_DETAILS_MAX_LENGTH)
    world_time_id: uuid.UUID | None = None
    character_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class CorrectEventRequest(BaseAuthoringRequest):
    reason: str = Field(min_length=1, max_length=REASON_MAX_LENGTH)
    replacement: ReplacementBody


def _jsonable(value: object) -> object:
    return str(value) if isinstance(value, uuid.UUID) else value


@router.get(_BASE)
def get_event_endpoint(event_id: uuid.UUID, access: _Edit, connection: _Conn) -> dict[str, Any]:
    view = get_event_authoring_view(connection, timeline_id=access.timeline_id, event_id=event_id)
    if view is None:
        raise NotFoundError()
    return {
        "event_id": str(view.event_id),
        "name": view.name,
        "event_type_code": view.event_type_code,
        "status": view.status,
        "world_time_id": str(view.world_time_id),
        "world_time": view.world_time,
        "session_id": None if view.session_id is None else str(view.session_id),
        # GM-only (D-3): this is the authoring read, for people who can edit canon.
        "details": view.details,
        "participants": [
            {"entity_id": str(p.entity_id), "name": p.name, "role": p.role}
            for p in view.participants
        ],
        "effects": [
            {
                "component": e.component,
                "target_entity_id": None if e.target_entity_id is None else str(e.target_entity_id),
                "previous": _jsonable(e.previous),
                "new": _jsonable(e.new),
                "application_status": e.application_status,
            }
            for e in view.effects
        ],
        "correction": (
            None
            if view.correction is None
            else {
                "kind": view.correction.kind,
                "reason": view.correction.reason,
                "correcting_event_id": str(view.correction.correcting_event_id),
                "replacement_event_id": (
                    None
                    if view.correction.replacement_event_id is None
                    else str(view.correction.replacement_event_id)
                ),
            }
        ),
        "corrects_event_id": None
        if view.corrects_event_id is None
        else str(view.corrects_event_id),
    }


@router.get(_BASE + "/correction-preview")
def correction_preview_endpoint(
    event_id: uuid.UUID, access: _Edit, connection: _Conn
) -> dict[str, Any]:
    try:
        assessment = assess_event(connection, timeline_id=access.timeline_id, event_id=event_id)
    except EventNotFoundError as exc:
        raise NotFoundError() from exc
    return {
        "event_id": str(assessment.event_id),
        "status": assessment.status,
        "can_correct": assessment.can_correct,
        "is_correction": assessment.event_type_code == "administrative_correction",
        "effects": [
            {
                "component": e.component,
                "target_entity_id": None if e.target_entity_id is None else str(e.target_entity_id),
                "reversible": e.reversible,
                "reason": e.reason,
            }
            for e in assessment.effects
        ],
    }


def _run(
    *,
    command_name: str,
    access: AccessContext,
    connection: Connection,
    idempotency_key: str | None,
    correlation_id: str | None,
    payload: dict[str, Any],
    command: Any,
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
    result: CorrectionResult = command()
    common = {
        "world_id": result.world_id,
        "actor_user_id": access.user_id,
        "correlation_id": correlation_id,
        "command_name": command_name,
    }
    record_change_log(
        connection,
        change_action_code="status_changed",
        schema_name="narrative",
        table_name="events",
        record_id=result.event_id,
        entity_id=result.event_id,
        event_id=result.correcting_event_id,
        previous_status="recorded",
        new_status=result.new_status,
        changed_fields={"event_status": result.changed_fields["event_status"]},
        **common,  # type: ignore[arg-type]
    )
    record_change_log(
        connection,
        change_action_code="created",
        schema_name="narrative",
        table_name="event_corrections",
        record_id=result.correction_id,
        entity_id=result.event_id,
        event_id=result.correcting_event_id,
        changed_fields={
            k: v for k, v in result.changed_fields.items() if k in ("correction_kind", "reason")
        },
        **common,  # type: ignore[arg-type]
    )
    receipt: dict[str, Any] = {
        "event_id": str(result.event_id),
        "status": result.new_status,
        "correction_id": str(result.correction_id),
        "correcting_event_id": str(result.correcting_event_id),
    }
    if result.replacement_event_id is not None:
        receipt["replacement_event_id"] = str(result.replacement_event_id)
    finish_campaign_idempotency(connection, idem, status_code=200, body=receipt)
    return JSONResponse(status_code=200, content=receipt)


@router.post(_BASE + "/void")
def void_event_endpoint(
    event_id: uuid.UUID,
    body: VoidEventRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="void_event",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"event_id": str(event_id), **body.model_dump(mode="json")},
        command=lambda: void_event(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            event_id=event_id,
            reason=body.reason,
        ),
    )


@router.post(_BASE + "/correct")
def correct_event_endpoint(
    event_id: uuid.UUID,
    body: CorrectEventRequest,
    access: _Edit,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="correct_event",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"event_id": str(event_id), **body.model_dump(mode="json")},
        command=lambda: correct_event(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            event_id=event_id,
            reason=body.reason,
            replacement={
                "event_type_code": body.replacement.event_type_code,
                "name": body.replacement.name,
                "details": body.replacement.details,
                "world_time_id": body.replacement.world_time_id,
                "character_ids": tuple(body.replacement.character_ids),
            },
        ),
    )
