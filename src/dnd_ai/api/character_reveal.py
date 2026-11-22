"""Reveal-delegation command endpoints (P03-A A1).

Exposes `grant_character_reveal_delegation` and `revoke_character_reveal_delegation` over HTTP on the
same OIDC authentication, request transaction and access resolution every other command router
uses. A live built-in `campaign_owner` is the only actor who can grant or revoke a delegation of
`character.reveal` to a member holding the built-in `gm` role.

Authorization: the routes require the `access.manage` role capability, like every other route that
changes who can act in a campaign, as a coarse first filter that keeps players and GMs out before
the body is read. It is not the authority: the commands re-read the caller's live built-in owner
assignment under lock (`CampaignOwnerRequiredError`, 403 `campaign_owner_required`), so a custom
`access.manage` holder is refused, and a refused call writes nothing and no audit row.

Auditing: one `audit.change_log` row per actual change (`security.character_reveal_delegations`,
`record_id` the delegation); an idempotent repeat that changes nothing writes none.

R01 S5-E6 (plan 6.36): both routes are **unkeyed pre-write plans** (`dnd_ai.commands.reveal_delegation_plans`,
`R01_UNKEYED_PRE_WRITE_ROUTES`). Every lock and refusal precedes `plan.finalize`; the writes and the audit row are
declared steps after it. They stay non-idempotent through a reservation: an `Idempotency-Key` header is ignored.
`dnd_ai.commands.character_reveal` stays as the direct, unguarded command and the oracle of the route tests.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from dnd_ai.commands.reveal_delegation_plans import (
    prepare_grant,
    prepare_revoke,
    write_grant,
    write_revoke,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authorization import AuthorizationPlan
from dnd_ai.queries.reveal_delegations import get_reveal_delegation_state

from .access import require_campaign_capability
from .correlation import get_request_correlation_id
from .deps import get_connection
from .r01_route_plans import get_authorization_plan

router = APIRouter(tags=["character-reveal"])

_ACCESS_MANAGE_CAPABILITY = "access.manage"

_Plan = Annotated[AuthorizationPlan, Depends(get_authorization_plan)]


class GrantCharacterRevealDelegationRequest(BaseModel):
    grantee_campaign_membership_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=1000)


class GrantCharacterRevealDelegationResponse(BaseModel):
    grantee_campaign_membership_id: uuid.UUID
    character_reveal_delegation_id: uuid.UUID
    granted: bool


class RevokeCharacterRevealDelegationRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class RevokeCharacterRevealDelegationResponse(BaseModel):
    grantee_campaign_membership_id: uuid.UUID
    revoked: bool


class RevealDelegationResponse(BaseModel):
    """Who holds reveal authority by delegation. No reason, id of a delegation or role, or ended row."""

    granted_at: datetime
    granted_by_name: str | None


class RevealDelegationMemberResponse(BaseModel):
    campaign_membership_id: uuid.UUID
    display_name: str
    delegation: RevealDelegationResponse | None


class LapsedRevealDelegationResponse(BaseModel):
    campaign_membership_id: uuid.UUID
    display_name: str
    granted_at: datetime
    granted_by_name: str | None


class RevealDelegationStateResponse(BaseModel):
    can_manage: bool
    members: list[RevealDelegationMemberResponse]
    lapsed_delegations: list[LapsedRevealDelegationResponse]


@router.get(
    "/campaigns/{campaign_id}/reveal-delegations",
    response_model=RevealDelegationStateResponse,
    status_code=200,
)
def get_reveal_delegation_state_endpoint(
    campaign_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> RevealDelegationStateResponse:
    """The current reveal-delegation state (read-only, `access.manage`, P15-C02-S03).

    `can_manage` is whether the caller holds a live built-in owner assignment (a custom `access.manage` holder
    reads but cannot grant or revoke); `members` lists every live built-in GM with the delegation that
    authorizes them, if any; `lapsed_delegations` lists open delegations whose grantee holds no live built-in
    GM assignment (they authorize nothing and the existing revoke route can close them). Writes nothing and
    takes no lock."""
    state = get_reveal_delegation_state(
        connection,
        campaign_id=campaign_id,
        caller_campaign_membership_id=access.campaign_membership_id,
    )
    return RevealDelegationStateResponse(
        can_manage=state.can_manage,
        members=[
            RevealDelegationMemberResponse(
                campaign_membership_id=m.campaign_membership_id,
                display_name=m.display_name,
                delegation=(
                    RevealDelegationResponse(
                        granted_at=m.delegation.granted_at,
                        granted_by_name=m.delegation.granted_by_name,
                    )
                    if m.delegation is not None
                    else None
                ),
            )
            for m in state.members
        ],
        lapsed_delegations=[
            LapsedRevealDelegationResponse(
                campaign_membership_id=x.campaign_membership_id,
                display_name=x.display_name,
                granted_at=x.delegation.granted_at,
                granted_by_name=x.delegation.granted_by_name,
            )
            for x in state.lapsed_delegations
        ],
    )


@router.post(
    "/campaigns/{campaign_id}/reveal-delegations",
    response_model=GrantCharacterRevealDelegationResponse,
    status_code=200,
)
def grant_character_reveal_delegation_endpoint(
    campaign_id: uuid.UUID,
    body: GrantCharacterRevealDelegationRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> GrantCharacterRevealDelegationResponse:
    """Delegates `character.reveal` to a member holding the built-in `gm` role. `granted` is
    false when the member already held a current delegation (nothing written, nothing audited).

    An **unkeyed** pre-write route (R01 S5-E6): the owner and grantee checks and every lock precede
    `plan.finalize`; the closure of a stale delegation, the insert and the audit row are declared steps."""
    prepared = prepare_grant(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_membership_id=access.campaign_membership_id,
        grantee_campaign_membership_id=body.grantee_campaign_membership_id,
        reason=body.reason,
    )
    plan.finalize(connection)
    result = write_grant(
        connection,
        plan,
        prepared,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        grantee_campaign_membership_id=body.grantee_campaign_membership_id,
        correlation_id=correlation_id,
    )
    return GrantCharacterRevealDelegationResponse(
        grantee_campaign_membership_id=result.grantee_campaign_membership_id,
        character_reveal_delegation_id=result.character_reveal_delegation_id,
        granted=result.created,
    )


@router.post(
    "/campaigns/{campaign_id}/reveal-delegations/{grantee_campaign_membership_id}/revoke",
    response_model=RevokeCharacterRevealDelegationResponse,
    status_code=200,
)
def revoke_character_reveal_delegation_endpoint(
    campaign_id: uuid.UUID,
    grantee_campaign_membership_id: uuid.UUID,
    body: RevokeCharacterRevealDelegationRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> RevokeCharacterRevealDelegationResponse:
    """Revokes the member's live delegation. `revoked` is false when they held none (nothing
    written, nothing audited). An **unkeyed** pre-write route (R01 S5-E6), like the grant."""
    prepared = prepare_revoke(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_membership_id=access.campaign_membership_id,
        grantee_campaign_membership_id=grantee_campaign_membership_id,
        reason=body.reason,
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
    return RevokeCharacterRevealDelegationResponse(
        grantee_campaign_membership_id=result.grantee_campaign_membership_id,
        revoked=result.revoked,
    )
