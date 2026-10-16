"""Item instance authoring, item runtime operations and party inventory (Phase 15 checkpoint 15.3B-1b).

    GET  /campaigns/{id}/authoring/items
    GET  /campaigns/{id}/authoring/items/options
    GET  /campaigns/{id}/authoring/items/{item_id}
    POST /campaigns/{id}/authoring/items
    POST /campaigns/{id}/authoring/items/{item_id}/update

    POST /campaigns/{id}/items/{item_id}/award          (a placed item is refused)
    POST /campaigns/{id}/items/{item_id}/equip | unequip
    POST /campaigns/{id}/items/{item_id}/consume | damage | repair | destroy
    POST /campaigns/{id}/items/{item_id}/attune | end-attunement
    GET  /campaigns/{id}/parties/{party_id}/inventory

(`/items/{item_id}/transfer` and `/identify` are in `api.items`.) All `canon.edit`. An item is a
lifecycle-managed definition (draft until published); every operation needs it published, takes
the item's last-event-seen token (`expected_last_event_id`, `null` when the item has no state
yet), records one event, and runs on the campaign idempotency store with one audit row.
"""

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection

from dnd_ai.commands.item_instances import create_item_instance, update_item_instance
from dnd_ai.commands.item_operations import (
    ItemOperationResult,
    attune_item,
    award_item,
    consume_item,
    damage_item,
    destroy_item,
    end_item_attunement,
    equip_item,
    repair_item,
    unequip_item,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authoring import DESCRIPTION_MAX_LENGTH, NAME_MAX_LENGTH, REASON_MAX_LENGTH
from dnd_ai.domain.item_runtime import ORIGIN_NOTES_MAX_LENGTH, QUANTITY_MAX
from dnd_ai.queries.inventory import get_inventory_view
from dnd_ai.queries.item_authoring import (
    ItemAuthoringView,
    Reference,
    get_item_authoring,
    list_item_instances,
)
from dnd_ai.queries.item_definitions import list_item_definitions
from dnd_ai.queries.parties import get_campaign_party
from dnd_ai.queries.party_members import list_party_members

from ._authoring import (
    BaseAuthoringRequest,
    finish_campaign_idempotency,
    start_campaign_idempotency,
)
from ._content_support import audit_content_write
from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .errors import NotFoundError

router = APIRouter(tags=["items"])

_AUTHORING = "/campaigns/{campaign_id}/authoring/items"
_RUNTIME = "/campaigns/{campaign_id}/items/{item_instance_id}"
_Access = Annotated[AccessContext, Depends(require_campaign_capability("canon.edit"))]
_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]


class CreateItemRequest(BaseAuthoringRequest):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    summary: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    item_definition_id: uuid.UUID
    origin_notes: str | None = Field(default=None, max_length=ORIGIN_NOTES_MAX_LENGTH)


class UpdateItemRequest(BaseAuthoringRequest):
    expected_row_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    summary: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    origin_notes: str | None = Field(default=None, max_length=ORIGIN_NOTES_MAX_LENGTH)
    change_note: str | None = Field(default=None, max_length=REASON_MAX_LENGTH)


class OperationBase(BaseAuthoringRequest):
    # The event the caller last saw for this item; `null` when it had no state yet.
    expected_last_event_id: uuid.UUID | None
    world_time_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)


class AwardRequest(OperationBase):
    holder_entity_id: uuid.UUID
    quantity: int = Field(default=1, ge=1, le=QUANTITY_MAX)
    set_owner: bool = True


class AmountRequest(OperationBase):
    amount: int = Field(default=1, ge=1, le=QUANTITY_MAX)


class AttuneRequest(OperationBase):
    character_id: uuid.UUID


def _reference_json(ref: Reference | None) -> dict[str, Any] | None:
    if ref is None:
        return None
    return {
        "entity_id": str(ref.entity_id),
        "name": ref.name,
        "entity_type_code": ref.entity_type_code,
    }


def _view_json(view: ItemAuthoringView, *, changed: bool | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "item_instance_id": str(view.item_instance_id),
        "name": view.name,
        "summary": view.summary,
        "origin_notes": view.origin_notes,
        "item_definition_id": str(view.item_definition_id),
        "definition_name": view.definition_name,
        "category": view.category,
        "category_label": view.category_label,
        "rarity": view.rarity,
        "requires_attunement": view.requires_attunement,
        "weight": None if view.weight is None else float(view.weight),
        "canon_status": view.canon_status,
        "lifecycle_status": view.lifecycle_status,
        "row_version": view.row_version,
        "is_container": view.is_container,
        "quantity": view.quantity,
        "condition_percentage": view.condition_percentage,
        "is_equipped": view.is_equipped,
        "is_destroyed": view.is_destroyed,
        "last_event_id": None if view.last_event_id is None else str(view.last_event_id),
        "holder": _reference_json(view.holder),
        "container": _reference_json(view.container),
        "location": _reference_json(view.location),
        "owner": _reference_json(view.owner),
        "attuned_to": _reference_json(view.attuned_to),
        "available_actions": view.available_actions,
        "blocked_actions": [{"action": b.action, "reason": b.reason} for b in view.blocked_actions],
        "can_operate": view.canon_status == "canon" and view.lifecycle_status == "active",
    }
    if changed is not None:
        body["changed"] = changed
    return body


def _load_view(
    connection: Connection, access: AccessContext, item_id: uuid.UUID
) -> ItemAuthoringView:
    view = get_item_authoring(
        connection,
        world_id=timeline_world_id(connection, access.timeline_id),
        timeline_id=access.timeline_id,
        item_instance_id=item_id,
    )
    if view is None:
        raise NotFoundError()
    return view


# --- reads -------------------------------------------------------------------------------------


@router.get(_AUTHORING)
def list_items_endpoint(access: _Access, connection: _Conn) -> dict[str, Any]:
    items = list_item_instances(
        connection,
        world_id=timeline_world_id(connection, access.timeline_id),
        timeline_id=access.timeline_id,
    )
    return {
        "items": [
            {
                "item_instance_id": str(i.item_instance_id),
                "name": i.name,
                "definition_name": i.definition_name,
                "category_label": i.category_label,
                "canon_status": i.canon_status,
                "lifecycle_status": i.lifecycle_status,
                "holder_name": i.holder_name,
                "is_destroyed": i.is_destroyed,
            }
            for i in items
        ]
    }


@router.get(_AUTHORING + "/options")
def item_options_endpoint(access: _Access, connection: _Conn) -> dict[str, Any]:
    definitions = [
        d
        for d in list_item_definitions(
            connection,
            campaign_id=access.campaign_id,
            world_id=timeline_world_id(connection, access.timeline_id),
        )
        if d.canon_status == "canon"
    ]
    return {
        "can_create": True,
        "definitions": [
            {
                "value": str(d.item_definition_id),
                "label": f"{d.name} ({d.category_label})",
                "category": d.category,
            }
            for d in definitions
        ],
        "limits": {
            "name_max_length": NAME_MAX_LENGTH,
            "summary_max_length": DESCRIPTION_MAX_LENGTH,
            "origin_notes_max_length": ORIGIN_NOTES_MAX_LENGTH,
            "change_note_max_length": REASON_MAX_LENGTH,
            "quantity_max": QUANTITY_MAX,
        },
    }


@router.get(_AUTHORING + "/{item_instance_id}")
def get_item_endpoint(item_instance_id: uuid.UUID, access: _Access, connection: _Conn) -> Any:
    return _view_json(_load_view(connection, access, item_instance_id))


# --- authoring writes ------------------------------------------------------------------------------


def _authoring_write(
    *,
    command_name: str,
    access: AccessContext,
    connection: Connection,
    idempotency_key: str | None,
    correlation_id: str | None,
    payload: dict[str, Any],
    created: bool,
    reason: str | None,
    command: Callable[[], Any],
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
    result = command()
    if result.changed:
        audit_content_write(
            connection,
            result=result,
            command_name=command_name,
            access=access,
            correlation_id=correlation_id,
            reason=reason,
            view_loader=lambda: _load_view(connection, access, result.entity_id),
        )
    response = _view_json(_load_view(connection, access, result.entity_id), changed=result.changed)
    status = 201 if created else 200
    finish_campaign_idempotency(connection, idem, status_code=status, body=response)
    return JSONResponse(status_code=status, content=response) if created else response


@router.post(_AUTHORING, status_code=201)
def create_item_endpoint(
    body: CreateItemRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _authoring_write(
        command_name="create_item_instance",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=body.model_dump(mode="json"),
        created=True,
        reason=None,
        command=lambda: create_item_instance(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            name=body.name,
            summary=body.summary,
            item_definition_id=body.item_definition_id,
            origin_notes=body.origin_notes,
        ),
    )


@router.post(_AUTHORING + "/{item_instance_id}/update")
def update_item_endpoint(
    item_instance_id: uuid.UUID,
    body: UpdateItemRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _authoring_write(
        command_name="update_item_instance",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"item_instance_id": str(item_instance_id), **body.model_dump(mode="json")},
        created=False,
        reason=(body.change_note or "").strip() or None,
        command=lambda: update_item_instance(
            connection,
            campaign_id=access.campaign_id,
            item_instance_id=item_instance_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
            name=body.name,
            summary=body.summary,
            origin_notes=body.origin_notes,
            change_note=body.change_note,
        ),
    )


# --- runtime operations ----------------------------------------------------------------------------


def _operate(
    *,
    command_name: str,
    item_instance_id: uuid.UUID,
    access: AccessContext,
    connection: Connection,
    idempotency_key: str | None,
    correlation_id: str | None,
    payload: dict[str, Any],
    command: Callable[[], ItemOperationResult],
) -> Any:
    idem = start_campaign_idempotency(
        connection,
        actor_user_id=access.user_id,
        campaign_id=access.campaign_id,
        idempotency_key=idempotency_key,
        command_name=command_name,
        payload={"item_instance_id": str(item_instance_id), **payload},
        correlation_id=correlation_id,
    )
    if idem.replay is not None:
        return idem.replay
    result = command()
    record_change_log(
        connection,
        change_action_code="updated",
        schema_name="campaign",
        table_name="item_state",
        record_id=result.item_instance_id,
        entity_id=result.item_instance_id,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=command_name,
        event_id=result.event_id,
        changed_fields=result.changed_fields or None,
    )
    response = {
        **_view_json(_load_view(connection, access, item_instance_id), changed=True),
        "event_id": str(result.event_id),
        "operation": result.operation,
    }
    finish_campaign_idempotency(connection, idem, status_code=200, body=response)
    return response


def _common(body: OperationBase) -> dict[str, Any]:
    return {
        "expected_last_event_id": body.expected_last_event_id,
        "world_time_id": body.world_time_id,
        "session_id": body.session_id,
        "note": body.note,
    }


@router.post(_RUNTIME + "/award")
def award_endpoint(
    item_instance_id: uuid.UUID,
    body: AwardRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _operate(
        command_name="award_item",
        item_instance_id=item_instance_id,
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=body.model_dump(mode="json"),
        command=lambda: award_item(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            item_instance_id=item_instance_id,
            holder_entity_id=body.holder_entity_id,
            quantity=body.quantity,
            set_owner=body.set_owner,
            **_common(body),
        ),
    )


def _simple_route(path: str, name: str, command: Callable[..., ItemOperationResult]) -> None:
    @router.post(_RUNTIME + "/" + path, name=name)
    def endpoint(
        item_instance_id: uuid.UUID,
        body: OperationBase,
        access: _Access,
        connection: _Conn,
        idempotency_key: _Key,
        correlation_id: _Corr,
    ) -> Any:
        return _operate(
            command_name=name,
            item_instance_id=item_instance_id,
            access=access,
            connection=connection,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            payload=body.model_dump(mode="json"),
            command=lambda: command(
                connection,
                campaign_id=access.campaign_id,
                actor_user_id=access.user_id,
                item_instance_id=item_instance_id,
                **_common(body),
            ),
        )


def _amount_route(path: str, name: str, command: Callable[..., ItemOperationResult]) -> None:
    @router.post(_RUNTIME + "/" + path, name=name)
    def endpoint(
        item_instance_id: uuid.UUID,
        body: AmountRequest,
        access: _Access,
        connection: _Conn,
        idempotency_key: _Key,
        correlation_id: _Corr,
    ) -> Any:
        return _operate(
            command_name=name,
            item_instance_id=item_instance_id,
            access=access,
            connection=connection,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            payload=body.model_dump(mode="json"),
            command=lambda: command(
                connection,
                campaign_id=access.campaign_id,
                actor_user_id=access.user_id,
                item_instance_id=item_instance_id,
                amount=body.amount,
                **_common(body),
            ),
        )


_simple_route("equip", "equip_item", equip_item)
_simple_route("unequip", "unequip_item", unequip_item)
_simple_route("destroy", "destroy_item", destroy_item)
_simple_route("end-attunement", "end_item_attunement", end_item_attunement)
_amount_route("consume", "consume_item", consume_item)
_amount_route("damage", "damage_item", damage_item)
_amount_route("repair", "repair_item", repair_item)


@router.post(_RUNTIME + "/attune")
def attune_endpoint(
    item_instance_id: uuid.UUID,
    body: AttuneRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _operate(
        command_name="attune_item",
        item_instance_id=item_instance_id,
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=body.model_dump(mode="json"),
        command=lambda: attune_item(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            item_instance_id=item_instance_id,
            character_id=body.character_id,
            **_common(body),
        ),
    )


# --- party inventory -------------------------------------------------------------------------------


@router.get("/campaigns/{campaign_id}/parties/{party_id}/inventory")
def party_inventory_endpoint(party_id: uuid.UUID, access: _Access, connection: _Conn) -> Any:
    party = get_campaign_party(
        connection, campaign_id=access.campaign_id, party_id=party_id, include_archived=True
    )
    if party is None:
        raise NotFoundError()
    world_id = timeline_world_id(connection, access.timeline_id)
    members = [
        m
        for m in list_party_members(connection, timeline_id=access.timeline_id, party_id=party_id)
        if m.is_current
    ]
    return {
        "party_id": str(party_id),
        "members": [
            {
                "character_id": str(member.character_id),
                "character_name": member.character_name,
                "items": [
                    {
                        "item_instance_id": str(item.item_instance_id),
                        "name": item.name,
                        "display_name": item.display_name,
                        "item_category_code": item.item_category_code,
                        "rarity": item.rarity,
                        "quantity": item.quantity,
                        "condition_percentage": item.condition_percentage,
                        "is_equipped": item.is_equipped,
                        "is_destroyed": item.is_destroyed,
                        "is_published": item.is_published,
                        "last_event_id": None
                        if item.last_event_id is None
                        else str(item.last_event_id),
                    }
                    for item in get_inventory_view(
                        connection,
                        holder_entity_id=member.character_id,
                        timeline_id=access.timeline_id,
                        expected_world_id=world_id,
                        reveal_all_properties=True,
                    )
                ],
            }
            for member in members
        ],
    }
