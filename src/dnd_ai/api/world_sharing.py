"""World sharing endpoints (docs/adr/0020-scoped-system-world-and-campaign-roles.md).

    GET  /worlds/{world_id}/access                           (world.share)
    POST /worlds/{world_id}/roles                            (world.share; owner: world.transfer)
    POST /worlds/{world_id}/roles/{world_membership_id}/end  (world.share; owner: world.transfer)
    POST /worlds/{world_id}/use-grants                       (world.share)
    POST /worlds/{world_id}/use-grants/{id}/revoke           (world.share)
    POST /worlds/{world_id}/ownership-transfer               (world.transfer)

Every route is human-only and resolves the caller's authority for the *target
world* (`require_world_capability`), so a campaign role, a system role, or authority
over a different world never reaches it; a caller with no authority gets the usual
non-disclosing 404, and an Owner whose system GM was revoked (so `world.share` is
withheld, decision D11) gets 403. The command re-checks under the world row lock.

Mutations accept an optional `Idempotency-Key` (the actor-scoped store, shared with
the other world routes) and are naturally idempotent without one: assigning a role
already held, or a use grant already open, is a 200 no-op that writes no audit row.
Each real change writes one `audit.change_log` row (no credentials, no tokens).
"""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import Field
from sqlalchemy import Connection

from dnd_ai.commands.world_access import (
    WorldAccessChange,
    assign_world_role,
    end_world_role,
    grant_world_use,
    revoke_world_use,
    transfer_world_ownership,
)
from dnd_ai.domain.world_authority import WORLD_SHARE, WORLD_TRANSFER, WorldAuthority
from dnd_ai.queries.world_access import list_world_access

from ._authoring import (
    BaseAuthoringRequest,
    finish_actor_idempotency,
    start_actor_idempotency,
)
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .world_access import require_world_capability

router = APIRouter(tags=["world-sharing"])

WorldRoleCode = Literal[
    "world_owner", "world_viewer", "world_editor", "world_reviewer", "world_reader"
]
RetainedRoleCode = Literal["world_viewer", "world_editor", "world_reviewer", "world_reader"]


class AssignWorldRoleRequest(BaseAuthoringRequest):
    login_name: str = Field(min_length=1, max_length=200)
    role_code: WorldRoleCode


class GrantWorldUseRequest(BaseAuthoringRequest):
    login_name: str = Field(min_length=1, max_length=200)


class TransferOwnershipRequest(BaseAuthoringRequest):
    login_name: str = Field(min_length=1, max_length=200)
    retain_previous_owner_as: RetainedRoleCode | None = None


def _audit(
    connection: Connection,
    *,
    action: str,
    table_name: str,
    record_id: uuid.UUID | None,
    world_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    correlation_id: str | None,
    command_name: str,
    changed_fields: dict[str, object],
) -> None:
    record_change_log(
        connection,
        change_action_code=action,
        schema_name="security",
        table_name=table_name,
        record_id=record_id,
        entity_id=None,
        world_id=world_id,
        actor_user_id=actor_user_id,
        correlation_id=correlation_id,
        command_name=command_name,
        event_id=None,
        changed_fields=changed_fields,
    )


def _change_body(change: WorldAccessChange) -> dict[str, Any]:
    return {
        "world_id": str(change.world_id),
        "user_id": str(change.target_user_id),
        "record_id": None if change.record_id is None else str(change.record_id),
        "role_code": change.role_code,
        "changed": change.changed,
    }


@router.get("/worlds/{world_id}/access")
def get_world_access_endpoint(
    authority: Annotated[WorldAuthority, Depends(require_world_capability(WORLD_SHARE))],
    connection: Annotated[Connection, Depends(get_connection)],
) -> dict[str, Any]:
    view = list_world_access(connection, world_id=authority.world_id)
    return {
        "assignments": [
            {
                "world_membership_id": str(a.world_membership_id),
                "user_id": str(a.user_id),
                "display_name": a.display_name,
                "role_code": a.role_code,
                "role_display_name": a.role_display_name,
                "granted_at": a.granted_at.isoformat(),
                "granted_by_display_name": a.granted_by_display_name,
                "account_active": a.account_active,
            }
            for a in view.assignments
        ],
        "use_grants": [
            {
                "world_use_grant_id": str(g.world_use_grant_id),
                "user_id": str(g.user_id),
                "display_name": g.display_name,
                "granted_at": g.granted_at.isoformat(),
                "granted_by_display_name": g.granted_by_display_name,
                "account_active": g.account_active,
            }
            for g in view.use_grants
        ],
        "may_transfer": authority.has_capability(WORLD_TRANSFER),
    }


@router.post("/worlds/{world_id}/roles")
def assign_world_role_endpoint(
    body: AssignWorldRoleRequest,
    response: Response,
    authority: Annotated[WorldAuthority, Depends(require_world_capability(WORLD_SHARE))],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    state = start_actor_idempotency(
        connection,
        actor_user_id=authority.user_id,
        idempotency_key=idempotency_key,
        command_name="assign_world_role",
        payload={**body.model_dump(mode="json"), "world_id": str(authority.world_id)},
        correlation_id=correlation_id,
    )
    if state.replay is not None:
        return state.replay
    change = assign_world_role(
        connection,
        actor_user_id=authority.user_id,
        world_id=authority.world_id,
        login_name=body.login_name,
        role_code=body.role_code,
    )
    status_code = 201 if change.changed else 200
    if change.changed:
        _audit(
            connection,
            action="created",
            table_name="world_memberships",
            record_id=change.record_id,
            world_id=authority.world_id,
            actor_user_id=authority.user_id,
            correlation_id=correlation_id,
            command_name="assign_world_role",
            changed_fields={
                "world_role_code": body.role_code,
                "target_user_id": str(change.target_user_id),
            },
        )
    payload = _change_body(change)
    finish_actor_idempotency(connection, state, status_code=status_code, body=payload)
    response.status_code = status_code
    return payload


@router.post("/worlds/{world_id}/roles/{world_membership_id}/end")
def end_world_role_endpoint(
    world_membership_id: uuid.UUID,
    authority: Annotated[WorldAuthority, Depends(require_world_capability(WORLD_SHARE))],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    state = start_actor_idempotency(
        connection,
        actor_user_id=authority.user_id,
        idempotency_key=idempotency_key,
        command_name="end_world_role",
        payload={
            "world_id": str(authority.world_id),
            "world_membership_id": str(world_membership_id),
        },
        correlation_id=correlation_id,
    )
    if state.replay is not None:
        return state.replay
    change = end_world_role(
        connection,
        actor_user_id=authority.user_id,
        world_id=authority.world_id,
        world_membership_id=world_membership_id,
    )
    _audit(
        connection,
        action="updated",
        table_name="world_memberships",
        record_id=change.record_id,
        world_id=authority.world_id,
        actor_user_id=authority.user_id,
        correlation_id=correlation_id,
        command_name="end_world_role",
        changed_fields={
            "world_role_code": change.role_code,
            "target_user_id": str(change.target_user_id),
            "ended": True,
        },
    )
    payload = _change_body(change)
    finish_actor_idempotency(connection, state, status_code=200, body=payload)
    return payload


@router.post("/worlds/{world_id}/use-grants")
def grant_world_use_endpoint(
    body: GrantWorldUseRequest,
    response: Response,
    authority: Annotated[WorldAuthority, Depends(require_world_capability(WORLD_SHARE))],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    state = start_actor_idempotency(
        connection,
        actor_user_id=authority.user_id,
        idempotency_key=idempotency_key,
        command_name="grant_world_use",
        payload={**body.model_dump(mode="json"), "world_id": str(authority.world_id)},
        correlation_id=correlation_id,
    )
    if state.replay is not None:
        return state.replay
    change = grant_world_use(
        connection,
        actor_user_id=authority.user_id,
        world_id=authority.world_id,
        login_name=body.login_name,
    )
    status_code = 201 if change.changed else 200
    if change.changed:
        _audit(
            connection,
            action="created",
            table_name="world_use_grants",
            record_id=change.record_id,
            world_id=authority.world_id,
            actor_user_id=authority.user_id,
            correlation_id=correlation_id,
            command_name="grant_world_use",
            changed_fields={"target_user_id": str(change.target_user_id)},
        )
    payload = _change_body(change)
    finish_actor_idempotency(connection, state, status_code=status_code, body=payload)
    response.status_code = status_code
    return payload


@router.post("/worlds/{world_id}/use-grants/{world_use_grant_id}/revoke")
def revoke_world_use_endpoint(
    world_use_grant_id: uuid.UUID,
    authority: Annotated[WorldAuthority, Depends(require_world_capability(WORLD_SHARE))],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    state = start_actor_idempotency(
        connection,
        actor_user_id=authority.user_id,
        idempotency_key=idempotency_key,
        command_name="revoke_world_use",
        payload={
            "world_id": str(authority.world_id),
            "world_use_grant_id": str(world_use_grant_id),
        },
        correlation_id=correlation_id,
    )
    if state.replay is not None:
        return state.replay
    change = revoke_world_use(
        connection,
        actor_user_id=authority.user_id,
        world_id=authority.world_id,
        world_use_grant_id=world_use_grant_id,
    )
    _audit(
        connection,
        action="updated",
        table_name="world_use_grants",
        record_id=change.record_id,
        world_id=authority.world_id,
        actor_user_id=authority.user_id,
        correlation_id=correlation_id,
        command_name="revoke_world_use",
        changed_fields={"target_user_id": str(change.target_user_id), "revoked": True},
    )
    payload = _change_body(change)
    finish_actor_idempotency(connection, state, status_code=200, body=payload)
    return payload


@router.post("/worlds/{world_id}/ownership-transfer")
def transfer_world_ownership_endpoint(
    body: TransferOwnershipRequest,
    authority: Annotated[WorldAuthority, Depends(require_world_capability(WORLD_TRANSFER))],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    state = start_actor_idempotency(
        connection,
        actor_user_id=authority.user_id,
        idempotency_key=idempotency_key,
        command_name="transfer_world_ownership",
        payload={**body.model_dump(mode="json"), "world_id": str(authority.world_id)},
        correlation_id=correlation_id,
    )
    if state.replay is not None:
        return state.replay
    result = transfer_world_ownership(
        connection,
        actor_user_id=authority.user_id,
        world_id=authority.world_id,
        login_name=body.login_name,
        retain_previous_owner_as=body.retain_previous_owner_as,
    )
    _audit(
        connection,
        action="updated",
        table_name="world_memberships",
        record_id=result.ended_membership_id,
        world_id=authority.world_id,
        actor_user_id=authority.user_id,
        correlation_id=correlation_id,
        command_name="transfer_world_ownership",
        changed_fields={
            "previous_owner_user_id": str(result.previous_owner_user_id),
            "new_owner_user_id": str(result.new_owner_user_id),
            "retained_role_code": result.retained_role_code,
        },
    )
    payload = {
        "world_id": str(result.world_id),
        "previous_owner_user_id": str(result.previous_owner_user_id),
        "new_owner_user_id": str(result.new_owner_user_id),
        "retained_role_code": result.retained_role_code,
    }
    finish_actor_idempotency(connection, state, status_code=200, body=payload)
    return payload
