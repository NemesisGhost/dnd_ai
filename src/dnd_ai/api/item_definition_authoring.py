"""Item definition authoring endpoints (Phase 15 checkpoint 15.3B-1a, decision D-22).

    GET  /campaigns/{id}/authoring/item-definitions[?category=&homebrew=true]
    GET  /campaigns/{id}/authoring/item-definitions/options
    GET  /campaigns/{id}/authoring/item-definitions/{definition_id}
    POST /campaigns/{id}/authoring/item-definitions
    POST /campaigns/{id}/authoring/item-definitions/{definition_id}/update

All `canon.edit`. The list shows the ruleset-wide generic definitions and the homebrew this
world owns, never another world's; only homebrew is editable. An update carries the definition
`row_version` it read.
"""

import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection

from dnd_ai.commands.item_definitions import (
    DefinitionResult,
    create_item_definition,
    update_item_definition,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.item_definition_authoring import (
    CANON_STATES,
    DESCRIPTION_MAX_LENGTH,
    NAME_MAX_LENGTH,
    RARITIES,
)
from dnd_ai.queries.item_definitions import (
    ItemDefinitionView,
    get_item_definition,
    list_item_categories,
    list_item_definitions,
)

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
from .errors import NotFoundError

router = APIRouter(tags=["item-definitions"])

_BASE = "/campaigns/{campaign_id}/authoring/item-definitions"
_Access = Annotated[AccessContext, Depends(require_campaign_capability("canon.edit"))]
_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]


class DefinitionFields(BaseAuthoringRequest):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    category: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    rarity: str = Field(default="common", max_length=20)
    requires_attunement: bool = False
    weight: Decimal | None = Field(default=None, ge=0)
    base_cost_gp: Decimal | None = Field(default=None, ge=0)
    canon_status: str = Field(default="draft", max_length=20)


class UpdateDefinitionRequest(DefinitionFields):
    expected_row_version: int = Field(ge=1)


def _number(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _view_json(view: ItemDefinitionView) -> dict[str, Any]:
    return {
        "item_definition_id": str(view.item_definition_id),
        "code": view.code,
        "name": view.name,
        "category": view.category,
        "category_label": view.category_label,
        "description": view.description,
        "rarity": view.rarity,
        "requires_attunement": view.requires_attunement,
        "weight": _number(view.weight),
        "base_cost_gp": _number(view.base_cost_gp),
        "canon_status": view.canon_status,
        "row_version": view.row_version,
        "is_homebrew": view.is_homebrew,
        "can_edit": view.is_homebrew,
    }


@router.get(_BASE)
def list_endpoint(
    access: _Access,
    connection: _Conn,
    category: Annotated[str | None, Query(max_length=100)] = None,
    homebrew: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    items = list_item_definitions(
        connection,
        campaign_id=access.campaign_id,
        world_id=timeline_world_id(connection, access.timeline_id),
        category=category,
        homebrew_only=homebrew,
    )
    return {"items": [_view_json(item) for item in items]}


@router.get(_BASE + "/options", dependencies=[Depends(require_campaign_capability("canon.edit"))])
def options_endpoint(connection: _Conn) -> dict[str, Any]:
    return {
        "categories": [
            {"value": code, "label": label} for code, label in list_item_categories(connection)
        ],
        "rarities": [{"value": code, "label": label} for code, label in RARITIES],
        "canon_states": [{"value": code, "label": label} for code, label in CANON_STATES],
        "limits": {
            "name_max_length": NAME_MAX_LENGTH,
            "description_max_length": DESCRIPTION_MAX_LENGTH,
        },
    }


@router.get(_BASE + "/{definition_id}")
def get_endpoint(definition_id: uuid.UUID, access: _Access, connection: _Conn) -> dict[str, Any]:
    view = get_item_definition(
        connection,
        campaign_id=access.campaign_id,
        world_id=timeline_world_id(connection, access.timeline_id),
        item_definition_id=definition_id,
    )
    if view is None:
        raise NotFoundError()
    return _view_json(view)


def _respond(
    connection: Connection,
    *,
    access: AccessContext,
    result: DefinitionResult,
    command_name: str,
    correlation_id: str | None,
    status_code: int,
    idem: Any,
) -> Any:
    if result.changed:
        record_change_log(
            connection,
            change_action_code="created" if result.created else "updated",
            schema_name="rules",
            table_name="item_definitions",
            record_id=result.item_definition_id,
            entity_id=None,
            world_id=result.world_id,
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=command_name,
            event_id=None,
            changed_fields=result.changed_fields or None,
        )
    view = get_item_definition(
        connection,
        campaign_id=access.campaign_id,
        world_id=result.world_id,
        item_definition_id=result.item_definition_id,
    )
    if view is None:
        raise NotFoundError()
    response = {**_view_json(view), "created": result.created, "changed": result.changed}
    finish_campaign_idempotency(connection, idem, status_code=status_code, body=response)
    return JSONResponse(status_code=status_code, content=response)


@router.post(_BASE, status_code=201)
def create_endpoint(
    body: DefinitionFields,
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
        command_name="create_item_definition",
        payload=body.model_dump(mode="json"),
        correlation_id=correlation_id,
    )
    if idem.replay is not None:
        return idem.replay
    result = create_item_definition(
        connection,
        campaign_id=access.campaign_id,
        actor_user_id=access.user_id,
        name=body.name,
        category=body.category,
        description=body.description,
        rarity=body.rarity,
        requires_attunement=body.requires_attunement,
        weight=body.weight,
        base_cost_gp=body.base_cost_gp,
        canon_status=body.canon_status,
    )
    return _respond(
        connection,
        access=access,
        result=result,
        command_name="create_item_definition",
        correlation_id=correlation_id,
        status_code=201,
        idem=idem,
    )


@router.post(_BASE + "/{definition_id}/update")
def update_endpoint(
    definition_id: uuid.UUID,
    body: UpdateDefinitionRequest,
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
        command_name="update_item_definition",
        payload={"item_definition_id": str(definition_id), **body.model_dump(mode="json")},
        correlation_id=correlation_id,
    )
    if idem.replay is not None:
        return idem.replay
    result = update_item_definition(
        connection,
        campaign_id=access.campaign_id,
        actor_user_id=access.user_id,
        item_definition_id=definition_id,
        expected_row_version=body.expected_row_version,
        name=body.name,
        category=body.category,
        description=body.description,
        rarity=body.rarity,
        requires_attunement=body.requires_attunement,
        weight=body.weight,
        base_cost_gp=body.base_cost_gp,
        canon_status=body.canon_status,
    )
    return _respond(
        connection,
        access=access,
        result=result,
        command_name="update_item_definition",
        correlation_id=correlation_id,
        status_code=200,
        idem=idem,
    )
