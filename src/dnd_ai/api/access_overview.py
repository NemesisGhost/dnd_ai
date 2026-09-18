"""Read-only GM campaign access overview (Phase 13E-A).

`GET /campaigns/{campaign_id}/access-overview` is the discovery/read half
of GM access management (docs/UI_DESIGN.md §6.4 "Access management"),
scoped to one campaign and gated on the same `access.manage` capability
`dnd_ai.api.memberships`/`dnd_ai.api.access_grants` require for every
mutation there — reviewing who currently has access is the same category
of action as changing it, not a lesser one. Returns every currently open
membership with its active roles, current character relationships, and
explicit membership-targeted resource grants; see
`dnd_ai.queries.access_overview` for the exact inclusion rules and this
increment's deliberately out-of-scope items (access-group grants, account
lifecycle status, invitations, non-character grant-target identity).

This is a pure read: no idempotency key, no `audit.change_log` row, no
mutation. The mutation endpoints remain `dnd_ai.api.memberships`/
`.access_grants`/`.campaign_invitations`, unchanged by this module.

Non-disclosure: a caller without an active membership, or without
`access.manage`, gets the same fixed 404/403 `require_campaign_capability`
already gives every other `access.manage` route — this route adds no new
error shape, so an unknown campaign and an unauthorized one remain
indistinguishable from each other, exactly like `dnd_ai.api.memberships`/
`.access_grants`.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.access_overview import get_campaign_access_overview

from .access import require_campaign_capability
from .deps import get_connection

router = APIRouter(tags=["access-overview"])

# Reviewing access is access administration, the same capability
# dnd_ai.api.memberships/.access_grants require for every mutation there —
# see this module's own docstring.
_ACCESS_MANAGE_CAPABILITY = "access.manage"


# ---------------------------------------------------------------------------
# Response contracts
# ---------------------------------------------------------------------------


class RoleSummaryResponse(BaseModel):
    role_id: uuid.UUID
    code: str
    display_name: str


class CharacterRelationshipSummaryResponse(BaseModel):
    membership_character_relationship_id: uuid.UUID
    character_id: uuid.UUID
    character_display_name: str
    relationship_type_code: str
    relationship_type_display_name: str
    granted_at: datetime
    expires_at: datetime | None


class ResourceGrantSummaryResponse(BaseModel):
    resource_grant_id: uuid.UUID
    capability_code: str
    capability_display_name: str
    effect: str
    target_type: str
    reason: str | None
    granted_at: datetime
    expires_at: datetime | None


class CampaignMemberSummaryResponse(BaseModel):
    campaign_membership_id: uuid.UUID
    display_name: str
    status_code: str
    status_display_name: str
    joined_at: datetime
    roles: list[RoleSummaryResponse]
    character_relationships: list[CharacterRelationshipSummaryResponse]
    grants: list[ResourceGrantSummaryResponse]


class CampaignAccessOverviewResponse(BaseModel):
    members: list[CampaignMemberSummaryResponse]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/campaigns/{campaign_id}/access-overview",
    response_model=CampaignAccessOverviewResponse,
    status_code=200,
)
def get_campaign_access_overview_endpoint(
    campaign_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> CampaignAccessOverviewResponse:
    members = get_campaign_access_overview(
        connection, campaign_id=campaign_id, timeline_id=access.timeline_id
    )
    return CampaignAccessOverviewResponse(
        members=[
            CampaignMemberSummaryResponse(
                campaign_membership_id=member.campaign_membership_id,
                display_name=member.display_name,
                status_code=member.status_code,
                status_display_name=member.status_display_name,
                joined_at=member.joined_at,
                roles=[
                    RoleSummaryResponse(
                        role_id=role.role_id, code=role.code, display_name=role.display_name
                    )
                    for role in member.roles
                ],
                character_relationships=[
                    CharacterRelationshipSummaryResponse(
                        membership_character_relationship_id=(
                            relationship.membership_character_relationship_id
                        ),
                        character_id=relationship.character_id,
                        character_display_name=relationship.character_display_name,
                        relationship_type_code=relationship.relationship_type_code,
                        relationship_type_display_name=(
                            relationship.relationship_type_display_name
                        ),
                        granted_at=relationship.granted_at,
                        expires_at=relationship.expires_at,
                    )
                    for relationship in member.character_relationships
                ],
                grants=[
                    ResourceGrantSummaryResponse(
                        resource_grant_id=grant.resource_grant_id,
                        capability_code=grant.capability_code,
                        capability_display_name=grant.capability_display_name,
                        effect=grant.effect,
                        target_type=grant.target_type,
                        reason=grant.reason,
                        granted_at=grant.granted_at,
                        expires_at=grant.expires_at,
                    )
                    for grant in member.grants
                ],
            )
            for member in members
        ]
    )
