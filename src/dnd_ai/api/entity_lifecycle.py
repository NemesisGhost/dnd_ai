"""Shared canon-lifecycle endpoints (Phase 14).

    GET  /campaigns/{campaign_id}/entities/{entity_id}/lifecycle
    GET  /campaigns/{campaign_id}/entities/{entity_id}/lifecycle/replacement-candidates
    POST /campaigns/{campaign_id}/entities/{entity_id}/lifecycle/submit-for-review
    POST …/return-to-draft | approve | reject | publish | supersede | archive | restore | delete-draft

Every route requires `canon.edit` in the campaign, checked by the dependency
**before** the entity is resolved (so a player learns nothing about which
entities exist) and re-checked under lock by the command; Foundry principals are
rejected. An entity of another world is the same 404 as a missing one. The
creator of a draft gets no authority from having created it. Campaign-scoped
idempotency; one audit row per durable record (`status_changed` carries the
previous and new canon codes, `archived`/`restored` the lifecycle codes, and
`deleted` a bounded `{canonical_name, entity_type_code}` because the row is
gone).
"""

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection

from dnd_ai.commands._revisions import REVISION_LIFECYCLE, capture_revision
from dnd_ai.commands.entity_lifecycle import (
    EntityTransitionResult,
    approve_entity,
    archive_entity,
    delete_draft_entity,
    publish_entity_as_canon,
    reject_entity,
    restore_entity,
    return_entity_to_draft,
    submit_entity_for_review,
    supersede_entity,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.entity_lifecycle import get_entity_lifecycle, list_replacement_candidates

from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .errors import InvalidCursorError, NotFoundError
from .idempotency import (
    IdempotentReplay,
    begin_idempotent_request,
    complete_idempotent_request,
)
from .pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, build_page, decode_typed_cursor

router = APIRouter(tags=["entity-lifecycle"])

_BASE = "/campaigns/{campaign_id}/entities/{entity_id}/lifecycle"
_CANDIDATE_KEYSET = "replacement_candidates"
_CAPABILITY = "canon.edit"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class VersionOnlyRequest(_Strict):
    expected_row_version: int = Field(ge=1)


class ReasonRequest(_Strict):
    expected_row_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=1000)


class RequiredReasonRequest(_Strict):
    expected_row_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class SupersedeRequest(_Strict):
    expected_row_version: int = Field(ge=1)
    replacement_entity_id: uuid.UUID
    replacement_expected_row_version: int = Field(ge=1)


@router.get(_BASE)
def get_entity_lifecycle_endpoint(
    entity_id: uuid.UUID,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_CAPABILITY))],
    connection: Annotated[Connection, Depends(get_connection)],
) -> dict[str, Any]:
    world_id = timeline_world_id(connection, access.timeline_id)
    view = get_entity_lifecycle(connection, world_id=world_id, entity_id=entity_id)
    if view is None:
        raise NotFoundError()
    return {
        "entity_id": str(view.entity_id),
        "entity_type_code": view.entity_type_code,
        "canonical_name": view.canonical_name,
        "canon_status": view.canon_status,
        "lifecycle_status": view.lifecycle_status,
        "row_version": view.row_version,
        "lifecycle_managed": view.lifecycle_managed,
        "superseded_by": (
            None
            if view.superseded_by_entity_id is None
            else {
                "entity_id": str(view.superseded_by_entity_id),
                "canonical_name": view.superseded_by_name,
            }
        ),
        "available_actions": view.available_actions,
        "blocked_actions": [{"action": b.action, "reason": b.reason} for b in view.blocked_actions],
    }


@router.get(_BASE + "/replacement-candidates")
def list_replacement_candidates_endpoint(
    entity_id: uuid.UUID,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_CAPABILITY))],
    connection: Annotated[Connection, Depends(get_connection)],
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
) -> dict[str, Any]:
    world_id = timeline_world_id(connection, access.timeline_id)
    if get_entity_lifecycle(connection, world_id=world_id, entity_id=entity_id) is None:
        raise NotFoundError()
    decoded = decode_typed_cursor(cursor, keyset=_CANDIDATE_KEYSET, fields=["str", "uuid"])
    after: tuple[str, uuid.UUID] | None = None
    if decoded is not None:
        after_name, after_id = decoded
        if not isinstance(after_name, str) or not isinstance(after_id, uuid.UUID):
            raise InvalidCursorError()
        after = (after_name, after_id)
    rows = list_replacement_candidates(
        connection,
        world_id=world_id,
        entity_id=entity_id,
        query_text=q.strip() if q and q.strip() else None,
        limit=limit,
        after=after,
    )
    page = build_page(
        rows,
        limit=limit,
        keyset=_CANDIDATE_KEYSET,
        cursor_key=lambda r: (r.name_sort, r.entity_id),
    )
    return {
        "items": [
            {
                "entity_id": str(r.entity_id),
                "canonical_name": r.canonical_name,
                "canon_status": r.canon_status,
                "row_version": r.row_version,
            }
            for r in page.items
        ],
        "next_cursor": page.next_cursor,
    }


def _audit_transition(
    connection: Connection,
    *,
    result: EntityTransitionResult,
    command_name: str,
    access: AccessContext,
    correlation_id: str | None,
    reason: str | None,
    lifecycle_action: str | None = None,
) -> None:
    """One audit row for the entity. Canon transitions record canon codes under
    `status_changed`; archive/restore record lifecycle codes; delete-draft
    records a bounded snapshot because the row no longer exists."""
    if result.deleted:
        action = "deleted"
        previous, new = None, None
    elif lifecycle_action is not None:
        action = lifecycle_action
        previous, new = result.previous_lifecycle_status, result.lifecycle_status
    else:
        action = "status_changed"
        previous, new = result.previous_canon_status, result.canon_status
    record_change_log(
        connection,
        change_action_code=action,
        schema_name="core",
        table_name="entities",
        record_id=result.entity_id,
        entity_id=None if result.deleted else result.entity_id,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=command_name,
        event_id=None,
        previous_status=previous,
        new_status=new,
        changed_fields=result.changed_fields or None,
        reason=reason,
    )
    if not result.deleted:
        # Canonical revision history (15.2R): the statuses as of this version.
        capture_revision(
            connection,
            entity_id=result.entity_id,
            world_id=result.world_id,
            row_version=result.row_version,
            kind=REVISION_LIFECYCLE,
            snapshot={
                "canon_status": result.canon_status,
                "lifecycle_status": result.lifecycle_status,
            },
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
        )


def _run(
    *,
    command_name: str,
    entity_id: uuid.UUID,
    access: AccessContext,
    connection: Connection,
    idempotency_key: str | None,
    correlation_id: str | None,
    payload: dict[str, Any],
    run: Callable[[], EntityTransitionResult],
    reason: str | None = None,
    lifecycle_action: str | None = None,
) -> Any:
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=access.campaign_id,
            idempotency_key=idempotency_key,
            command_name=command_name,
            payload={"entity_id": str(entity_id), **payload},
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return JSONResponse(
                status_code=outcome.response_status_code, content=outcome.response_body
            )
        reservation_id = outcome.idempotent_request_id

    result = run()
    _audit_transition(
        connection,
        result=result,
        command_name=command_name,
        access=access,
        correlation_id=correlation_id,
        reason=reason,
        lifecycle_action=lifecycle_action,
    )
    if result.replacement is not None:
        _audit_transition(
            connection,
            result=result.replacement,
            command_name=command_name,
            access=access,
            correlation_id=correlation_id,
            reason=None,
        )
    response: dict[str, Any]
    if result.deleted:
        response = {"entity_id": str(result.entity_id), "deleted": True}
    else:
        response = {
            "entity_id": str(result.entity_id),
            "canon_status": result.canon_status,
            "lifecycle_status": result.lifecycle_status,
            "row_version": result.row_version,
        }
    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=200,
            response_body=response,
        )
    return response


def _clean(reason: str | None) -> str | None:
    return reason.strip() if reason and reason.strip() else None


_Access = Annotated[AccessContext, Depends(require_campaign_capability(_CAPABILITY))]
_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]


@router.post(_BASE + "/submit-for-review")
def submit_for_review_endpoint(
    entity_id: uuid.UUID,
    body: VersionOnlyRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="submit_entity_for_review",
        entity_id=entity_id,
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=body.model_dump(mode="json"),
        run=lambda: submit_entity_for_review(
            connection,
            campaign_id=access.campaign_id,
            entity_id=entity_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
        ),
    )


@router.post(_BASE + "/return-to-draft")
def return_to_draft_endpoint(
    entity_id: uuid.UUID,
    body: ReasonRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="return_entity_to_draft",
        entity_id=entity_id,
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=body.model_dump(mode="json"),
        reason=_clean(body.reason),
        run=lambda: return_entity_to_draft(
            connection,
            campaign_id=access.campaign_id,
            entity_id=entity_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
            reason=body.reason,
        ),
    )


@router.post(_BASE + "/approve")
def approve_endpoint(
    entity_id: uuid.UUID,
    body: VersionOnlyRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="approve_entity",
        entity_id=entity_id,
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=body.model_dump(mode="json"),
        run=lambda: approve_entity(
            connection,
            campaign_id=access.campaign_id,
            entity_id=entity_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
        ),
    )


@router.post(_BASE + "/reject")
def reject_endpoint(
    entity_id: uuid.UUID,
    body: ReasonRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="reject_entity",
        entity_id=entity_id,
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=body.model_dump(mode="json"),
        reason=_clean(body.reason),
        run=lambda: reject_entity(
            connection,
            campaign_id=access.campaign_id,
            entity_id=entity_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
            reason=body.reason,
        ),
    )


@router.post(_BASE + "/publish")
def publish_endpoint(
    entity_id: uuid.UUID,
    body: VersionOnlyRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="publish_entity_as_canon",
        entity_id=entity_id,
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=body.model_dump(mode="json"),
        run=lambda: publish_entity_as_canon(
            connection,
            campaign_id=access.campaign_id,
            entity_id=entity_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
        ),
    )


@router.post(_BASE + "/supersede")
def supersede_endpoint(
    entity_id: uuid.UUID,
    body: SupersedeRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="supersede_entity",
        entity_id=entity_id,
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=body.model_dump(mode="json"),
        run=lambda: supersede_entity(
            connection,
            campaign_id=access.campaign_id,
            entity_id=entity_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
            replacement_entity_id=body.replacement_entity_id,
            replacement_expected_row_version=body.replacement_expected_row_version,
        ),
    )


@router.post(_BASE + "/archive")
def archive_endpoint(
    entity_id: uuid.UUID,
    body: ReasonRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="archive_entity",
        entity_id=entity_id,
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=body.model_dump(mode="json"),
        reason=_clean(body.reason),
        lifecycle_action="archived",
        run=lambda: archive_entity(
            connection,
            campaign_id=access.campaign_id,
            entity_id=entity_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
            reason=body.reason,
        ),
    )


@router.post(_BASE + "/restore")
def restore_endpoint(
    entity_id: uuid.UUID,
    body: RequiredReasonRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="restore_entity",
        entity_id=entity_id,
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=body.model_dump(mode="json"),
        reason=_clean(body.reason),
        lifecycle_action="restored",
        run=lambda: restore_entity(
            connection,
            campaign_id=access.campaign_id,
            entity_id=entity_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
            reason=body.reason,
        ),
    )


@router.post(_BASE + "/delete-draft")
def delete_draft_endpoint(
    entity_id: uuid.UUID,
    body: RequiredReasonRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="delete_draft_entity",
        entity_id=entity_id,
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=body.model_dump(mode="json"),
        reason=_clean(body.reason),
        run=lambda: delete_draft_entity(
            connection,
            campaign_id=access.campaign_id,
            entity_id=entity_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
            reason=body.reason,
        ),
    )
