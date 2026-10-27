"""World authoring endpoints (Phase 14, docs/adr/0014-world-authoring-authority.md).

    GET  /worlds                          worlds the caller holds authority over
    POST /worlds                          create (world.create: an active platform
                                          administrator or effective built-in gm)
    GET  /worlds/{world_id}               detail with server-computed actions (world.view)
    POST /worlds/{world_id}/update        (world.manage)
    POST /worlds/{world_id}/archive       (world.manage)
    POST /worlds/{world_id}/restore       (world.manage)

Every route builds on `require_human_user_id` / `require_world_capability`, so
Foundry device principals get 403 and cookie-session callers pass CSRF and
Origin checks (inherited from `get_authenticated_user_id`). `POST /worlds`
additionally refuses a human who may not create worlds with 403 `forbidden`
(docs/adr/0018-world-creation-eligibility.md): the route checks before touching
the idempotency store — so a refused caller can neither reserve a key nor
replay an earlier success — and `create_world` re-checks authoritatively in the
same transaction. A missing,
unclaimed, or someone-else's world is the same 404. Mutations use the
actor-scoped idempotency store and write one `audit.change_log` row per
durable record, sharing the request correlation ID. Reasons are stored in the
audit trail and never returned.
"""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import Connection, text

from dnd_ai.commands.worlds import (
    WorldMutationResult,
    archive_world,
    create_world,
    restore_world,
    update_world,
)
from dnd_ai.domain.authoring import WorldCreationNotAuthorizedError
from dnd_ai.domain.world_authority import (
    CAMPAIGN_CREATE,
    TIMELINE_MANAGE,
    WORLD_MANAGE,
    WORLD_VIEW,
    WorldAuthority,
)
from dnd_ai.queries.world_authority import may_create_worlds
from dnd_ai.queries.worlds import WorldDetail, WorldSummary, get_world_detail, list_worlds

from ._authoring import (
    BaseAuthoringRequest,
    finish_actor_idempotency,
    start_actor_idempotency,
)
from .audit import record_change_log
from .auth import require_human_user_id
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .errors import NotFoundError
from .pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    build_page,
    decode_typed_cursor,
)
from .world_access import require_world_capability

router = APIRouter(tags=["worlds"])

_KEYSET = "worlds"


class TimelineSeed(BaseAuthoringRequest):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)


class CreateWorldRequest(BaseAuthoringRequest):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    ruleset_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    default_ruleset_id: uuid.UUID
    primary_timeline: TimelineSeed


class UpdateWorldRequest(BaseAuthoringRequest):
    expected_row_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)


class TransitionWorldRequest(BaseAuthoringRequest):
    expected_row_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=1000)


def world_summary_body(summary: WorldSummary) -> dict[str, Any]:
    return {
        "world_id": str(summary.world_id),
        "name": summary.name,
        "description": summary.description,
        "lifecycle_status": summary.lifecycle_status,
        "row_version": summary.row_version,
        "primary_timeline_id": (
            None if summary.primary_timeline_id is None else str(summary.primary_timeline_id)
        ),
        "capabilities": summary.capabilities,
        "role_codes": summary.role_codes,
        "has_use_grant": summary.has_use_grant,
    }


def timeline_summary_body(timeline: Any) -> dict[str, Any]:
    branch = timeline.branch_point
    return {
        "timeline_id": str(timeline.timeline_id),
        "name": timeline.name,
        "description": timeline.description,
        "is_primary": timeline.is_primary,
        "parent_timeline_id": (
            None if timeline.parent_timeline_id is None else str(timeline.parent_timeline_id)
        ),
        "branch_point": (
            None
            if branch is None
            else {
                "world_time_id": str(branch.world_time_id),
                "label": branch.label,
                "sort_key": branch.sort_key,
            }
        ),
        "lifecycle_status": timeline.lifecycle_status,
        "row_version": timeline.row_version,
    }


def managed_campaign_body(campaign: Any) -> dict[str, Any]:
    return {
        "campaign_id": str(campaign.campaign_id),
        "name": campaign.name,
        "lifecycle_status": campaign.lifecycle_status,
        "timeline_id": str(campaign.timeline_id),
    }


def blocked_body(blocked: Any) -> dict[str, str]:
    return {"action": blocked.action, "reason": blocked.reason}


def _detail_body(detail: WorldDetail, *, hosting: dict[uuid.UUID, str | None]) -> dict[str, Any]:
    return {
        **world_summary_body(detail.summary),
        "default_ruleset_id": (
            None if detail.default_ruleset_id is None else str(detail.default_ruleset_id)
        ),
        "allowed_rulesets": [
            {
                "ruleset_id": str(r.ruleset_id),
                "code": r.code,
                "display_name": r.display_name,
                "is_default": r.is_default,
                "current_version": (
                    None
                    if r.current_version is None
                    else {
                        "ruleset_version_id": str(r.current_version.ruleset_version_id),
                        "version_label": r.current_version.version_label,
                    }
                ),
            }
            for r in detail.allowed_rulesets
        ],
        "timelines": [
            {
                **timeline_summary_body(t),
                # Whether the caller may start a campaign on this timeline (D7): they need
                # `campaign.create`, and `timeline.manage` as well once it already hosts a
                # campaign. Presentation only; `create_campaign` re-checks under lock.
                "campaign_hosting": {
                    "eligible": hosting[t.timeline_id] is None,
                    "reason": hosting[t.timeline_id],
                },
            }
            for t in detail.timelines
        ],
        "managed_campaigns": [managed_campaign_body(c) for c in detail.managed_campaigns],
        "available_actions": detail.available_actions,
        "blocked_actions": [blocked_body(b) for b in detail.blocked_actions],
    }


def _campaign_hosting(
    connection: Connection, detail: WorldDetail, authority: WorldAuthority
) -> dict[uuid.UUID, str | None]:
    """Per timeline: `None` when the caller may start a campaign on it, else why not
    (`world_use_not_permitted`, or `timeline_in_use` when it already hosts a campaign and
    the caller lacks `timeline.manage`; decision D7)."""
    if not authority.has_capability(CAMPAIGN_CREATE):
        return {t.timeline_id: "world_use_not_permitted" for t in detail.timelines}
    used = set(
        connection.execute(
            text(
                "SELECT DISTINCT c.timeline_id FROM campaign.campaigns c "
                "JOIN campaign.timelines t ON t.timeline_id = c.timeline_id "
                "WHERE t.world_id = :w"
            ),
            {"w": detail.summary.world_id},
        ).scalars()
    )
    can_manage = authority.has_capability(TIMELINE_MANAGE)
    return {
        t.timeline_id: (None if (t.timeline_id not in used) or can_manage else "timeline_in_use")
        for t in detail.timelines
    }


@router.get("/worlds")
def list_worlds_endpoint(
    user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
    status: Annotated[Literal["active", "archived", "all"], Query()] = "active",
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
) -> dict[str, Any]:
    decoded = decode_typed_cursor(cursor, keyset=_KEYSET, fields=["str", "uuid"])
    after = None if decoded is None else (str(decoded[0]), decoded[1])
    rows = list_worlds(
        connection,
        user_id=user_id,
        status=status,
        limit=limit,
        after=after,  # type: ignore[arg-type]
    )
    page = build_page(
        rows, limit=limit, keyset=_KEYSET, cursor_key=lambda w: (w.sort_name, w.world_id)
    )
    return {
        "items": [world_summary_body(w) for w in page.items],
        "next_cursor": page.next_cursor,
    }


@router.post("/worlds", status_code=201)
def create_world_endpoint(
    body: CreateWorldRequest,
    user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    # Defense in depth ahead of the idempotency store; `create_world` repeats
    # this check as the authoritative one.
    if not may_create_worlds(connection, user_id=user_id):
        raise WorldCreationNotAuthorizedError(f"user {user_id} may not create worlds")
    state = start_actor_idempotency(
        connection,
        actor_user_id=user_id,
        idempotency_key=idempotency_key,
        command_name="create_world",
        payload=body.model_dump(mode="json"),
        correlation_id=correlation_id,
    )
    if state.replay is not None:
        return state.replay

    result = create_world(
        connection,
        creator_user_id=user_id,
        name=body.name,
        description=body.description,
        ruleset_ids=body.ruleset_ids,
        default_ruleset_id=body.default_ruleset_id,
        primary_timeline_name=body.primary_timeline.name,
        primary_timeline_description=body.primary_timeline.description,
    )
    for schema, table, record_id in (
        ("core", "worlds", result.world_id),
        ("security", "world_memberships", result.world_membership_id),
        ("campaign", "timelines", result.primary_timeline_id),
    ):
        record_change_log(
            connection,
            change_action_code="created",
            schema_name=schema,
            table_name=table,
            record_id=record_id,
            entity_id=None,
            world_id=result.world_id,
            actor_user_id=user_id,
            correlation_id=correlation_id,
            command_name="create_world",
            event_id=None,
        )
    response = {
        "world_id": str(result.world_id),
        "primary_timeline_id": str(result.primary_timeline_id),
        "row_version": result.row_version,
    }
    finish_actor_idempotency(connection, state, status_code=201, body=response)
    return response


@router.get("/worlds/{world_id}")
def get_world_endpoint(
    authority: Annotated[WorldAuthority, Depends(require_world_capability(WORLD_VIEW))],
    connection: Annotated[Connection, Depends(get_connection)],
) -> dict[str, Any]:
    detail = get_world_detail(
        connection,
        user_id=authority.user_id,
        world_id=authority.world_id,
        authority=authority,
    )
    if detail is None:  # raced with deletion; same non-disclosing 404
        raise NotFoundError()
    return _detail_body(detail, hosting=_campaign_hosting(connection, detail, authority))


def _record_world_change(
    connection: Connection,
    *,
    result: WorldMutationResult,
    action: str,
    command_name: str,
    user_id: uuid.UUID,
    correlation_id: str | None,
    reason: str | None,
) -> None:
    record_change_log(
        connection,
        change_action_code=action,
        schema_name="core",
        table_name="worlds",
        record_id=result.world_id,
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


@router.post("/worlds/{world_id}/update")
def update_world_endpoint(
    body: UpdateWorldRequest,
    authority: Annotated[WorldAuthority, Depends(require_world_capability(WORLD_MANAGE))],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    state = start_actor_idempotency(
        connection,
        actor_user_id=authority.user_id,
        idempotency_key=idempotency_key,
        command_name="update_world",
        payload={"world_id": str(authority.world_id), **body.model_dump(mode="json")},
        correlation_id=correlation_id,
    )
    if state.replay is not None:
        return state.replay
    result = update_world(
        connection,
        world_id=authority.world_id,
        actor_user_id=authority.user_id,
        expected_row_version=body.expected_row_version,
        name=body.name,
        description=body.description,
    )
    if result.changed:
        _record_world_change(
            connection,
            result=result,
            action="updated",
            command_name="update_world",
            user_id=authority.user_id,
            correlation_id=correlation_id,
            reason=None,
        )
    response = {"world_id": str(result.world_id), "row_version": result.row_version}
    finish_actor_idempotency(connection, state, status_code=200, body=response)
    return response


def _transition(
    *,
    command: Any,
    action: str,
    command_name: str,
    body: TransitionWorldRequest,
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
        payload={"world_id": str(authority.world_id), **body.model_dump(mode="json")},
        correlation_id=correlation_id,
    )
    if state.replay is not None:
        return state.replay
    result: WorldMutationResult = command(
        connection,
        world_id=authority.world_id,
        actor_user_id=authority.user_id,
        expected_row_version=body.expected_row_version,
        reason=body.reason,
    )
    _record_world_change(
        connection,
        result=result,
        action=action,
        command_name=command_name,
        user_id=authority.user_id,
        correlation_id=correlation_id,
        reason=body.reason.strip() if body.reason and body.reason.strip() else None,
    )
    response = {
        "world_id": str(result.world_id),
        "lifecycle_status": result.lifecycle_status,
        "row_version": result.row_version,
    }
    finish_actor_idempotency(connection, state, status_code=200, body=response)
    return response


@router.post("/worlds/{world_id}/archive")
def archive_world_endpoint(
    body: TransitionWorldRequest,
    authority: Annotated[WorldAuthority, Depends(require_world_capability(WORLD_MANAGE))],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    return _transition(
        command=archive_world,
        action="archived",
        command_name="archive_world",
        body=body,
        authority=authority,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )


@router.post("/worlds/{world_id}/restore")
def restore_world_endpoint(
    body: TransitionWorldRequest,
    authority: Annotated[WorldAuthority, Depends(require_world_capability(WORLD_MANAGE))],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    return _transition(
        command=restore_world,
        action="restored",
        command_name="restore_world",
        body=body,
        authority=authority,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
