"""Timeline authoring endpoints (Phase 14).

    POST /worlds/{world_id}/timelines                                   create root (timeline.manage)
    GET  /worlds/{world_id}/timelines/{timeline_id}                     detail (world.view)
    POST /worlds/{world_id}/timelines/{timeline_id}/update              (timeline.manage)
    GET  /worlds/{world_id}/timelines/{timeline_id}/branch-points       options (timeline.manage)
    POST /worlds/{world_id}/timelines/{timeline_id}/branches            branch (timeline.manage)
    POST /worlds/{world_id}/timelines/{timeline_id}/archive|restore     (timeline.manage)

Every timeline in a path is bound to the path's world: another world's timeline
is the same 404 as a missing one. Branch-point options and errors disclose only
world-time data, never event names or IDs.
"""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import Connection

from dnd_ai.commands.timelines import (
    BranchPoint,
    ExistingWorldTime,
    LatestPoint,
    TimelineMutationResult,
    archive_timeline,
    create_timeline,
    create_timeline_branch,
    restore_timeline,
    update_timeline,
)
from dnd_ai.domain.world_authority import TIMELINE_MANAGE, WORLD_VIEW, WorldAuthority
from dnd_ai.queries.timeline_detail import get_timeline_detail
from dnd_ai.queries.timelines import get_timeline_summary, list_branch_points

from ._authoring import (
    BaseAuthoringRequest,
    finish_actor_idempotency,
    start_actor_idempotency,
)
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .errors import InvalidCursorError, NotFoundError
from .pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    build_page,
    decode_typed_cursor,
)
from .world_access import require_world_capability
from .worlds import blocked_body, managed_campaign_body, timeline_summary_body

router = APIRouter(tags=["timelines"])

_BRANCH_POINT_KEYSET = "branch_points"


class CreateTimelineRequest(BaseAuthoringRequest):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)


class UpdateTimelineRequest(BaseAuthoringRequest):
    expected_row_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)


class TransitionTimelineRequest(BaseAuthoringRequest):
    expected_row_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=1000)


class ExistingWorldTimeRequest(BaseAuthoringRequest):
    kind: Literal["existing_world_time"]
    world_time_id: uuid.UUID


class LatestPointRequest(BaseAuthoringRequest):
    kind: Literal["latest"]
    label: str = Field(min_length=1, max_length=200)


class CreateBranchRequest(BaseAuthoringRequest):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    branch_point: Annotated[
        ExistingWorldTimeRequest | LatestPointRequest, Field(discriminator="kind")
    ]


def _timeline_path(authority: WorldAuthority, timeline_id: uuid.UUID) -> dict[str, str]:
    return {"world_id": str(authority.world_id), "timeline_id": str(timeline_id)}


@router.post("/worlds/{world_id}/timelines", status_code=201)
def create_timeline_endpoint(
    body: CreateTimelineRequest,
    authority: Annotated[WorldAuthority, Depends(require_world_capability(TIMELINE_MANAGE))],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    state = start_actor_idempotency(
        connection,
        actor_user_id=authority.user_id,
        idempotency_key=idempotency_key,
        command_name="create_timeline",
        payload={"world_id": str(authority.world_id), **body.model_dump(mode="json")},
        correlation_id=correlation_id,
    )
    if state.replay is not None:
        return state.replay
    result = create_timeline(
        connection,
        world_id=authority.world_id,
        actor_user_id=authority.user_id,
        name=body.name,
        description=body.description,
    )
    record_change_log(
        connection,
        change_action_code="created",
        schema_name="campaign",
        table_name="timelines",
        record_id=result.timeline_id,
        entity_id=None,
        world_id=authority.world_id,
        actor_user_id=authority.user_id,
        correlation_id=correlation_id,
        command_name="create_timeline",
        event_id=None,
    )
    response = {"timeline_id": str(result.timeline_id), "row_version": result.row_version}
    finish_actor_idempotency(connection, state, status_code=201, body=response)
    return response


@router.get("/worlds/{world_id}/timelines/{timeline_id}")
def get_timeline_endpoint(
    timeline_id: uuid.UUID,
    authority: Annotated[WorldAuthority, Depends(require_world_capability(WORLD_VIEW))],
    connection: Annotated[Connection, Depends(get_connection)],
) -> dict[str, Any]:
    detail = get_timeline_detail(
        connection,
        user_id=authority.user_id,
        world_id=authority.world_id,
        timeline_id=timeline_id,
    )
    if detail is None:
        raise NotFoundError()
    return {
        **timeline_summary_body(detail.summary),
        "children": [timeline_summary_body(c) for c in detail.children],
        "managed_campaigns": [managed_campaign_body(c) for c in detail.managed_campaigns],
        "available_actions": detail.available_actions,
        "blocked_actions": [blocked_body(b) for b in detail.blocked_actions],
    }


def _record_timeline_change(
    connection: Connection,
    *,
    result: TimelineMutationResult,
    action: str,
    command_name: str,
    user_id: uuid.UUID,
    correlation_id: str | None,
    reason: str | None,
) -> None:
    record_change_log(
        connection,
        change_action_code=action,
        schema_name="campaign",
        table_name="timelines",
        record_id=result.timeline_id,
        entity_id=None,
        world_id=result.world_id,
        actor_user_id=user_id,
        correlation_id=correlation_id,
        command_name=command_name,
        event_id=None,
        previous_status=result.previous_lifecycle_status,
        new_status=result.lifecycle_status if result.previous_lifecycle_status else None,
        changed_fields=result.changed_fields or None,
        reason=reason,
    )


@router.post("/worlds/{world_id}/timelines/{timeline_id}/update")
def update_timeline_endpoint(
    timeline_id: uuid.UUID,
    body: UpdateTimelineRequest,
    authority: Annotated[WorldAuthority, Depends(require_world_capability(TIMELINE_MANAGE))],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    state = start_actor_idempotency(
        connection,
        actor_user_id=authority.user_id,
        idempotency_key=idempotency_key,
        command_name="update_timeline",
        payload={**_timeline_path(authority, timeline_id), **body.model_dump(mode="json")},
        correlation_id=correlation_id,
    )
    if state.replay is not None:
        return state.replay
    result = update_timeline(
        connection,
        world_id=authority.world_id,
        timeline_id=timeline_id,
        actor_user_id=authority.user_id,
        expected_row_version=body.expected_row_version,
        name=body.name,
        description=body.description,
    )
    if result.changed:
        _record_timeline_change(
            connection,
            result=result,
            action="updated",
            command_name="update_timeline",
            user_id=authority.user_id,
            correlation_id=correlation_id,
            reason=None,
        )
    response = {"timeline_id": str(result.timeline_id), "row_version": result.row_version}
    finish_actor_idempotency(connection, state, status_code=200, body=response)
    return response


def _transition(
    *,
    command: Any,
    action: str,
    command_name: str,
    timeline_id: uuid.UUID,
    body: TransitionTimelineRequest,
    authority: WorldAuthority,
    connection: Connection,
    idempotency_key: str | None,
    correlation_id: str | None,
) -> Any:
    state = start_actor_idempotency(
        connection,
        actor_user_id=authority.user_id,
        idempotency_key=idempotency_key,
        command_name=command_name,
        payload={**_timeline_path(authority, timeline_id), **body.model_dump(mode="json")},
        correlation_id=correlation_id,
    )
    if state.replay is not None:
        return state.replay
    result: TimelineMutationResult = command(
        connection,
        world_id=authority.world_id,
        timeline_id=timeline_id,
        actor_user_id=authority.user_id,
        expected_row_version=body.expected_row_version,
        reason=body.reason,
    )
    _record_timeline_change(
        connection,
        result=result,
        action=action,
        command_name=command_name,
        user_id=authority.user_id,
        correlation_id=correlation_id,
        reason=body.reason.strip() if body.reason and body.reason.strip() else None,
    )
    response = {
        "timeline_id": str(result.timeline_id),
        "lifecycle_status": result.lifecycle_status,
        "row_version": result.row_version,
    }
    finish_actor_idempotency(connection, state, status_code=200, body=response)
    return response


@router.post("/worlds/{world_id}/timelines/{timeline_id}/archive")
def archive_timeline_endpoint(
    timeline_id: uuid.UUID,
    body: TransitionTimelineRequest,
    authority: Annotated[WorldAuthority, Depends(require_world_capability(TIMELINE_MANAGE))],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    return _transition(
        command=archive_timeline,
        action="archived",
        command_name="archive_timeline",
        timeline_id=timeline_id,
        body=body,
        authority=authority,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )


@router.post("/worlds/{world_id}/timelines/{timeline_id}/restore")
def restore_timeline_endpoint(
    timeline_id: uuid.UUID,
    body: TransitionTimelineRequest,
    authority: Annotated[WorldAuthority, Depends(require_world_capability(TIMELINE_MANAGE))],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    return _transition(
        command=restore_timeline,
        action="restored",
        command_name="restore_timeline",
        timeline_id=timeline_id,
        body=body,
        authority=authority,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )


@router.get("/worlds/{world_id}/timelines/{timeline_id}/branch-points")
def list_branch_points_endpoint(
    timeline_id: uuid.UUID,
    authority: Annotated[WorldAuthority, Depends(require_world_capability(TIMELINE_MANAGE))],
    connection: Annotated[Connection, Depends(get_connection)],
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
) -> dict[str, Any]:
    if (
        get_timeline_summary(connection, world_id=authority.world_id, timeline_id=timeline_id)
        is None
    ):
        raise NotFoundError()
    decoded = decode_typed_cursor(
        cursor, keyset=_BRANCH_POINT_KEYSET, fields=["int_or_none", "uuid"]
    )
    after: tuple[int, uuid.UUID] | None = None
    if decoded is not None:
        sort_key, world_time_id = decoded
        if not isinstance(sort_key, int) or not isinstance(world_time_id, uuid.UUID):
            raise InvalidCursorError()
        after = (sort_key, world_time_id)
    rows = list_branch_points(connection, parent_timeline_id=timeline_id, limit=limit, after=after)
    page = build_page(
        rows,
        limit=limit,
        keyset=_BRANCH_POINT_KEYSET,
        cursor_key=lambda r: (r.sort_key, r.world_time_id),
    )
    return {
        "items": [
            {
                "world_time_id": str(r.world_time_id),
                "label": r.label,
                "year": r.year,
                "month_number": r.month_number,
                "day": r.day,
                "sort_key": r.sort_key,
            }
            for r in page.items
        ],
        "next_cursor": page.next_cursor,
    }


@router.post("/worlds/{world_id}/timelines/{timeline_id}/branches", status_code=201)
def create_branch_endpoint(
    timeline_id: uuid.UUID,
    body: CreateBranchRequest,
    authority: Annotated[WorldAuthority, Depends(require_world_capability(TIMELINE_MANAGE))],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    state = start_actor_idempotency(
        connection,
        actor_user_id=authority.user_id,
        idempotency_key=idempotency_key,
        command_name="create_timeline_branch",
        payload={**_timeline_path(authority, timeline_id), **body.model_dump(mode="json")},
        correlation_id=correlation_id,
    )
    if state.replay is not None:
        return state.replay
    point: BranchPoint
    if isinstance(body.branch_point, ExistingWorldTimeRequest):
        point = ExistingWorldTime(world_time_id=body.branch_point.world_time_id)
    else:
        point = LatestPoint(label=body.branch_point.label)
    result = create_timeline_branch(
        connection,
        world_id=authority.world_id,
        parent_timeline_id=timeline_id,
        actor_user_id=authority.user_id,
        name=body.name,
        description=body.description,
        branch_point=point,
    )
    if result.created_world_time_id is not None:
        record_change_log(
            connection,
            change_action_code="created",
            schema_name="core",
            table_name="world_times",
            record_id=result.created_world_time_id,
            entity_id=None,
            world_id=authority.world_id,
            actor_user_id=authority.user_id,
            correlation_id=correlation_id,
            command_name="create_timeline_branch",
            event_id=None,
        )
    record_change_log(
        connection,
        change_action_code="created",
        schema_name="campaign",
        table_name="timelines",
        record_id=result.timeline_id,
        entity_id=None,
        world_id=authority.world_id,
        actor_user_id=authority.user_id,
        correlation_id=correlation_id,
        command_name="create_timeline_branch",
        event_id=None,
    )
    response = {
        "timeline_id": str(result.timeline_id),
        "branch_world_time_id": str(result.branch_world_time_id),
        "row_version": result.row_version,
    }
    finish_actor_idempotency(connection, state, status_code=201, body=response)
    return response
