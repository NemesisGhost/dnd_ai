"""Campaign-invitation creation and acceptance endpoints.

Exposes
`create_campaign_invitation` as `POST /campaigns/{campaign_id}/invitations`
and `accept_campaign_invitation` as `POST /campaign-invitations/accept`.

Authorization is asymmetric between the two routes, by design:
`create_campaign_invitation_endpoint` requires `access.manage` in the
target campaign, the same capability `dnd_ai.api.memberships` already
requires for direct membership creation. `accept_campaign_invitation_
endpoint` has no campaign to resolve a capability against at all — the
caller authenticates with `dnd_ai.api.auth.require_oidc_user_id`
only (Phase 11 workstream 2 correction: a `FoundrySystem` adapter
credential is rejected outright here, the same "no campaign_id to scope a
Foundry principal's world against, and not part of the bounded
adapter-facing surface" reasoning `dnd_ai.api.campaigns.create_campaign_
endpoint` now documents for its own identical case), and the invitation
*token itself* (in the request body, never the URL, so it never lands in
access logs) is the authorization credential, the same "no campaign yet"
shape `dnd_ai.api.campaigns.create_campaign_endpoint` already established.

Idempotency: `create_campaign_invitation` uses the same durable `security.
idempotent_requests` mechanism every other Phase 10 write endpoint with an
existing `campaign_id` uses. `accept_campaign_invitation` needs none — see
`dnd_ai.commands.campaign_invitations`'s own docstring for why redeeming
the same token twice is already a defined no-op.

Auditing: one `audit.change_log` row per successful call. `entity_id` is
always `None` (neither `security.campaign_invitations` nor `.campaign_
memberships` is a `core.entities` row). `world_id` for the accept route —
which has no `AccessContext` to resolve a timeline from — is looked up
directly from the invitation's own resolved `campaign_id`, the one place
in this router that needs a campaign-to-world lookup rather than a
timeline-to-world one.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection, text

from dnd_ai.commands.campaign_invitations import (
    accept_campaign_invitation,
    create_campaign_invitation,
)
from dnd_ai.domain.access import AccessContext

from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .auth import require_oidc_user_id
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .idempotency import IdempotentReplay, begin_idempotent_request, complete_idempotent_request

router = APIRouter(tags=["campaign_invitations"])

_ACCESS_MANAGE_CAPABILITY = "access.manage"
_CREATE_INVITATION_COMMAND_NAME = "create_campaign_invitation"
_ACCEPT_INVITATION_COMMAND_NAME = "accept_campaign_invitation"
_CREATED_CHANGE_ACTION = "created"
_UPDATED_CHANGE_ACTION = "updated"


class CreateCampaignInvitationRequest(BaseModel):
    invited_email: str | None = None


class CreateCampaignInvitationResponse(BaseModel):
    campaign_invitation_id: uuid.UUID
    token: str


class AcceptCampaignInvitationRequest(BaseModel):
    token: str


class AcceptCampaignInvitationResponse(BaseModel):
    campaign_id: uuid.UUID
    campaign_membership_id: uuid.UUID


@router.post(
    "/campaigns/{campaign_id}/invitations",
    response_model=CreateCampaignInvitationResponse,
    status_code=201,
)
def create_campaign_invitation_endpoint(
    campaign_id: uuid.UUID,
    body: CreateCampaignInvitationRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> CreateCampaignInvitationResponse:
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
            command_name=_CREATE_INVITATION_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return CreateCampaignInvitationResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = create_campaign_invitation(
        connection,
        campaign_id=campaign_id,
        invited_by_membership_id=access.campaign_membership_id,
        invited_email=body.invited_email,
    )

    record_change_log(
        connection,
        change_action_code=_CREATED_CHANGE_ACTION,
        schema_name="security",
        table_name="campaign_invitations",
        record_id=result.campaign_invitation_id,
        entity_id=None,
        world_id=timeline_world_id(connection, access.timeline_id),
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_CREATE_INVITATION_COMMAND_NAME,
        event_id=None,
    )

    response = CreateCampaignInvitationResponse(
        campaign_invitation_id=result.campaign_invitation_id, token=result.token
    )

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=201,
            response_body=response.model_dump(mode="json"),
        )

    return response


@router.post(
    "/campaign-invitations/accept",
    response_model=AcceptCampaignInvitationResponse,
    status_code=200,
)
def accept_campaign_invitation_endpoint(
    body: AcceptCampaignInvitationRequest,
    accepting_user_id: Annotated[uuid.UUID, Depends(require_oidc_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> AcceptCampaignInvitationResponse:
    result = accept_campaign_invitation(
        connection, token=body.token, accepting_user_id=accepting_user_id
    )

    world_id = connection.execute(
        text("""
            SELECT t.world_id FROM campaign.campaigns c
            JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
            WHERE c.campaign_id = :campaign
        """),
        {"campaign": result.campaign_id},
    ).scalar()

    record_change_log(
        connection,
        change_action_code=_UPDATED_CHANGE_ACTION,
        schema_name="security",
        table_name="campaign_memberships",
        record_id=result.campaign_membership_id,
        entity_id=None,
        world_id=world_id,
        actor_user_id=accepting_user_id,
        correlation_id=correlation_id,
        command_name=_ACCEPT_INVITATION_COMMAND_NAME,
        event_id=None,
    )

    return AcceptCampaignInvitationResponse(
        campaign_id=result.campaign_id, campaign_membership_id=result.campaign_membership_id
    )
