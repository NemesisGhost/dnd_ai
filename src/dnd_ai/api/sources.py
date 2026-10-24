"""Source and provenance endpoints (Phase 15 checkpoint 15.3C-1, decision D-26).

    GET  /campaigns/{id}/sources
    POST /campaigns/{id}/sources
    POST /campaigns/{id}/entities/{eid}/sources/attach
    POST /campaigns/{id}/entities/{eid}/sources/detach
    GET  /campaigns/{id}/entities/{eid}/provenance

All `canon.edit` (a player holds no such capability and is refused like any authoring route).
Sources are world-owned, of a closed list of types, with a title and a GM-only reference text; a
source of another world is never visible or attachable. Writes use the campaign idempotency
store and write one audit row whose title and reference text are redacted.
"""

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection

from dnd_ai.commands.sources import SourceResult, attach_source, create_source, detach_source
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.source_authoring import (
    REFERENCE_MAX_LENGTH,
    SOURCE_TYPES,
    TITLE_MAX_LENGTH,
)
from dnd_ai.domain.world_authority import WORLD_CANON_READ_PRIVATE
from dnd_ai.queries.provenance import (
    EntityRef,
    LinkRow,
    SourceRow,
    get_provenance,
    list_world_sources,
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

router = APIRouter(tags=["sources"])

_Access = Annotated[AccessContext, Depends(require_campaign_capability("canon.edit"))]
# Reads of the private side of shared world canon (drafts, GM-only prep, revisions,
# provenance, sources, the review queue) also need `world.canon.read_private`
# (docs/adr/0020-scoped-system-world-and-campaign-roles.md, D6).
_PrivateRead = Annotated[
    AccessContext,
    Depends(require_campaign_capability("canon.edit", world_capability=WORLD_CANON_READ_PRIVATE)),
]
_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]


class CreateSourceRequest(BaseAuthoringRequest):
    source_type: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=TITLE_MAX_LENGTH)
    reference: str | None = Field(default=None, max_length=REFERENCE_MAX_LENGTH)


class SourceLinkRequest(BaseAuthoringRequest):
    source_id: uuid.UUID


def _source_json(s: SourceRow) -> dict[str, Any]:
    return {
        "source_id": str(s.source_id),
        "source_type": s.source_type,
        "source_type_label": s.source_type_label,
        "title": s.title,
        "reference": s.reference,
        "created_by_name": s.created_by_name,
        "attached_count": s.attached_count,
    }


def _ref(r: EntityRef | None) -> dict[str, Any] | None:
    return None if r is None else {"entity_id": str(r.entity_id), "name": r.name}


def _link_json(link: LinkRow) -> dict[str, Any]:
    return {
        "source_id": str(link.source_id),
        "source_type_label": link.source_type_label,
        "title": link.title,
        "reference": link.reference,
        "attached_at": link.attached_at.isoformat(),
        "attached_by_name": link.attached_by_name,
        "detached_at": None if link.detached_at is None else link.detached_at.isoformat(),
        "detached_by_name": link.detached_by_name,
        "is_attached": link.detached_at is None,
    }


def _provenance_json(connection: Connection, access: AccessContext, entity_id: uuid.UUID) -> Any:
    view = get_provenance(
        connection, world_id=timeline_world_id(connection, access.timeline_id), entity_id=entity_id
    )
    if view is None:
        raise NotFoundError()
    return {
        "entity_id": str(view.entity_id),
        "name": view.name,
        "entity_type_code": view.entity_type_code,
        "canon_status": view.canon_status,
        "lifecycle_status": view.lifecycle_status,
        "created_at": view.created_at.isoformat(),
        "created_by_name": view.created_by_name,
        "origin": None if view.origin is None else _source_json(view.origin),
        "links": [_link_json(link) for link in view.links],
        "transitions": [
            {
                "label": t.label,
                "previous_status": t.previous_status,
                "new_status": t.new_status,
                "actor_name": t.actor_name,
                "recorded_at": t.recorded_at.isoformat(),
            }
            for t in view.transitions
        ],
        "superseded_by": _ref(view.superseded_by),
        "supersedes": [_ref(r) for r in view.supersedes],
    }


@router.get("/campaigns/{campaign_id}/sources")
def list_sources_endpoint(access: _PrivateRead, connection: _Conn) -> dict[str, Any]:
    sources = list_world_sources(
        connection, world_id=timeline_world_id(connection, access.timeline_id)
    )
    return {
        "items": [_source_json(s) for s in sources],
        "source_types": [{"value": code, "label": label} for code, label in SOURCE_TYPES],
        "limits": {
            "title_max_length": TITLE_MAX_LENGTH,
            "reference_max_length": REFERENCE_MAX_LENGTH,
        },
    }


@router.get("/campaigns/{campaign_id}/entities/{entity_id}/provenance")
def provenance_endpoint(entity_id: uuid.UUID, access: _PrivateRead, connection: _Conn) -> Any:
    return _provenance_json(connection, access, entity_id)


def _write(
    *,
    command_name: str,
    access: AccessContext,
    connection: Connection,
    idempotency_key: str | None,
    correlation_id: str | None,
    payload: dict[str, Any],
    command: Callable[[], SourceResult],
    created: bool = False,
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
    record_change_log(
        connection,
        change_action_code=result.action,
        schema_name="core",
        table_name=result.table,
        record_id=result.link_id or result.source_id,
        entity_id=result.entity_id,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=command_name,
        event_id=None,
        changed_fields=result.changed_fields or None,
        source_id=result.source_id,
    )
    if result.entity_id is None:
        sources = list_world_sources(connection, world_id=result.world_id)
        created_row = next(s for s in sources if s.source_id == result.source_id)
        response: dict[str, Any] = _source_json(created_row)
    else:
        response = _provenance_json(connection, access, result.entity_id)
    status = 201 if created else 200
    finish_campaign_idempotency(connection, idem, status_code=status, body=response)
    return JSONResponse(status_code=status, content=response) if created else response


@router.post("/campaigns/{campaign_id}/sources", status_code=201)
def create_source_endpoint(
    body: CreateSourceRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _write(
        command_name="create_source",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=body.model_dump(mode="json"),
        created=True,
        command=lambda: create_source(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            source_type=body.source_type,
            title=body.title,
            reference=body.reference,
        ),
    )


@router.post("/campaigns/{campaign_id}/entities/{entity_id}/sources/attach")
def attach_source_endpoint(
    entity_id: uuid.UUID,
    body: SourceLinkRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _write(
        command_name="attach_source",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"entity_id": str(entity_id), **body.model_dump(mode="json")},
        command=lambda: attach_source(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            entity_id=entity_id,
            source_id=body.source_id,
        ),
    )


@router.post("/campaigns/{campaign_id}/entities/{entity_id}/sources/detach")
def detach_source_endpoint(
    entity_id: uuid.UUID,
    body: SourceLinkRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _write(
        command_name="detach_source",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"entity_id": str(entity_id), **body.model_dump(mode="json")},
        command=lambda: detach_source(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            entity_id=entity_id,
            source_id=body.source_id,
        ),
    )
