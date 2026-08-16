"""Campaign membership and role-assignment command endpoints.

Exposes
`create_campaign_membership`, `assign_membership_role`, and
`revoke_membership_role` over HTTP, on the same already-delivered OIDC
authentication, transaction management, and access resolution every other
command router uses.

Every route runs on the request's own `get_connection` transaction — these
commands take a `Connection` directly (no `_impl`/engine-wrapper split;
see `dnd_ai.commands.memberships`' own docstring for why).

Authorization: all three routes require the `access.manage` role
capability in the target campaign — the capability this codebase's own
seed data (`database/seeds/security.capabilities.yaml`) names for exactly
this purpose, distinct from every other command router's `canon.edit`
(these routes change *who can act*, not *what is canonically true*).

Idempotency: `create_campaign_membership`/`assign_membership_role` use the
same durable, PostgreSQL-backed `security.idempotent_requests` mechanism
every other Phase 10 write endpoint uses — see `dnd_ai.api.items`'s module
docstring for the full concurrency argument. `revoke_membership_role`
needs no idempotency-key store: `dnd_ai.commands.memberships.
revoke_membership_role` is already a no-op on a retry, the same reasoning
`dnd_ai.api.encounters`' `end` route already relies on for its own
naturally-idempotent command.

Auditing: every successful call inserts one `audit.change_log` row
(`dnd_ai.api.audit.record_change_log`). `entity_id` is always `None` —
neither `security.campaign_memberships` nor `.membership_roles` is a
`core.entities` row (people and their campaign authorization are not world
entities), matching `audit.change_log.entity_id`'s own documented
contract, "the `core.entities` row this change concerns, *when there is
one*" (migration 007). `world_id` is resolved server-side from the
campaign's own pinned timeline (`dnd_ai.api._shared.timeline_world_id`),
the same "never trust a caller-supplied world/timeline pairing" rule every
other command router already applies.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.commands.memberships import (
    assign_membership_role,
    create_campaign_membership,
    revoke_membership_role,
)
from dnd_ai.domain.access import AccessContext

from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .idempotency import IdempotentReplay, begin_idempotent_request, complete_idempotent_request

router = APIRouter(tags=["memberships"])

# Access/role administration is distinct from canon mutation — see this
# module's docstring for why every route here requires it instead of
# canon.edit.
_ACCESS_MANAGE_CAPABILITY = "access.manage"

_CREATE_MEMBERSHIP_COMMAND_NAME = "create_campaign_membership"
_ASSIGN_ROLE_COMMAND_NAME = "assign_membership_role"
_REVOKE_ROLE_COMMAND_NAME = "revoke_membership_role"

_CREATED_CHANGE_ACTION = "created"
_UPDATED_CHANGE_ACTION = "updated"


# ---------------------------------------------------------------------------
# Request/response contracts
# ---------------------------------------------------------------------------


class CreateCampaignMembershipRequest(BaseModel):
    user_id: uuid.UUID


class CampaignMembershipResponse(BaseModel):
    campaign_membership_id: uuid.UUID


class AssignMembershipRoleRequest(BaseModel):
    role_id: uuid.UUID
    expires_at: datetime | None = None


class MembershipRoleResponse(BaseModel):
    membership_role_id: uuid.UUID


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/campaigns/{campaign_id}/memberships",
    response_model=CampaignMembershipResponse,
    status_code=201,
)
def create_campaign_membership_endpoint(
    campaign_id: uuid.UUID,
    body: CreateCampaignMembershipRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> CampaignMembershipResponse:
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "campaign_id": str(campaign_id),
            **body.model_dump(mode="json"),
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_CREATE_MEMBERSHIP_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return CampaignMembershipResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = create_campaign_membership(connection, campaign_id=campaign_id, user_id=body.user_id)

    record_change_log(
        connection,
        change_action_code=_CREATED_CHANGE_ACTION,
        schema_name="security",
        table_name="campaign_memberships",
        record_id=result.campaign_membership_id,
        entity_id=None,
        world_id=timeline_world_id(connection, access.timeline_id),
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_CREATE_MEMBERSHIP_COMMAND_NAME,
        event_id=None,
    )

    response = CampaignMembershipResponse(campaign_membership_id=result.campaign_membership_id)

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=201,
            response_body=response.model_dump(mode="json"),
        )

    return response


@router.post(
    "/campaigns/{campaign_id}/memberships/{campaign_membership_id}/roles",
    response_model=MembershipRoleResponse,
    status_code=201,
)
def assign_membership_role_endpoint(
    campaign_id: uuid.UUID,
    campaign_membership_id: uuid.UUID,
    body: AssignMembershipRoleRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> MembershipRoleResponse:
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "campaign_membership_id": str(campaign_membership_id),
            **body.model_dump(mode="json"),
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_ASSIGN_ROLE_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return MembershipRoleResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = assign_membership_role(
        connection,
        campaign_membership_id=campaign_membership_id,
        role_id=body.role_id,
        campaign_id=campaign_id,
        granted_by_membership_id=access.campaign_membership_id,
        expires_at=body.expires_at,
    )

    record_change_log(
        connection,
        change_action_code=_CREATED_CHANGE_ACTION,
        schema_name="security",
        table_name="membership_roles",
        record_id=result.membership_role_id,
        entity_id=None,
        world_id=timeline_world_id(connection, access.timeline_id),
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_ASSIGN_ROLE_COMMAND_NAME,
        event_id=None,
    )

    response = MembershipRoleResponse(membership_role_id=result.membership_role_id)

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=201,
            response_body=response.model_dump(mode="json"),
        )

    return response


@router.post(
    "/campaigns/{campaign_id}/memberships/roles/{membership_role_id}/revoke",
    status_code=204,
)
def revoke_membership_role_endpoint(
    campaign_id: uuid.UUID,
    membership_role_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> None:
    revoke_membership_role(
        connection, membership_role_id=membership_role_id, campaign_id=campaign_id
    )

    record_change_log(
        connection,
        change_action_code=_UPDATED_CHANGE_ACTION,
        schema_name="security",
        table_name="membership_roles",
        record_id=membership_role_id,
        entity_id=None,
        world_id=timeline_world_id(connection, access.timeline_id),
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_REVOKE_ROLE_COMMAND_NAME,
        event_id=None,
    )
