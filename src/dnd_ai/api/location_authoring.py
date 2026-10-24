"""Typed Location authoring endpoints (Phase 15.1, ADR 0015).

    GET  /campaigns/{campaign_id}/authoring/locations/options
    GET  /campaigns/{campaign_id}/authoring/locations/parent-options
    POST /campaigns/{campaign_id}/authoring/locations
    GET  /campaigns/{campaign_id}/authoring/locations/{location_id}
    POST /campaigns/{campaign_id}/authoring/locations/{location_id}/update

Every route requires `canon.edit` in the campaign, checked by the dependency
**before** anything is resolved (a player learns nothing about which ids exist)
and re-checked under lock by the command. Foundry and machine principals are
rejected (`allow_foundry_access=False`). The world is derived from the
campaign; no request carries a world, timeline, or entity type. Mutations take
an `Idempotency-Key` (campaign-scoped store); one audit row per real change;
nothing is audited on a no-op or a replay. Request bodies are strict: unknown
fields are a 422.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection

from dnd_ai.commands._content import ContentWriteResult
from dnd_ai.commands.locations import create_location, update_location
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authoring import DESCRIPTION_MAX_LENGTH, NAME_MAX_LENGTH, REASON_MAX_LENGTH
from dnd_ai.domain.content_authoring import (
    POPULATION_MAX,
    SHORT_TEXT_MAX_LENGTH,
    LocationCategory,
)
from dnd_ai.queries.location_authoring import (
    LocationAuthoringView,
    get_location_authoring,
    list_location_categories,
    list_location_parent_options,
)

from ._authoring import (
    BaseAuthoringRequest,
    finish_campaign_idempotency,
    start_campaign_idempotency,
)
from ._content_support import audit_content_write, clean_note, write_receipt
from ._shared import timeline_world_id
from .access import require_campaign_capability
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .errors import InvalidCursorError, NotFoundError
from .pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, build_page, decode_typed_cursor

router = APIRouter(tags=["location-authoring"])

_BASE = "/campaigns/{campaign_id}/authoring/locations"
_PARENT_KEYSET = "location_parent_options"
_CAPABILITY = "canon.edit"

_Access = Annotated[AccessContext, Depends(require_campaign_capability(_CAPABILITY))]
_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]


class _LocationFields(BaseAuthoringRequest):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    summary: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    parent_location_id: uuid.UUID | None = None
    population: int | None = Field(default=None, ge=0, le=POPULATION_MAX)
    building_use: str | None = Field(default=None, max_length=SHORT_TEXT_MAX_LENGTH)


class CreateLocationRequest(_LocationFields):
    category: str = Field(min_length=1, max_length=64)


class UpdateLocationRequest(_LocationFields):
    expected_row_version: int = Field(ge=1)
    change_note: str | None = Field(default=None, max_length=REASON_MAX_LENGTH)


def _category_json(category: LocationCategory) -> dict[str, Any]:
    return {
        "code": category.code,
        "label": category.label,
        "fields": [
            {
                "name": f.name,
                "kind": f.kind,
                "label": f.label,
                "max_length": f.max_length,
                "minimum": f.minimum,
                "maximum": f.maximum,
            }
            for f in category.fields
        ],
    }


def _view_json(view: LocationAuthoringView, *, changed: bool | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "location_id": str(view.location_id),
        "name": view.name,
        "summary": view.summary,
        "category": {"code": view.category.code, "label": view.category.label},
        "parent": (
            None
            if view.parent is None
            else {
                "location_id": str(view.parent.location_id),
                "name": view.parent.name,
                "canon_status": view.parent.canon_status,
                "lifecycle_status": view.parent.lifecycle_status,
            }
        ),
        "population": view.population,
        "building_use": view.building_use,
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


@router.get(_BASE + "/options")
def location_options_endpoint(access: _Access) -> dict[str, Any]:
    del access  # authorization is the dependency's job
    return {
        "can_create": True,
        "categories": [_category_json(c) for c in list_location_categories()],
        "limits": {
            "name_max_length": NAME_MAX_LENGTH,
            "summary_max_length": DESCRIPTION_MAX_LENGTH,
            "change_note_max_length": REASON_MAX_LENGTH,
        },
    }


@router.get(_BASE + "/parent-options")
def location_parent_options_endpoint(
    access: _Access,
    connection: _Conn,
    for_location: Annotated[uuid.UUID | None, Query(alias="for")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
) -> dict[str, Any]:
    world_id = timeline_world_id(connection, access.timeline_id)
    decoded = decode_typed_cursor(cursor, keyset=_PARENT_KEYSET, fields=["str", "uuid"])
    after: tuple[str, uuid.UUID] | None = None
    if decoded is not None:
        after_name, after_id = decoded
        if not isinstance(after_name, str) or not isinstance(after_id, uuid.UUID):
            raise InvalidCursorError()
        after = (after_name, after_id)
    rows = list_location_parent_options(
        connection,
        world_id=world_id,
        for_location_id=for_location,
        query_text=q.strip() if q and q.strip() else None,
        limit=limit,
        after=after,
    )
    page = build_page(
        rows, limit=limit, keyset=_PARENT_KEYSET, cursor_key=lambda r: (r.name_sort, r.location_id)
    )
    return {
        "items": [
            {
                "location_id": str(r.location_id),
                "name": r.name,
                "category": {"code": r.category.code, "label": r.category.label},
                "canon_status": r.canon_status,
            }
            for r in page.items
        ],
        "next_cursor": page.next_cursor,
    }


@router.post(_BASE, status_code=201)
def create_location_endpoint(
    body: CreateLocationRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    command_name = "create_location"
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
    result = create_location(
        connection,
        campaign_id=access.campaign_id,
        actor_user_id=access.user_id,
        category_code=body.category,
        name=body.name,
        summary=body.summary,
        parent_location_id=body.parent_location_id,
        population=body.population,
        building_use=body.building_use,
    )
    audit_content_write(
        connection,
        result=result,
        command_name=command_name,
        access=access,
        correlation_id=correlation_id,
        reason=None,
        view_loader=lambda: get_location_authoring(
            connection, world_id=result.world_id, location_id=result.entity_id
        ),
    )
    response = _response(connection, result, changed=True)
    finish_campaign_idempotency(connection, idem, status_code=201, body=response)
    return JSONResponse(status_code=201, content=response)


@router.get(_BASE + "/{location_id}")
def get_location_authoring_endpoint(
    location_id: uuid.UUID, access: _Access, connection: _Conn
) -> dict[str, Any]:
    world_id = timeline_world_id(connection, access.timeline_id)
    view = get_location_authoring(connection, world_id=world_id, location_id=location_id)
    if view is None:
        raise NotFoundError()
    return _view_json(view)


@router.post(_BASE + "/{location_id}/update")
def update_location_endpoint(
    location_id: uuid.UUID,
    body: UpdateLocationRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    command_name = "update_location"
    idem = start_campaign_idempotency(
        connection,
        actor_user_id=access.user_id,
        campaign_id=access.campaign_id,
        idempotency_key=idempotency_key,
        command_name=command_name,
        payload={"location_id": str(location_id), **body.model_dump(mode="json")},
        correlation_id=correlation_id,
    )
    if idem.replay is not None:
        return idem.replay
    result = update_location(
        connection,
        campaign_id=access.campaign_id,
        location_id=location_id,
        actor_user_id=access.user_id,
        expected_row_version=body.expected_row_version,
        name=body.name,
        summary=body.summary,
        parent_location_id=body.parent_location_id,
        population=body.population,
        building_use=body.building_use,
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
            view_loader=lambda: get_location_authoring(
                connection, world_id=result.world_id, location_id=result.entity_id
            ),
        )
    response = _response(connection, result, changed=result.changed)
    finish_campaign_idempotency(connection, idem, status_code=200, body=response)
    return response


def _response(
    connection: Connection, result: ContentWriteResult, *, changed: bool
) -> dict[str, Any]:
    del connection
    return write_receipt(result, "location_id", changed=changed)
