"""Dungeon authoring and runtime-state endpoints (Phase 15 checkpoint 15.3A-1, D-31).

    GET  /campaigns/{id}/authoring/dungeons/options
    POST /campaigns/{id}/authoring/dungeons
    GET  /campaigns/{id}/authoring/dungeons/{dungeon_id}
    POST /campaigns/{id}/authoring/dungeons/{dungeon_id}/update
    POST /campaigns/{id}/authoring/dungeons/{dungeon_id}/areas
    POST /campaigns/{id}/authoring/dungeons/{dungeon_id}/connections[/{connection_id}/update|remove]
    POST /campaigns/{id}/authoring/dungeons/{dungeon_id}/{features|hazards|interactables}
         [/{child_id}/update|remove]
    GET  /campaigns/{id}/authoring/dungeon-areas/{area_id}
    POST /campaigns/{id}/authoring/dungeon-areas/{area_id}/update
    POST /campaigns/{id}/dungeon-areas/{area_id}/state

All `canon.edit`. The dungeon's `expected_row_version` is the token for every structural change
(D-31); an area's own version covers its fields. Mutations take an `Idempotency-Key`, write one
audit row for a real change (content redacted), capture a revision of the authored aggregate, and
answer with the refreshed dungeon view. The state route writes one event with its effects and
answers with an id-only receipt. Players read dungeon areas through the audience-filtered read.
"""

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection, text

from dnd_ai.commands._content import ContentWriteResult
from dnd_ai.commands.dungeon_state import DungeonStateResult, set_dungeon_state
from dnd_ai.commands.dungeons import (
    add_area_child,
    add_connection,
    create_dungeon,
    create_dungeon_area,
    remove_area_child,
    remove_connection,
    update_area_child,
    update_connection,
    update_dungeon,
    update_dungeon_area,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authoring import DESCRIPTION_MAX_LENGTH, NAME_MAX_LENGTH, REASON_MAX_LENGTH
from dnd_ai.domain.content_authoring import SHORT_TEXT_MAX_LENGTH
from dnd_ai.domain.dungeon_authoring import (
    ALARM_LEVEL_MAX,
    NOTES_MAX_LENGTH,
    RATING_MAX,
    RATING_MIN,
    STATE_KINDS,
)
from dnd_ai.queries.dungeon_authoring import (
    AreaAuthoringView,
    ChildRow,
    ConnectionRow,
    DungeonAuthoringView,
    Reference,
    get_area_authoring,
    get_dungeon_authoring,
    list_connection_types,
)

from ._authoring import (
    BaseAuthoringRequest,
    finish_campaign_idempotency,
    start_campaign_idempotency,
)
from ._content_support import audit_content_write, clean_note
from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .errors import NotFoundError

router = APIRouter(tags=["dungeon-authoring"])

_BASE = "/campaigns/{campaign_id}/authoring/dungeons"
_AREAS = "/campaigns/{campaign_id}/authoring/dungeon-areas"
_Access = Annotated[AccessContext, Depends(require_campaign_capability("canon.edit"))]
_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]

_KIND_BY_PATH = {"features": "feature", "hazards": "hazard", "interactables": "interactable"}


class _DungeonFields(BaseAuthoringRequest):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    summary: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    danger_level: int | None = Field(default=None, ge=RATING_MIN, le=RATING_MAX)
    parent_location_id: uuid.UUID | None = None


class CreateDungeonRequest(_DungeonFields):
    pass


class UpdateDungeonRequest(_DungeonFields):
    expected_row_version: int = Field(ge=1)
    change_note: str | None = Field(default=None, max_length=REASON_MAX_LENGTH)


class _AreaFields(BaseAuthoringRequest):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    summary: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    area_type: str | None = Field(default=None, max_length=SHORT_TEXT_MAX_LENGTH)
    dimensions: str | None = Field(default=None, max_length=SHORT_TEXT_MAX_LENGTH)
    environmental_properties: str | None = Field(default=None, max_length=NOTES_MAX_LENGTH)


class CreateAreaRequest(_AreaFields):
    pass


class UpdateAreaRequest(_AreaFields):
    expected_row_version: int = Field(ge=1)
    change_note: str | None = Field(default=None, max_length=REASON_MAX_LENGTH)


class _ConnectionFields(BaseAuthoringRequest):
    connection_type: str = Field(min_length=1, max_length=64)
    is_one_way: bool = False
    is_hidden: bool = False
    description: str | None = Field(default=None, max_length=NOTES_MAX_LENGTH)
    is_conditional: bool = False
    condition_description: str | None = Field(default=None, max_length=NOTES_MAX_LENGTH)


class AddConnectionRequest(_ConnectionFields):
    expected_row_version: int = Field(ge=1)
    from_area_id: uuid.UUID
    to_area_id: uuid.UUID


class UpdateConnectionRequest(_ConnectionFields):
    expected_row_version: int = Field(ge=1)


class RemoveRequest(BaseAuthoringRequest):
    expected_row_version: int = Field(ge=1)


class _ChildFields(BaseAuthoringRequest):
    child_type: str | None = Field(default=None, max_length=SHORT_TEXT_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=NOTES_MAX_LENGTH)
    is_hidden: bool = False
    severity: int | None = Field(default=None, ge=RATING_MIN, le=RATING_MAX)


class AddChildRequest(_ChildFields):
    expected_row_version: int = Field(ge=1)
    dungeon_area_id: uuid.UUID


class UpdateChildRequest(_ChildFields):
    expected_row_version: int = Field(ge=1)


class SetStateRequest(BaseAuthoringRequest):
    kind: str = Field(pattern="^(" + "|".join(STATE_KINDS) + ")$")
    target_id: uuid.UUID
    expected_last_event_id: uuid.UUID | None
    is_searched: bool | None = None
    is_destroyed: bool | None = None
    alarm_level: int | None = Field(default=None, ge=0, le=ALARM_LEVEL_MAX)
    condition_notes: str | None = Field(default=None, max_length=NOTES_MAX_LENGTH)
    connection_status: str | None = Field(default=None, max_length=64)
    hazard_status: str | None = Field(default=None, max_length=64)
    interactable_status: str | None = Field(default=None, max_length=64)
    world_time_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)


# --- JSON -------------------------------------------------------------------------------------


def _ref(ref: Reference) -> dict[str, Any]:
    return {
        "entity_id": str(ref.entity_id),
        "name": ref.name,
        "canon_status": ref.canon_status,
        "lifecycle_status": ref.lifecycle_status,
    }


def _connection_json(c: ConnectionRow) -> dict[str, Any]:
    return {
        "area_connection_id": str(c.area_connection_id),
        "from_area": _ref(c.from_area),
        "to_area": _ref(c.to_area),
        "connection_type": c.connection_type,
        "connection_type_label": c.connection_type_label,
        "is_one_way": c.is_one_way,
        "is_hidden": c.is_hidden,
        "description": c.description,
        "is_conditional": c.is_conditional,
        "condition_description": c.condition_description,
        "status": c.status,
        "state_event_id": None if c.state_event_id is None else str(c.state_event_id),
    }


def _child_json(c: ChildRow) -> dict[str, Any]:
    return {
        "kind": c.kind,
        "child_id": str(c.child_id),
        "child_type": c.child_type,
        "description": c.description,
        "is_hidden": c.is_hidden,
        "severity": c.severity,
        "status": c.status,
        "is_destroyed": c.is_destroyed,
        "condition_notes": c.condition_notes,
        "state_event_id": None if c.state_event_id is None else str(c.state_event_id),
    }


def _dungeon_json(view: DungeonAuthoringView, *, changed: bool | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "dungeon_id": str(view.dungeon_id),
        "name": view.name,
        "summary": view.summary,
        "danger_level": view.danger_level,
        "parent": None if view.parent is None else _ref(view.parent),
        "canon_status": view.canon_status,
        "lifecycle_status": view.lifecycle_status,
        "row_version": view.row_version,
        "available_actions": view.available_actions,
        "blocked_actions": [{"action": b.action, "reason": b.reason} for b in view.blocked_actions],
        "areas": [
            {
                "dungeon_area_id": str(a.dungeon_area_id),
                "name": a.name,
                "area_type": a.area_type,
                "canon_status": a.canon_status,
                "lifecycle_status": a.lifecycle_status,
                "row_version": a.row_version,
                "feature_count": a.feature_count,
                "hazard_count": a.hazard_count,
                "interactable_count": a.interactable_count,
            }
            for a in view.areas
        ],
        "connections": [_connection_json(c) for c in view.connections],
    }
    if changed is not None:
        body["changed"] = changed
    return body


def _area_json(view: AreaAuthoringView, *, changed: bool | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "dungeon_area_id": str(view.dungeon_area_id),
        "name": view.name,
        "summary": view.summary,
        "area_type": view.area_type,
        "dimensions": view.dimensions,
        "environmental_properties": view.environmental_properties,
        "dungeon": _ref(view.dungeon),
        "dungeon_row_version": view.dungeon_row_version,
        "canon_status": view.canon_status,
        "lifecycle_status": view.lifecycle_status,
        "row_version": view.row_version,
        "available_actions": view.available_actions,
        "blocked_actions": [{"action": b.action, "reason": b.reason} for b in view.blocked_actions],
        "structure_actions": view.structure_actions,
        "features": [_child_json(c) for c in view.features],
        "hazards": [_child_json(c) for c in view.hazards],
        "interactables": [_child_json(c) for c in view.interactables],
        "connections": [_connection_json(c) for c in view.connections],
        "state": {
            "is_searched": view.state.is_searched,
            "is_destroyed": view.state.is_destroyed,
            "alarm_level": view.state.alarm_level,
            "condition_notes": view.state.condition_notes,
            "state_event_id": None
            if view.state.state_event_id is None
            else str(view.state.state_event_id),
        },
        "can_set_state": view.can_set_state,
        "state_choices": {
            name: [{"value": v, "label": label} for v, label in pairs]
            for name, pairs in view.state_choices.items()
        },
    }
    if changed is not None:
        body["changed"] = changed
    return body


# --- the one mutation flow -------------------------------------------------------------------


def _dungeon_response(
    connection: Connection, world_id: uuid.UUID, dungeon_id: uuid.UUID, *, changed: bool
) -> dict[str, Any]:
    view = get_dungeon_authoring(connection, world_id=world_id, dungeon_id=dungeon_id)
    if view is None:
        raise NotFoundError()
    return _dungeon_json(view, changed=changed)


def _run(
    *,
    command_name: str,
    access: AccessContext,
    connection: Connection,
    idempotency_key: str | None,
    correlation_id: str | None,
    payload: dict[str, Any],
    command: Callable[[], ContentWriteResult],
    created: bool = False,
    reason: str | None = None,
    area_view: bool = False,
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

    def aggregate() -> object:
        view = get_dungeon_authoring(
            connection, world_id=result.world_id, dungeon_id=_dungeon_of(connection, result)
        )
        return view

    if result.changed:
        audit_content_write(
            connection,
            result=result,
            command_name=command_name,
            access=access,
            correlation_id=correlation_id,
            reason=reason,
            view_loader=aggregate,
        )
    if area_view:
        area = get_area_authoring(
            connection,
            world_id=result.world_id,
            timeline_id=access.timeline_id,
            dungeon_area_id=result.entity_id,
        )
        if area is None:
            raise NotFoundError()
        response = _area_json(area, changed=result.changed)
    else:
        response = _dungeon_response(
            connection, result.world_id, result.entity_id, changed=result.changed
        )
    if result.record_id is not None and result.record_table != "entities":
        response["record_id"] = str(result.record_id)
    status = 201 if created else 200
    finish_campaign_idempotency(connection, idem, status_code=status, body=response)
    return JSONResponse(status_code=status, content=response) if created else response


def _dungeon_of(connection: Connection, result: ContentWriteResult) -> uuid.UUID:
    """The aggregate root of a write: the dungeon itself, or an area's parent dungeon."""
    if result.entity_type_code == "dungeon_area":
        parent = connection.execute(
            text("SELECT parent_location_id FROM world.locations WHERE location_id = :a"),
            {"a": result.entity_id},
        ).scalar()
        assert isinstance(parent, uuid.UUID)
        return parent
    return result.entity_id


# --- reads -------------------------------------------------------------------------------------


@router.get(_BASE + "/options")
def dungeon_options_endpoint(access: _Access, connection: _Conn) -> dict[str, Any]:
    del access
    return {
        "can_create": True,
        "connection_types": [
            {"value": code, "label": label} for code, label in list_connection_types(connection)
        ],
        "limits": {
            "name_max_length": NAME_MAX_LENGTH,
            "summary_max_length": DESCRIPTION_MAX_LENGTH,
            "short_text_max_length": SHORT_TEXT_MAX_LENGTH,
            "notes_max_length": NOTES_MAX_LENGTH,
            "change_note_max_length": REASON_MAX_LENGTH,
            "rating_min": RATING_MIN,
            "rating_max": RATING_MAX,
            "alarm_level_max": ALARM_LEVEL_MAX,
        },
    }


@router.get(_BASE + "/{dungeon_id}")
def get_dungeon_endpoint(dungeon_id: uuid.UUID, access: _Access, connection: _Conn) -> Any:
    world_id = timeline_world_id(connection, access.timeline_id)
    view = get_dungeon_authoring(connection, world_id=world_id, dungeon_id=dungeon_id)
    if view is None:
        raise NotFoundError()
    return _dungeon_json(view)


@router.get(_AREAS + "/{dungeon_area_id}")
def get_area_endpoint(dungeon_area_id: uuid.UUID, access: _Access, connection: _Conn) -> Any:
    world_id = timeline_world_id(connection, access.timeline_id)
    view = get_area_authoring(
        connection,
        world_id=world_id,
        timeline_id=access.timeline_id,
        dungeon_area_id=dungeon_area_id,
    )
    if view is None:
        raise NotFoundError()
    return _area_json(view)


# --- dungeon and area writes ---------------------------------------------------------------------


@router.post(_BASE, status_code=201)
def create_dungeon_endpoint(
    body: CreateDungeonRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="create_dungeon",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=body.model_dump(mode="json"),
        created=True,
        command=lambda: create_dungeon(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            name=body.name,
            summary=body.summary,
            danger_level=body.danger_level,
            parent_location_id=body.parent_location_id,
        ),
    )


@router.post(_BASE + "/{dungeon_id}/update")
def update_dungeon_endpoint(
    dungeon_id: uuid.UUID,
    body: UpdateDungeonRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="update_dungeon",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"dungeon_id": str(dungeon_id), **body.model_dump(mode="json")},
        reason=clean_note(body.change_note),
        command=lambda: update_dungeon(
            connection,
            campaign_id=access.campaign_id,
            dungeon_id=dungeon_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
            name=body.name,
            summary=body.summary,
            danger_level=body.danger_level,
            parent_location_id=body.parent_location_id,
            change_note=body.change_note,
        ),
    )


@router.post(_BASE + "/{dungeon_id}/areas", status_code=201)
def create_area_endpoint(
    dungeon_id: uuid.UUID,
    body: CreateAreaRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="create_dungeon_area",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"dungeon_id": str(dungeon_id), **body.model_dump(mode="json")},
        created=True,
        area_view=True,
        command=lambda: create_dungeon_area(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            dungeon_id=dungeon_id,
            name=body.name,
            summary=body.summary,
            area_type=body.area_type,
            dimensions=body.dimensions,
            environmental_properties=body.environmental_properties,
        ),
    )


@router.post(_AREAS + "/{dungeon_area_id}/update")
def update_area_endpoint(
    dungeon_area_id: uuid.UUID,
    body: UpdateAreaRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="update_dungeon_area",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"dungeon_area_id": str(dungeon_area_id), **body.model_dump(mode="json")},
        reason=clean_note(body.change_note),
        area_view=True,
        command=lambda: update_dungeon_area(
            connection,
            campaign_id=access.campaign_id,
            dungeon_area_id=dungeon_area_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
            name=body.name,
            summary=body.summary,
            area_type=body.area_type,
            dimensions=body.dimensions,
            environmental_properties=body.environmental_properties,
            change_note=body.change_note,
        ),
    )


# --- structural children ------------------------------------------------------------------------


@router.post(_BASE + "/{dungeon_id}/connections", status_code=201)
def add_connection_endpoint(
    dungeon_id: uuid.UUID,
    body: AddConnectionRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="add_area_connection",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"dungeon_id": str(dungeon_id), **body.model_dump(mode="json")},
        created=True,
        command=lambda: add_connection(
            connection,
            campaign_id=access.campaign_id,
            dungeon_id=dungeon_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
            from_area_id=body.from_area_id,
            to_area_id=body.to_area_id,
            connection_type=body.connection_type,
            is_one_way=body.is_one_way,
            is_hidden=body.is_hidden,
            description=body.description,
            is_conditional=body.is_conditional,
            condition_description=body.condition_description,
        ),
    )


@router.post(_BASE + "/{dungeon_id}/connections/{area_connection_id}/update")
def update_connection_endpoint(
    dungeon_id: uuid.UUID,
    area_connection_id: uuid.UUID,
    body: UpdateConnectionRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="update_area_connection",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={
            "dungeon_id": str(dungeon_id),
            "area_connection_id": str(area_connection_id),
            **body.model_dump(mode="json"),
        },
        command=lambda: update_connection(
            connection,
            campaign_id=access.campaign_id,
            dungeon_id=dungeon_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
            area_connection_id=area_connection_id,
            connection_type=body.connection_type,
            is_one_way=body.is_one_way,
            is_hidden=body.is_hidden,
            description=body.description,
            is_conditional=body.is_conditional,
            condition_description=body.condition_description,
        ),
    )


@router.post(_BASE + "/{dungeon_id}/connections/{area_connection_id}/remove")
def remove_connection_endpoint(
    dungeon_id: uuid.UUID,
    area_connection_id: uuid.UUID,
    body: RemoveRequest,
    access: _Access,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="remove_area_connection",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={
            "dungeon_id": str(dungeon_id),
            "area_connection_id": str(area_connection_id),
            **body.model_dump(mode="json"),
        },
        command=lambda: remove_connection(
            connection,
            campaign_id=access.campaign_id,
            dungeon_id=dungeon_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
            area_connection_id=area_connection_id,
        ),
    )


def _child_routes() -> None:
    for path, kind in _KIND_BY_PATH.items():

        def add(
            dungeon_id: uuid.UUID,
            body: AddChildRequest,
            access: _Access,
            connection: _Conn,
            idempotency_key: _Key,
            correlation_id: _Corr,
            kind: str = kind,
        ) -> Any:
            return _run(
                command_name=f"add_area_{kind}",
                access=access,
                connection=connection,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                payload={"dungeon_id": str(dungeon_id), **body.model_dump(mode="json")},
                created=True,
                command=lambda: add_area_child(
                    connection,
                    campaign_id=access.campaign_id,
                    dungeon_id=dungeon_id,
                    actor_user_id=access.user_id,
                    expected_row_version=body.expected_row_version,
                    dungeon_area_id=body.dungeon_area_id,
                    kind=kind,
                    child_type=body.child_type,
                    description=body.description,
                    is_hidden=body.is_hidden,
                    severity=body.severity,
                ),
            )

        def update(
            dungeon_id: uuid.UUID,
            child_id: uuid.UUID,
            body: UpdateChildRequest,
            access: _Access,
            connection: _Conn,
            idempotency_key: _Key,
            correlation_id: _Corr,
            kind: str = kind,
        ) -> Any:
            return _run(
                command_name=f"update_area_{kind}",
                access=access,
                connection=connection,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                payload={
                    "dungeon_id": str(dungeon_id),
                    "child_id": str(child_id),
                    **body.model_dump(mode="json"),
                },
                command=lambda: update_area_child(
                    connection,
                    campaign_id=access.campaign_id,
                    dungeon_id=dungeon_id,
                    actor_user_id=access.user_id,
                    expected_row_version=body.expected_row_version,
                    kind=kind,
                    child_id=child_id,
                    child_type=body.child_type,
                    description=body.description,
                    is_hidden=body.is_hidden,
                    severity=body.severity,
                ),
            )

        def remove(
            dungeon_id: uuid.UUID,
            child_id: uuid.UUID,
            body: RemoveRequest,
            access: _Access,
            connection: _Conn,
            idempotency_key: _Key,
            correlation_id: _Corr,
            kind: str = kind,
        ) -> Any:
            return _run(
                command_name=f"remove_area_{kind}",
                access=access,
                connection=connection,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                payload={
                    "dungeon_id": str(dungeon_id),
                    "child_id": str(child_id),
                    **body.model_dump(mode="json"),
                },
                command=lambda: remove_area_child(
                    connection,
                    campaign_id=access.campaign_id,
                    dungeon_id=dungeon_id,
                    actor_user_id=access.user_id,
                    expected_row_version=body.expected_row_version,
                    kind=kind,
                    child_id=child_id,
                ),
            )

        base = _BASE + "/{dungeon_id}/" + path
        router.add_api_route(base, add, methods=["POST"], status_code=201)
        router.add_api_route(base + "/{child_id}/update", update, methods=["POST"])
        router.add_api_route(base + "/{child_id}/remove", remove, methods=["POST"])


_child_routes()


# --- runtime state -------------------------------------------------------------------------------

_STATE_FIELDS = (
    "is_searched",
    "is_destroyed",
    "alarm_level",
    "condition_notes",
    "connection_status",
    "hazard_status",
    "interactable_status",
)


@router.post("/campaigns/{campaign_id}/dungeon-areas/{dungeon_area_id}/state")
def set_state_endpoint(
    dungeon_area_id: uuid.UUID,
    body: SetStateRequest,
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
        command_name="set_dungeon_state",
        payload={"dungeon_area_id": str(dungeon_area_id), **body.model_dump(mode="json")},
        correlation_id=correlation_id,
    )
    if idem.replay is not None:
        return idem.replay
    changes = {name: getattr(body, name) for name in _STATE_FIELDS if name in body.model_fields_set}
    result: DungeonStateResult = set_dungeon_state(
        connection,
        campaign_id=access.campaign_id,
        actor_user_id=access.user_id,
        dungeon_area_id=dungeon_area_id,
        kind=body.kind,
        target_id=body.target_id,
        changes=changes,
        expected_last_event_id=body.expected_last_event_id,
        world_time_id=body.world_time_id,
        note=body.note,
    )
    if result.changed:
        record_change_log(
            connection,
            change_action_code="updated",
            schema_name="campaign",
            table_name=result.table,
            record_id=result.target_id,
            entity_id=result.area_id,
            world_id=result.world_id,
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name="set_dungeon_state",
            event_id=result.event_id,
            changed_fields=result.changed_fields or None,
        )
    receipt: dict[str, Any] = {
        "dungeon_area_id": str(dungeon_area_id),
        "kind": result.kind,
        "target_id": str(result.target_id),
        "changed": result.changed,
    }
    if result.event_id is not None:
        receipt["event_id"] = str(result.event_id)
    finish_campaign_idempotency(connection, idem, status_code=200, body=receipt)
    return JSONResponse(status_code=200, content=receipt)
