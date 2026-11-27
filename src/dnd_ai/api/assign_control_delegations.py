"""Assign-control delegation endpoints (P15-C11-S02-T02, ADR 0021 OD-4a).

A live built-in `campaign_owner` or `gm` delegates `character.assign_control` to a member who holds the built-in
`assistant_gm` role in the same campaign, and revokes the delegation again. The recipient then uses the assign, replace
and revoke control routes of this campaign (and only this campaign) and cannot delegate further. This is not a reveal
delegation: no shared table, function or route (`dnd_ai.api.character_reveal` is the reveal one).

Authorization: the route requirement is `campaign.view`; the operation authority (a live built-in owner or GM) is judged
by the plan before any target lookup and again after the last lock wait and at `plan.finalize`, so a refusal is the one
fixed 403 `character_assign_control_required` for every kind of non-holder. The body is taken as a plain mapping and
validated after the authority (403 before 422).

Both writers are **unkeyed pre-write plans** (`dnd_ai.commands.assign_control_delegation_plans`,
`R01_UNKEYED_PRE_WRITE_ROUTES`): an `Idempotency-Key` header is ignored, a repeated grant returns 200 with nothing
written, and a revoke with no live delegation is a 200 no-op. The read is limited to the same holders.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Response
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.commands.assign_control_delegation_plans import (
    prepare_grant,
    prepare_revoke,
    write_grant,
    write_revoke,
)
from dnd_ai.commands.control_assignment_plans import AssignControlRequiredError
from dnd_ai.domain.access import AccessContext, read_authority_snapshot
from dnd_ai.domain.authorization import AuthorizationPlan
from dnd_ai.queries.assign_control_delegations import get_assign_control_delegations

from .access import require_campaign_capability
from .correlation import get_request_correlation_id
from .deps import get_connection
from .r01_route_plans import get_authorization_plan

router = APIRouter(tags=["assign-control-delegations"])

_VIEW = "campaign.view"
_Plan = Annotated[AuthorizationPlan, Depends(get_authorization_plan)]
_Body = Annotated[dict[str, Any], Body()]


class DelegateAssignControlResponse(BaseModel):
    grantee_campaign_membership_id: uuid.UUID
    character_assign_control_delegation_id: uuid.UUID
    granted: bool


class RevokeAssignControlDelegationResponse(BaseModel):
    grantee_campaign_membership_id: uuid.UUID
    revoked: bool


class AssignControlDelegationResponse(BaseModel):
    delegation_id: uuid.UUID
    grantee_campaign_membership_id: uuid.UUID
    display_name: str
    status: str
    status_text: str
    in_force: bool
    reason: str
    granted_at: datetime
    granted_by: str | None
    revoked_at: datetime | None
    revoked_by: str | None
    revocation_reason: str | None
    end_reason: str | None


class AssignControlDelegationsResponse(BaseModel):
    delegations: list[AssignControlDelegationResponse]
    truncated: bool


@router.get(
    "/campaigns/{campaign_id}/assign-control-delegations",
    response_model=AssignControlDelegationsResponse,
    status_code=200,
)
def get_assign_control_delegations_endpoint(
    campaign_id: uuid.UUID,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_VIEW))],
    connection: Annotated[Connection, Depends(get_connection)],
) -> AssignControlDelegationsResponse:
    """Every delegation of the campaign, live and closed, newest first (at most 200, with `truncated`), each with its
    in-force status, reasons and actors. Limited to a live built-in owner or GM (a delegated holder is refused: it may
    not manage delegations). Writes nothing and takes no lock."""
    snapshot = read_authority_snapshot(
        connection,
        user_id=access.user_id,
        campaign_id=campaign_id,
        with_assign_control=True,
    )
    if snapshot.assign_control_authority not in ("campaign_owner", "gm"):
        raise AssignControlRequiredError(
            f"membership {access.campaign_membership_id} holds no live owner or gm assignment "
            f"in campaign {campaign_id}"
        )
    state = get_assign_control_delegations(connection, campaign_id=campaign_id)
    return AssignControlDelegationsResponse(
        delegations=[AssignControlDelegationResponse(**vars(row)) for row in state.delegations],
        truncated=state.truncated,
    )


@router.post(
    "/campaigns/{campaign_id}/assign-control-delegations",
    response_model=DelegateAssignControlResponse,
    status_code=201,
)
def delegate_character_assign_control_endpoint(
    campaign_id: uuid.UUID,
    body: _Body,
    response: Response,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_VIEW))],
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> DelegateAssignControlResponse:
    """Delegates `character.assign_control` to a member holding the built-in `assistant_gm` role. 201 when a delegation
    was created; 200 `granted: false` when the member already holds one bound to their current `assistant_gm`
    assignment (nothing written, nothing audited). An **unkeyed** pre-write route."""
    prepared = prepare_grant(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        raw=body,
    )
    plan.finalize(connection)
    result = write_grant(
        connection,
        plan,
        prepared,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        grantee_campaign_membership_id=prepared.grantee,
        correlation_id=correlation_id,
    )
    response.status_code = 201 if result.created else 200
    return DelegateAssignControlResponse(
        grantee_campaign_membership_id=result.grantee_campaign_membership_id,
        character_assign_control_delegation_id=result.character_assign_control_delegation_id,
        granted=result.created,
    )


@router.post(
    "/campaigns/{campaign_id}/assign-control-delegations/{grantee_campaign_membership_id}/revoke",
    response_model=RevokeAssignControlDelegationResponse,
    status_code=200,
)
def revoke_character_assign_control_delegation_endpoint(
    campaign_id: uuid.UUID,
    grantee_campaign_membership_id: uuid.UUID,
    body: _Body,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_VIEW))],
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> RevokeAssignControlDelegationResponse:
    """Revokes the member's live delegation. `revoked` is false when they held none (nothing written, nothing audited).
    The assignments the holder already made are untouched. An **unkeyed** pre-write route, like the grant."""
    prepared = prepare_revoke(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_membership_id=access.campaign_membership_id,
        grantee_campaign_membership_id=grantee_campaign_membership_id,
        raw=body,
    )
    plan.finalize(connection)
    result = write_revoke(
        connection,
        plan,
        prepared,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        grantee_campaign_membership_id=grantee_campaign_membership_id,
        correlation_id=correlation_id,
    )
    return RevokeAssignControlDelegationResponse(
        grantee_campaign_membership_id=result.grantee_campaign_membership_id,
        revoked=result.revoked,
    )
