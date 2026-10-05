"""Quest definition authoring endpoints (Phase 15.1, ADR 0015).

    GET  /campaigns/{campaign_id}/authoring/quests/options
    GET  /campaigns/{campaign_id}/authoring/quests/target-options
    POST /campaigns/{campaign_id}/authoring/quests
    GET  /campaigns/{campaign_id}/authoring/quests/{quest_id}
    POST /campaigns/{campaign_id}/authoring/quests/{quest_id}/update
    POST …/{quest_id}/stages                       add_quest_stage
    POST …/{quest_id}/stages/reorder               reorder_quest_stages
    POST …/{quest_id}/stages/{stage_id}/update     update_quest_stage
    POST …/{quest_id}/stages/{stage_id}/remove     remove_quest_stage
    POST …/{quest_id}/stages/{stage_id}/objectives                      add_quest_objective
    POST …/{quest_id}/stages/{stage_id}/objectives/{objective_id}/update
    POST …/{quest_id}/stages/{stage_id}/objectives/{objective_id}/remove

Every mutation takes the quest's `expected_row_version` and returns the whole
authoring view, so the portal never reasons about a partial aggregate. Same
contract as the other typed content routes (`dnd_ai.api.location_authoring`):
`canon.edit` before anything resolves and again under lock, humans only, strict
bodies, campaign-scoped idempotency, one audit row per real change, `no-store`.
"""

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection

from dnd_ai.commands._content import ContentWriteResult
from dnd_ai.commands.quest_definitions import (
    MAX_OBJECTIVES_PER_STAGE,
    MAX_STAGES,
    add_quest_objective,
    add_quest_stage,
    create_quest,
    remove_quest_objective,
    remove_quest_stage,
    reorder_quest_stages,
    update_quest,
    update_quest_objective,
    update_quest_stage,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authoring import DESCRIPTION_MAX_LENGTH, NAME_MAX_LENGTH, REASON_MAX_LENGTH
from dnd_ai.domain.quest_authoring import OBJECTIVE_TARGET_TYPE_CODES, QUANTITY_MAX
from dnd_ai.queries.quest_authoring import (
    QuestAuthoringView,
    get_quest_authoring,
    list_objective_types,
    quest_option_catalogs,
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

router = APIRouter(tags=["quest-authoring"])

_BASE = "/campaigns/{campaign_id}/authoring/quests"
_CAPABILITY = "canon.edit"

_Access = Annotated[AccessContext, Depends(require_campaign_capability(_CAPABILITY))]
_Conn = Annotated[Connection, Depends(get_connection)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]

_Version = Annotated[int, Field(ge=1)]


class CreateQuestRequest(BaseAuthoringRequest):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    summary: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)


class UpdateQuestRequest(CreateQuestRequest):
    expected_row_version: _Version
    change_note: str | None = Field(default=None, max_length=REASON_MAX_LENGTH)


class StageRequest(BaseAuthoringRequest):
    expected_row_version: _Version
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    stage_type: str = Field(min_length=1, max_length=32)


class ReorderRequest(BaseAuthoringRequest):
    expected_row_version: _Version
    stage_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_STAGES)


class VersionRequest(BaseAuthoringRequest):
    expected_row_version: _Version


class ObjectiveRequest(BaseAuthoringRequest):
    expected_row_version: _Version
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    objective_type: str = Field(min_length=1, max_length=64)
    requirement_level: str = Field(min_length=1, max_length=32)
    completion_mode: str = Field(min_length=1, max_length=32)
    visibility_policy: str = Field(min_length=1, max_length=32)
    quantity_required: int | None = Field(default=None, ge=1, le=QUANTITY_MAX)
    target_entity_id: uuid.UUID | None = None


def _view_json(view: QuestAuthoringView, *, changed: bool | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "quest_id": str(view.quest_id),
        "name": view.name,
        "summary": view.summary,
        "has_progress": view.has_progress,
        "stages": [
            {
                "quest_stage_id": str(stage.quest_stage_id),
                "name": stage.name,
                "description": stage.description,
                "stage_type": stage.stage_type,
                "sequence_number": stage.sequence_number,
                "objectives": [
                    {
                        "quest_objective_id": str(o.quest_objective_id),
                        "name": o.name,
                        "description": o.description,
                        "objective_type": o.objective_type,
                        "objective_type_label": o.objective_type_label,
                        "requirement_level": o.requirement_level,
                        "completion_mode": o.completion_mode,
                        "visibility_policy": o.visibility_policy,
                        "quantity_required": o.quantity_required,
                        "target_kind": o.target_kind,
                        "target": (
                            None
                            if o.target is None
                            else {
                                "entity_id": str(o.target.entity_id),
                                "name": o.target.name,
                                "canon_status": o.target.canon_status,
                                "lifecycle_status": o.target.lifecycle_status,
                            }
                        ),
                    }
                    for o in stage.objectives
                ],
            }
            for stage in view.stages
        ],
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
    return write_receipt(result, "quest_id", changed=changed)


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
) -> Any:
    """The one mutation flow every quest command shares: reserve the key (replay
    answers before the command runs), run the command, audit exactly once if it
    changed anything, answer with the whole authoring view, complete the key."""
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
            view_loader=lambda: get_quest_authoring(
                connection, world_id=result.world_id, quest_id=result.entity_id
            ),
        )
    response = _response(connection, result, changed=result.changed)
    status = 201 if created else 200
    finish_campaign_idempotency(connection, idem, status_code=status, body=response)
    return JSONResponse(status_code=status, content=response) if created else response


# --- reads -------------------------------------------------------------------------------------


@router.get(_BASE + "/options")
def quest_options_endpoint(access: _Access, connection: _Conn) -> dict[str, Any]:
    del access
    catalogs = quest_option_catalogs()
    return {
        "can_create": True,
        "objective_types": [
            {"value": code, "label": label} for code, label in list_objective_types(connection)
        ],
        **{
            name: [{"value": value, "label": label} for value, label in pairs]
            for name, pairs in catalogs.items()
        },
        "limits": {
            "name_max_length": NAME_MAX_LENGTH,
            "summary_max_length": DESCRIPTION_MAX_LENGTH,
            "change_note_max_length": REASON_MAX_LENGTH,
            "max_stages": MAX_STAGES,
            "max_objectives_per_stage": MAX_OBJECTIVES_PER_STAGE,
            "quantity_max": QUANTITY_MAX,
        },
    }


@router.get(_BASE + "/target-options")
def quest_target_options_endpoint(
    access: _Access,
    connection: _Conn,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
) -> dict[str, Any]:
    keyset = "quest_target_options"
    rows = list_reference_options(
        connection,
        world_id=timeline_world_id(connection, access.timeline_id),
        type_codes=OBJECTIVE_TARGET_TYPE_CODES,
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


@router.get(_BASE + "/{quest_id}")
def get_quest_authoring_endpoint(
    quest_id: uuid.UUID, access: _Access, connection: _Conn
) -> dict[str, Any]:
    view = get_quest_authoring(
        connection, world_id=timeline_world_id(connection, access.timeline_id), quest_id=quest_id
    )
    if view is None:
        raise NotFoundError()
    return _view_json(view)


# --- the quest ---------------------------------------------------------------------------------


@router.post(_BASE, status_code=201)
def create_quest_endpoint(
    body: CreateQuestRequest, access: _Access, connection: _Conn, key: _Key, corr: _Corr
) -> Any:
    return _run(
        command_name="create_quest",
        access=access,
        connection=connection,
        idempotency_key=key,
        correlation_id=corr,
        payload=body.model_dump(mode="json"),
        created=True,
        command=lambda: create_quest(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            name=body.name,
            summary=body.summary,
        ),
    )


@router.post(_BASE + "/{quest_id}/update")
def update_quest_endpoint(
    quest_id: uuid.UUID,
    body: UpdateQuestRequest,
    access: _Access,
    connection: _Conn,
    key: _Key,
    corr: _Corr,
) -> Any:
    return _run(
        command_name="update_quest",
        access=access,
        connection=connection,
        idempotency_key=key,
        correlation_id=corr,
        payload={"quest_id": str(quest_id), **body.model_dump(mode="json")},
        reason=clean_note(body.change_note),
        command=lambda: update_quest(
            connection,
            campaign_id=access.campaign_id,
            quest_id=quest_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
            name=body.name,
            summary=body.summary,
            change_note=body.change_note,
        ),
    )


# --- stages ------------------------------------------------------------------------------------


@router.post(_BASE + "/{quest_id}/stages")
def add_stage_endpoint(
    quest_id: uuid.UUID,
    body: StageRequest,
    access: _Access,
    connection: _Conn,
    key: _Key,
    corr: _Corr,
) -> Any:
    return _run(
        command_name="add_quest_stage",
        access=access,
        connection=connection,
        idempotency_key=key,
        correlation_id=corr,
        payload={"quest_id": str(quest_id), **body.model_dump(mode="json")},
        command=lambda: add_quest_stage(
            connection,
            campaign_id=access.campaign_id,
            quest_id=quest_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
            name=body.name,
            description=body.description,
            stage_type=body.stage_type,
        ),
    )


@router.post(_BASE + "/{quest_id}/stages/reorder")
def reorder_stages_endpoint(
    quest_id: uuid.UUID,
    body: ReorderRequest,
    access: _Access,
    connection: _Conn,
    key: _Key,
    corr: _Corr,
) -> Any:
    return _run(
        command_name="reorder_quest_stages",
        access=access,
        connection=connection,
        idempotency_key=key,
        correlation_id=corr,
        payload={"quest_id": str(quest_id), **body.model_dump(mode="json")},
        command=lambda: reorder_quest_stages(
            connection,
            campaign_id=access.campaign_id,
            quest_id=quest_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
            ordered_stage_ids=body.stage_ids,
        ),
    )


@router.post(_BASE + "/{quest_id}/stages/{stage_id}/update")
def update_stage_endpoint(
    quest_id: uuid.UUID,
    stage_id: uuid.UUID,
    body: StageRequest,
    access: _Access,
    connection: _Conn,
    key: _Key,
    corr: _Corr,
) -> Any:
    return _run(
        command_name="update_quest_stage",
        access=access,
        connection=connection,
        idempotency_key=key,
        correlation_id=corr,
        payload={
            "quest_id": str(quest_id),
            "stage_id": str(stage_id),
            **body.model_dump(mode="json"),
        },
        command=lambda: update_quest_stage(
            connection,
            campaign_id=access.campaign_id,
            quest_id=quest_id,
            quest_stage_id=stage_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
            name=body.name,
            description=body.description,
            stage_type=body.stage_type,
        ),
    )


@router.post(_BASE + "/{quest_id}/stages/{stage_id}/remove")
def remove_stage_endpoint(
    quest_id: uuid.UUID,
    stage_id: uuid.UUID,
    body: VersionRequest,
    access: _Access,
    connection: _Conn,
    key: _Key,
    corr: _Corr,
) -> Any:
    return _run(
        command_name="remove_quest_stage",
        access=access,
        connection=connection,
        idempotency_key=key,
        correlation_id=corr,
        payload={
            "quest_id": str(quest_id),
            "stage_id": str(stage_id),
            **body.model_dump(mode="json"),
        },
        command=lambda: remove_quest_stage(
            connection,
            campaign_id=access.campaign_id,
            quest_id=quest_id,
            quest_stage_id=stage_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
        ),
    )


# --- objectives --------------------------------------------------------------------------------


@router.post(_BASE + "/{quest_id}/stages/{stage_id}/objectives")
def add_objective_endpoint(
    quest_id: uuid.UUID,
    stage_id: uuid.UUID,
    body: ObjectiveRequest,
    access: _Access,
    connection: _Conn,
    key: _Key,
    corr: _Corr,
) -> Any:
    return _run(
        command_name="add_quest_objective",
        access=access,
        connection=connection,
        idempotency_key=key,
        correlation_id=corr,
        payload={
            "quest_id": str(quest_id),
            "stage_id": str(stage_id),
            **body.model_dump(mode="json"),
        },
        command=lambda: add_quest_objective(
            connection,
            campaign_id=access.campaign_id,
            quest_id=quest_id,
            quest_stage_id=stage_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
            name=body.name,
            description=body.description,
            objective_type=body.objective_type,
            requirement_level=body.requirement_level,
            completion_mode=body.completion_mode,
            visibility_policy=body.visibility_policy,
            quantity_required=body.quantity_required,
            target_entity_id=body.target_entity_id,
        ),
    )


@router.post(_BASE + "/{quest_id}/stages/{stage_id}/objectives/{objective_id}/update")
def update_objective_endpoint(
    quest_id: uuid.UUID,
    stage_id: uuid.UUID,
    objective_id: uuid.UUID,
    body: ObjectiveRequest,
    access: _Access,
    connection: _Conn,
    key: _Key,
    corr: _Corr,
) -> Any:
    return _run(
        command_name="update_quest_objective",
        access=access,
        connection=connection,
        idempotency_key=key,
        correlation_id=corr,
        payload={
            "quest_id": str(quest_id),
            "stage_id": str(stage_id),
            "objective_id": str(objective_id),
            **body.model_dump(mode="json"),
        },
        command=lambda: update_quest_objective(
            connection,
            campaign_id=access.campaign_id,
            quest_id=quest_id,
            quest_stage_id=stage_id,
            quest_objective_id=objective_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
            name=body.name,
            description=body.description,
            objective_type=body.objective_type,
            requirement_level=body.requirement_level,
            completion_mode=body.completion_mode,
            visibility_policy=body.visibility_policy,
            quantity_required=body.quantity_required,
            target_entity_id=body.target_entity_id,
        ),
    )


@router.post(_BASE + "/{quest_id}/stages/{stage_id}/objectives/{objective_id}/remove")
def remove_objective_endpoint(
    quest_id: uuid.UUID,
    stage_id: uuid.UUID,
    objective_id: uuid.UUID,
    body: VersionRequest,
    access: _Access,
    connection: _Conn,
    key: _Key,
    corr: _Corr,
) -> Any:
    return _run(
        command_name="remove_quest_objective",
        access=access,
        connection=connection,
        idempotency_key=key,
        correlation_id=corr,
        payload={
            "quest_id": str(quest_id),
            "stage_id": str(stage_id),
            "objective_id": str(objective_id),
            **body.model_dump(mode="json"),
        },
        command=lambda: remove_quest_objective(
            connection,
            campaign_id=access.campaign_id,
            quest_id=quest_id,
            quest_stage_id=stage_id,
            quest_objective_id=objective_id,
            actor_user_id=access.user_id,
            expected_row_version=body.expected_row_version,
        ),
    )
