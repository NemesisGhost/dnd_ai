"""NPC identity authoring endpoints (Phase 15.1, ADR 0015).

    GET  /campaigns/{campaign_id}/authoring/npcs/options
    POST /campaigns/{campaign_id}/authoring/npcs
    GET  /campaigns/{campaign_id}/authoring/npcs/{npc_id}
    POST /campaigns/{campaign_id}/authoring/npcs/{npc_id}/update

Same contract as the other typed content routes (`dnd_ai.api.location_authoring`).
The species list is the server's: canon species of the current version of each
ruleset the world allows. Origin choices come from the Location parent-options
list. Only NPCs are reachable here; a player character at this route is a 404.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection

from dnd_ai.commands._content import ContentWriteResult
from dnd_ai.commands.npcs import create_npc, update_npc
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authoring import DESCRIPTION_MAX_LENGTH, NAME_MAX_LENGTH, REASON_MAX_LENGTH
from dnd_ai.domain.npc_authoring import NPC_TEXT_MAX_LENGTH, SIZE_CATEGORIES
from dnd_ai.domain.world_authority import WORLD_CANON_READ_PRIVATE
from dnd_ai.queries.npc_authoring import NpcAuthoringView, get_npc_authoring, list_species_options

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
from .errors import NotFoundError

router = APIRouter(tags=["npc-authoring"])

_BASE = "/campaigns/{campaign_id}/authoring/npcs"
_CAPABILITY = "canon.edit"

_Access = Annotated[AccessContext, Depends(require_campaign_capability(_CAPABILITY))]
# Reads of the private side of shared world canon (drafts, GM-only prep, revisions,
# provenance, sources, the review queue) also need `world.canon.read_private`
# (docs/adr/0020-scoped-system-world-and-campaign-roles.md, D6).
_PrivateRead = Annotated[
    AccessContext,
    Depends(require_campaign_capability(_CAPABILITY, world_capability=WORLD_CANON_READ_PRIVATE)),
]
_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]


class _NpcFields(BaseAuthoringRequest):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    summary: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    species_id: uuid.UUID
    size_category: str = Field(min_length=1, max_length=32)
    origin_location_id: uuid.UUID | None = None
    background: str | None = Field(default=None, max_length=NPC_TEXT_MAX_LENGTH)
    appearance: str | None = Field(default=None, max_length=NPC_TEXT_MAX_LENGTH)
    notes: str | None = Field(default=None, max_length=NPC_TEXT_MAX_LENGTH)


class CreateNpcRequest(_NpcFields):
    pass


class UpdateNpcRequest(_NpcFields):
    expected_row_version: int = Field(ge=1)
    change_note: str | None = Field(default=None, max_length=REASON_MAX_LENGTH)


def _view_json(view: NpcAuthoringView, *, changed: bool | None = None) -> dict[str, Any]:
    labels = dict(SIZE_CATEGORIES)
    body: dict[str, Any] = {
        "npc_id": str(view.character_id),
        "name": view.name,
        "summary": view.summary,
        "species": {"species_id": str(view.species_id), "name": view.species_name},
        "size": {"code": view.size_category, "label": labels.get(view.size_category)},
        "origin": (
            None
            if view.origin is None
            else {
                "entity_id": str(view.origin.entity_id),
                "name": view.origin.name,
                "canon_status": view.origin.canon_status,
                "lifecycle_status": view.origin.lifecycle_status,
            }
        ),
        "background": view.background,
        "appearance": view.appearance,
        "notes": view.notes,
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
    return write_receipt(result, "npc_id", changed=changed)


@router.get(_BASE + "/options")
def npc_options_endpoint(access: _PrivateRead, connection: _Conn) -> dict[str, Any]:
    world_id = timeline_world_id(connection, access.timeline_id)
    return {
        "can_create": True,
        "species": [
            {
                "species_id": str(s.species_id),
                "name": s.name,
                "ruleset_name": s.ruleset_name,
            }
            for s in list_species_options(connection, world_id=world_id)
        ],
        "sizes": [{"code": code, "label": label} for code, label in SIZE_CATEGORIES],
        "limits": {
            "name_max_length": NAME_MAX_LENGTH,
            "summary_max_length": DESCRIPTION_MAX_LENGTH,
            "text_max_length": NPC_TEXT_MAX_LENGTH,
            "change_note_max_length": REASON_MAX_LENGTH,
        },
    }


@router.post(_BASE, status_code=201)
def create_npc_endpoint(
    body: CreateNpcRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    command_name = "create_npc"
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
    result = create_npc(
        connection,
        campaign_id=access.campaign_id,
        actor_user_id=access.user_id,
        name=body.name,
        summary=body.summary,
        species_id=body.species_id,
        size_category=body.size_category,
        origin_location_id=body.origin_location_id,
        background=body.background,
        appearance=body.appearance,
        notes=body.notes,
    )
    audit_content_write(
        connection,
        result=result,
        command_name=command_name,
        access=access,
        correlation_id=correlation_id,
        reason=None,
        view_loader=lambda: get_npc_authoring(
            connection, world_id=result.world_id, npc_id=result.entity_id
        ),
    )
    response = _response(connection, result, changed=True)
    finish_campaign_idempotency(connection, idem, status_code=201, body=response)
    return JSONResponse(status_code=201, content=response)


@router.get(_BASE + "/{npc_id}")
def get_npc_authoring_endpoint(
    npc_id: uuid.UUID, access: _PrivateRead, connection: _Conn
) -> dict[str, Any]:
    world_id = timeline_world_id(connection, access.timeline_id)
    view = get_npc_authoring(connection, world_id=world_id, npc_id=npc_id)
    if view is None:
        raise NotFoundError()
    return _view_json(view)


@router.post(_BASE + "/{npc_id}/update")
def update_npc_endpoint(
    npc_id: uuid.UUID,
    body: UpdateNpcRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    command_name = "update_npc"
    idem = start_campaign_idempotency(
        connection,
        actor_user_id=access.user_id,
        campaign_id=access.campaign_id,
        idempotency_key=idempotency_key,
        command_name=command_name,
        payload={"npc_id": str(npc_id), **body.model_dump(mode="json")},
        correlation_id=correlation_id,
    )
    if idem.replay is not None:
        return idem.replay
    result = update_npc(
        connection,
        campaign_id=access.campaign_id,
        npc_id=npc_id,
        actor_user_id=access.user_id,
        expected_row_version=body.expected_row_version,
        name=body.name,
        summary=body.summary,
        species_id=body.species_id,
        size_category=body.size_category,
        origin_location_id=body.origin_location_id,
        background=body.background,
        appearance=body.appearance,
        notes=body.notes,
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
            view_loader=lambda: get_npc_authoring(
                connection, world_id=result.world_id, npc_id=result.entity_id
            ),
        )
    response = _response(connection, result, changed=result.changed)
    finish_campaign_idempotency(connection, idem, status_code=200, body=response)
    return response
