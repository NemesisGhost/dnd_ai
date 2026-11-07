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
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from dnd_ai.commands.character_reveal import (
    grant_character_reveal_delegation,
    revoke_character_reveal_delegation,
)
from dnd_ai.domain.access import AccessContext

from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection

router = APIRouter(tags=["character-reveal"])

_ACCESS_MANAGE_CAPABILITY = "access.manage"

_GRANT_COMMAND_NAME = "grant_character_reveal_delegation"
_REVOKE_COMMAND_NAME = "revoke_character_reveal_delegation"

_CREATED_CHANGE_ACTION = "created"
_UPDATED_CHANGE_ACTION = "updated"


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
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> GrantCharacterRevealDelegationResponse:
    """Delegates `character.reveal` to a member holding the built-in `gm` role. `granted` is
    false when the member already held a current delegation (nothing written, nothing audited)."""
    result = grant_character_reveal_delegation(
        connection,
        campaign_id=campaign_id,
        actor_membership_id=access.campaign_membership_id,
        grantee_campaign_membership_id=body.grantee_campaign_membership_id,
        reason=body.reason,
    )
    if result.created:
        record_change_log(
            connection,
            change_action_code=_CREATED_CHANGE_ACTION,
            schema_name="security",
            table_name="character_reveal_delegations",
            record_id=result.character_reveal_delegation_id,
            entity_id=None,
            world_id=timeline_world_id(connection, access.timeline_id),
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=_GRANT_COMMAND_NAME,
            event_id=None,
            changed_fields={
                "grantee_campaign_membership_id": str(result.grantee_campaign_membership_id),
                "gm_membership_role_id": str(result.gm_membership_role_id),
                "replaced_stale_delegation": bool(result.replaced_stale_delegation_ids),
            },
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
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> RevokeCharacterRevealDelegationResponse:
    """Revokes the member's live delegation. `revoked` is false when they held none (nothing
    written, nothing audited)."""
    result = revoke_character_reveal_delegation(
        connection,
        campaign_id=campaign_id,
        actor_membership_id=access.campaign_membership_id,
        grantee_campaign_membership_id=grantee_campaign_membership_id,
        reason=body.reason,
    )
    if result.revoked:
        assert result.character_reveal_delegation_id is not None
        record_change_log(
            connection,
            change_action_code=_UPDATED_CHANGE_ACTION,
            schema_name="security",
            table_name="character_reveal_delegations",
            record_id=result.character_reveal_delegation_id,
            entity_id=None,
            world_id=timeline_world_id(connection, access.timeline_id),
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=_REVOKE_COMMAND_NAME,
            event_id=None,
            changed_fields={
                "grantee_campaign_membership_id": str(result.grantee_campaign_membership_id),
                "revoked": True,
            },
        )
    return RevokeCharacterRevealDelegationResponse(
        grantee_campaign_membership_id=result.grantee_campaign_membership_id,
        revoked=result.revoked,
    )
