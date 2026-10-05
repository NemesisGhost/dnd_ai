"""Knowledge-item definition authoring endpoints (Phase 15.1, ADR 0015).

    GET  /campaigns/{campaign_id}/authoring/knowledge/options
    GET  /campaigns/{campaign_id}/authoring/knowledge/subject-options
    POST /campaigns/{campaign_id}/authoring/knowledge
    GET  /campaigns/{campaign_id}/authoring/knowledge/{knowledge_item_id}
    POST /campaigns/{campaign_id}/authoring/knowledge/{knowledge_item_id}/update

Same contract as the other typed content routes (`dnd_ai.api.location_authoring`).
These write the *claim* only; who knows it is per-knower state (Phase 15.2).
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection

from dnd_ai.commands._content import ContentWriteResult
from dnd_ai.commands.knowledge_definitions import create_knowledge_item, update_knowledge_item
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authoring import REASON_MAX_LENGTH
from dnd_ai.domain.knowledge_authoring import (
    KNOWLEDGE_SUBJECT_TYPE_CODES,
    SENSITIVITIES,
    STATEMENT_MAX_LENGTH,
)
from dnd_ai.queries.knowledge_authoring import (
    KnowledgeAuthoringView,
    get_knowledge_authoring,
    list_knowledge_catalogs,
)
from dnd_ai.queries.reference_options import list_reference_options

from ._authoring import (
    BaseAuthoringRequest,
    finish_campaign_idempotency,
    start_campaign_idempotency,
)
from ._content_support import (
    audit_content_write,
    clean_note,
    decode_name_cursor,
    reference_options_page,
    write_receipt,
)
from ._shared import timeline_world_id
from .access import require_campaign_capability
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .errors import NotFoundError
from .pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(tags=["knowledge-authoring"])

_BASE = "/campaigns/{campaign_id}/authoring/knowledge"
_CAPABILITY = "canon.edit"

_Access = Annotated[AccessContext, Depends(require_campaign_capability(_CAPABILITY))]
_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]


class _KnowledgeFields(BaseAuthoringRequest):
    statement: str = Field(min_length=1, max_length=STATEMENT_MAX_LENGTH)
    knowledge_type: str = Field(min_length=1, max_length=64)
    truth_status: str = Field(min_length=1, max_length=64)
    sensitivity: str = Field(min_length=1, max_length=32)
    subject_entity_id: uuid.UUID | None = None


class CreateKnowledgeRequest(_KnowledgeFields):
    pass


class UpdateKnowledgeRequest(_KnowledgeFields):
    expected_row_version: int = Field(ge=1)
    change_note: str | None = Field(default=None, max_length=REASON_MAX_LENGTH)


def _view_json(view: KnowledgeAuthoringView, *, changed: bool | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "knowledge_item_id": str(view.knowledge_item_id),
        "statement": view.statement,
        "knowledge_type": view.knowledge_type,
        "truth_status": view.truth_status,
        "sensitivity": view.sensitivity,
        "subject": (
            None
            if view.subject is None
            else {
                "entity_id": str(view.subject.entity_id),
                "name": view.subject.name,
                "canon_status": view.subject.canon_status,
                "lifecycle_status": view.subject.lifecycle_status,
            }
        ),
        "in_use": view.in_use,
        "canon_status": view.canon_status,
        "lifecycle_status": view.lifecycle_status,
        "row_version": view.row_version,
        "available_actions": view.available_actions,
        "blocked_actions": [{"action": b.action, "reason": b.reason} for b in view.blocked_actions],
        "field_locks": view.field_locks,
    }
    if changed is not None:
        body["changed"] = changed
    return body


def _response(
    connection: Connection, result: ContentWriteResult, *, changed: bool
) -> dict[str, Any]:
    del connection
    return write_receipt(result, "knowledge_item_id", changed=changed)


@router.get(_BASE + "/options")
def knowledge_options_endpoint(access: _Access, connection: _Conn) -> dict[str, Any]:
    del access
    types, truths = list_knowledge_catalogs(connection)
    return {
        "can_create": True,
        "knowledge_types": [{"value": c, "label": label} for c, label in types],
        "truth_statuses": [{"value": c, "label": label} for c, label in truths],
        "sensitivities": [{"value": c, "label": label} for c, label in SENSITIVITIES],
        "limits": {
            "statement_max_length": STATEMENT_MAX_LENGTH,
            "change_note_max_length": REASON_MAX_LENGTH,
        },
    }


@router.get(_BASE + "/subject-options")
def knowledge_subject_options_endpoint(
    access: _Access,
    connection: _Conn,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
) -> dict[str, Any]:
    keyset = "knowledge_subject_options"
    rows = list_reference_options(
        connection,
        world_id=timeline_world_id(connection, access.timeline_id),
        type_codes=KNOWLEDGE_SUBJECT_TYPE_CODES,
        query_text=q.strip() if q and q.strip() else None,
        limit=limit,
        after=decode_name_cursor(cursor, keyset),
    )
    return reference_options_page(
        rows,
        limit=limit,
        keyset=keyset,
        item=lambda r: {
            "entity_id": str(r.entity_id),
            "name": r.name,
            "kind": r.entity_type_code,
            "canon_status": r.canon_status,
        },
    )


@router.post(_BASE, status_code=201)
def create_knowledge_endpoint(
    body: CreateKnowledgeRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    command_name = "create_knowledge_item"
    idem = start_campaign_idempotency(
        connection,
        actor_user_id=access.user_id,
        campaign_id=access.campaign_id,
        idempotency_key=idempotency_key,
        command_name=command_name,
        payload=body.model_dump(mode="json"),
        correlation_id=correlation_id,
    )
    if idem.replay is not None:
        return idem.replay
    result = create_knowledge_item(
        connection,
        campaign_id=access.campaign_id,
        actor_user_id=access.user_id,
        statement=body.statement,
        knowledge_type=body.knowledge_type,
        truth_status=body.truth_status,
        sensitivity=body.sensitivity,
        subject_entity_id=body.subject_entity_id,
    )
    audit_content_write(
        connection,
        result=result,
        command_name=command_name,
        access=access,
        correlation_id=correlation_id,
        reason=None,
    )
    response = _response(connection, result, changed=True)
    finish_campaign_idempotency(connection, idem, status_code=201, body=response)
    return JSONResponse(status_code=201, content=response)


@router.get(_BASE + "/{knowledge_item_id}")
def get_knowledge_authoring_endpoint(
    knowledge_item_id: uuid.UUID, access: _Access, connection: _Conn
) -> dict[str, Any]:
    view = get_knowledge_authoring(
        connection,
        world_id=timeline_world_id(connection, access.timeline_id),
        knowledge_item_id=knowledge_item_id,
    )
    if view is None:
        raise NotFoundError()
    return _view_json(view)


@router.post(_BASE + "/{knowledge_item_id}/update")
def update_knowledge_endpoint(
    knowledge_item_id: uuid.UUID,
    body: UpdateKnowledgeRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    command_name = "update_knowledge_item"
    idem = start_campaign_idempotency(
        connection,
        actor_user_id=access.user_id,
        campaign_id=access.campaign_id,
        idempotency_key=idempotency_key,
        command_name=command_name,
        payload={"knowledge_item_id": str(knowledge_item_id), **body.model_dump(mode="json")},
        correlation_id=correlation_id,
    )
    if idem.replay is not None:
        return idem.replay
    result = update_knowledge_item(
        connection,
        campaign_id=access.campaign_id,
        knowledge_item_id=knowledge_item_id,
        actor_user_id=access.user_id,
        expected_row_version=body.expected_row_version,
        statement=body.statement,
        knowledge_type=body.knowledge_type,
        truth_status=body.truth_status,
        sensitivity=body.sensitivity,
        subject_entity_id=body.subject_entity_id,
        change_note=body.change_note,
    )
    if result.changed:
        audit_content_write(
            connection,
            result=result,
            command_name=command_name,
            access=access,
            correlation_id=correlation_id,
            reason=clean_note(body.change_note),
        )
    response = _response(connection, result, changed=result.changed)
    finish_campaign_idempotency(connection, idem, status_code=200, body=response)
    return response
