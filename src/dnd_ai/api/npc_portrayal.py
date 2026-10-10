"""NPC portrayal and runtime-option endpoints (Phase 15 checkpoint 15.3A-3, decision D-21).

    GET  /campaigns/{id}/authoring/npc-runtime-options
    GET  /campaigns/{id}/authoring/npcs/{npc_id}/portrayal[?version=]
    POST /campaigns/{id}/authoring/npcs/{npc_id}/portrayal
    POST /campaigns/{id}/authoring/npcs/{npc_id}/detail-level

All `canon.edit`. The portrayal profile is GM-only and never part of a player read; a save appends
the next version against the version number the editor saw. The GM runtime controls for an NPC
(hit points, conditions, resources, location) reuse the character-state and travel routes; the
runtime options here list the rules conditions and resources of the campaign ruleset to pick from.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection

from dnd_ai.commands.npc_portrayal import (
    ProfileResult,
    save_npc_portrayal_profile,
    update_npc_detail_level,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.npc_portrayal import (
    DETAIL_LEVELS,
    FIELD_MAX_LENGTH,
    NOTE_MAX_LENGTH,
    PROFILE_FIELDS,
)
from dnd_ai.queries.npc_portrayal import NpcPortrayalView, get_npc_portrayal, get_runtime_options

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

router = APIRouter(tags=["npc-portrayal"])

_BASE = "/campaigns/{campaign_id}/authoring/npcs"
_Access = Annotated[AccessContext, Depends(require_campaign_capability("canon.edit"))]
_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]


class SavePortrayalRequest(BaseAuthoringRequest):
    # The version the editor saw; 0 when the NPC has no profile yet.
    expected_version: int = Field(ge=0)
    voice: str | None = Field(default=None, max_length=FIELD_MAX_LENGTH)
    speech_style: str | None = Field(default=None, max_length=FIELD_MAX_LENGTH)
    vocabulary: str | None = Field(default=None, max_length=FIELD_MAX_LENGTH)
    mannerisms: str | None = Field(default=None, max_length=FIELD_MAX_LENGTH)
    emotional_baseline: str | None = Field(default=None, max_length=FIELD_MAX_LENGTH)
    conversational_habits: str | None = Field(default=None, max_length=FIELD_MAX_LENGTH)
    topics_avoided: str | None = Field(default=None, max_length=FIELD_MAX_LENGTH)
    disclosure_boundaries: str | None = Field(default=None, max_length=FIELD_MAX_LENGTH)
    roleplay_guidance: str | None = Field(default=None, max_length=FIELD_MAX_LENGTH)
    change_note: str | None = Field(default=None, max_length=NOTE_MAX_LENGTH)


class DetailLevelRequest(BaseAuthoringRequest):
    expected_row_version: int = Field(ge=1)
    detail_level: str = Field(pattern="^(" + "|".join(code for code, _ in DETAIL_LEVELS) + ")$")


def _view_json(view: NpcPortrayalView) -> dict[str, Any]:
    return {
        "npc_id": str(view.npc_id),
        "name": view.name,
        "detail_level": view.detail_level,
        "detail_levels": [{"value": code, "label": label} for code, label in DETAIL_LEVELS],
        "row_version": view.row_version,
        "canon_status": view.canon_status,
        "lifecycle_status": view.lifecycle_status,
        "current_version": view.current_version,
        "shown_version": view.shown_version,
        "fields": view.fields,
        "field_labels": [{"name": name, "label": label} for name, label in PROFILE_FIELDS],
        "limits": {"field_max_length": FIELD_MAX_LENGTH, "note_max_length": NOTE_MAX_LENGTH},
        "versions": [
            {
                "version_number": v.version_number,
                "created_at": v.created_at.isoformat(),
                "change_note": v.change_note,
            }
            for v in view.versions
        ],
        "can_edit": view.can_edit,
    }


@router.get("/campaigns/{campaign_id}/authoring/npc-runtime-options")
def runtime_options_endpoint(access: _Access, connection: _Conn) -> dict[str, Any]:
    options = get_runtime_options(connection, campaign_id=access.campaign_id)
    return {
        "conditions": [{"value": str(i), "label": n, "code": c} for i, n, c in options.conditions],
        "resources": [{"value": str(i), "label": n, "code": c} for i, n, c in options.resources],
    }


@router.get(_BASE + "/{npc_id}/portrayal")
def get_portrayal_endpoint(
    npc_id: uuid.UUID,
    access: _Access,
    connection: _Conn,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    view = get_npc_portrayal(
        connection,
        world_id=timeline_world_id(connection, access.timeline_id),
        npc_id=npc_id,
        version=version,
    )
    if view is None:
        raise NotFoundError()
    return _view_json(view)


@router.post(_BASE + "/{npc_id}/portrayal")
def save_portrayal_endpoint(
    npc_id: uuid.UUID,
    body: SavePortrayalRequest,
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
        command_name="save_npc_portrayal_profile",
        payload={"npc_id": str(npc_id), **body.model_dump(mode="json")},
        correlation_id=correlation_id,
    )
    if idem.replay is not None:
        return idem.replay
    fields = {name: getattr(body, name) for name, _ in PROFILE_FIELDS}
    result: ProfileResult = save_npc_portrayal_profile(
        connection,
        campaign_id=access.campaign_id,
        actor_user_id=access.user_id,
        npc_id=npc_id,
        expected_version=body.expected_version,
        fields=fields,
        change_note=body.change_note,
    )
    if result.changed:
        record_change_log(
            connection,
            change_action_code="created",
            schema_name="character",
            table_name="npc_portrayal_profiles",
            record_id=result.profile_id,
            entity_id=npc_id,
            world_id=result.world_id,
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name="save_npc_portrayal_profile",
            event_id=None,
            changed_fields=result.changed_fields or None,
        )
    view = get_npc_portrayal(connection, world_id=result.world_id, npc_id=npc_id)
    if view is None:
        raise NotFoundError()
    response = {**_view_json(view), "changed": result.changed}
    finish_campaign_idempotency(connection, idem, status_code=200, body=response)
    return JSONResponse(status_code=200, content=response)


@router.post(_BASE + "/{npc_id}/detail-level")
def detail_level_endpoint(
    npc_id: uuid.UUID,
    body: DetailLevelRequest,
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
        command_name="update_npc_detail_level",
        payload={"npc_id": str(npc_id), **body.model_dump(mode="json")},
        correlation_id=correlation_id,
    )
    if idem.replay is not None:
        return idem.replay
    result = update_npc_detail_level(
        connection,
        campaign_id=access.campaign_id,
        actor_user_id=access.user_id,
        npc_id=npc_id,
        expected_row_version=body.expected_row_version,
        detail_level=body.detail_level,
    )
    if result.changed:
        audit_content_write(
            connection,
            result=result,
            command_name="update_npc_detail_level",
            access=access,
            correlation_id=correlation_id,
            reason=None,
        )
    view = get_npc_portrayal(connection, world_id=result.world_id, npc_id=npc_id)
    if view is None:
        raise NotFoundError()
    response = {**_view_json(view), "changed": result.changed}
    finish_campaign_idempotency(connection, idem, status_code=200, body=response)
    return JSONResponse(status_code=200, content=response)
