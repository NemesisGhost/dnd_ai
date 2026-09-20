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

`assignable_roles` (Phase 13E-B) is the read-contract counterpart to
`dnd_ai.api.memberships`' new `change_membership_role` mutation: every role
currently usable by this campaign (`dnd_ai.queries.access_overview.
list_assignable_campaign_roles`), so the portal's role-change control never
has to hardcode or guess the assignable set. Campaign-level, not per-member
— this codebase's role model carries no hierarchy, so every role
`access.manage` may assign is equally assignable to any member (see that
query function's own docstring).

`assignable_characters`/`assignable_relationship_types` (character-
relationship-management checkpoint) are the identical read-contract
counterpart for `dnd_ai.api.access_grants`' `grant_character_relationship`/
`change_character_relationship` mutations: every same-world, currently
active character, and every currently active relationship type, so the
portal's "Add/change character relationship" controls never have to
hardcode or guess either assignable set (`dnd_ai.queries.access_overview.
list_assignable_campaign_characters`/`.list_assignable_character_
relationship_types`). Also campaign-level (by world, for characters) rather
than per-member — which *combinations* are already active for a given
member is derived by the portal from that member's own `character_
relationships` list already in this response, exactly like `assignable_
roles`' own per-member narrowing is left to the portal.

`grantable_resource_capabilities` (checkpoint 5) is the read-contract
counterpart to `dnd_ai.api.access_grants`' `create_resource_grant`
mutation: every `(capability, target_type)` pairing `dnd_ai.domain.access.
RESOURCE_GRANT_CAPABILITY_CATALOG` currently allows, campaign-independent
(a fixed server policy, not scoped by `campaign_id`/`world_id`) — see that
constant's own docstring for the full delegation policy. Each member's own
`grants[].target_display_name` (checkpoint 5) resolves a safe display name
for a `character_id`-targeted grant only (from `core.entities.
canonical_name`, the identical name `character_relationships` already
uses) and is `None` for every other target kind, matching this module's
own "non-character grant-target identity" out-of-scope note below — the
portal's resource-grant management UI is scoped to `character` targets
only this checkpoint for the identical reason.

`access_groups` (Phase 13E-B checkpoint 6) is the read-contract
counterpart to `dnd_ai.api.access_groups`' own lifecycle/membership
mutations: every access group in the campaign, active and archived, each
with its currently open members and currently active, group-owned
resource grants (`dnd_ai.queries.access_overview.
list_campaign_access_groups`). Reuses `ResourceGrantSummaryResponse`'s own
shape for group-owned grants (`AccessGroupResourceGrantResponse` below) so
the portal's group-grant UI can share rendering/labeling logic with its
existing member-grant UI. The portal's own group-grant management is
scoped to `character` targets only, the identical reason `grantable_
resource_capabilities`' own note above gives — a backend-created grant of
another target kind, or a `deny` effect, may still appear here for display/
revocation, matching `grants[]`' own contract on `CampaignMemberSummaryResponse`.

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

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.access_overview import (
    find_eligible_campaign_account,
    get_campaign_access_overview,
    list_assignable_campaign_characters,
    list_assignable_campaign_roles,
    list_assignable_character_relationship_types,
    list_campaign_access_groups,
    list_grantable_resource_capabilities,
)

from ._shared import timeline_world_id
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
    membership_role_id: uuid.UUID
    role_id: uuid.UUID
    code: str
    display_name: str


class AssignableRoleResponse(BaseModel):
    role_id: uuid.UUID
    code: str
    display_name: str


class AssignableCharacterResponse(BaseModel):
    character_id: uuid.UUID
    display_name: str


class AssignableCharacterRelationshipTypeResponse(BaseModel):
    character_relationship_type_id: uuid.UUID
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
    target_id: uuid.UUID
    target_display_name: str | None
    reason: str | None
    granted_at: datetime
    expires_at: datetime | None


class GrantableResourceCapabilityResponse(BaseModel):
    capability_id: uuid.UUID
    code: str
    display_name: str
    target_type: str


class CampaignMemberSummaryResponse(BaseModel):
    campaign_membership_id: uuid.UUID
    # Identity only, never rendered as page text — matching
    # campaign_membership_id's own contract above. Exists so the portal can
    # detect "this row is the caller's own membership" (self-removal
    # messaging) by comparing against the caller's own
    # SessionBootstrap.user.user_id, without a separate server-computed
    # flag for what is presentation-only labeling; the server remains
    # authoritative on the one thing that actually matters (whether the
    # removal is *permitted*), independent of this comparison.
    user_id: uuid.UUID
    display_name: str
    status_code: str
    status_display_name: str
    joined_at: datetime
    roles: list[RoleSummaryResponse]
    character_relationships: list[CharacterRelationshipSummaryResponse]
    grants: list[ResourceGrantSummaryResponse]


class AccessGroupMemberSummaryResponse(BaseModel):
    access_group_membership_id: uuid.UUID
    campaign_membership_id: uuid.UUID
    display_name: str
    added_at: datetime


class AccessGroupResourceGrantResponse(BaseModel):
    resource_grant_id: uuid.UUID
    capability_code: str
    capability_display_name: str
    effect: str
    target_type: str
    target_id: uuid.UUID
    target_display_name: str | None
    reason: str | None
    granted_at: datetime
    expires_at: datetime | None


class AccessGroupSummaryResponse(BaseModel):
    access_group_id: uuid.UUID
    name: str
    description: str | None
    status_code: str
    status_display_name: str
    created_at: datetime
    members: list[AccessGroupMemberSummaryResponse]
    grants: list[AccessGroupResourceGrantResponse]


class CampaignAccessOverviewResponse(BaseModel):
    members: list[CampaignMemberSummaryResponse]
    assignable_roles: list[AssignableRoleResponse]
    assignable_characters: list[AssignableCharacterResponse]
    assignable_relationship_types: list[AssignableCharacterRelationshipTypeResponse]
    grantable_resource_capabilities: list[GrantableResourceCapabilityResponse]
    access_groups: list[AccessGroupSummaryResponse]


class EligibleAccountResponse(BaseModel):
    # Identity only, never rendered as page text — the portal's "Add
    # campaign member" control submits this back verbatim as the
    # add-member mutation's target user_id; a human never sees it.
    user_id: uuid.UUID
    display_name: str


class EligibleAccountLookupResponse(BaseModel):
    account: EligibleAccountResponse | None


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
    assignable_roles = list_assignable_campaign_roles(connection, campaign_id=campaign_id)
    assignable_characters = list_assignable_campaign_characters(
        connection, world_id=timeline_world_id(connection, access.timeline_id)
    )
    assignable_relationship_types = list_assignable_character_relationship_types(connection)
    grantable_resource_capabilities = list_grantable_resource_capabilities(connection)
    access_groups = list_campaign_access_groups(
        connection, campaign_id=campaign_id, timeline_id=access.timeline_id
    )
    return CampaignAccessOverviewResponse(
        assignable_roles=[
            AssignableRoleResponse(
                role_id=role.role_id, code=role.code, display_name=role.display_name
            )
            for role in assignable_roles
        ],
        assignable_characters=[
            AssignableCharacterResponse(
                character_id=character.character_id, display_name=character.display_name
            )
            for character in assignable_characters
        ],
        assignable_relationship_types=[
            AssignableCharacterRelationshipTypeResponse(
                character_relationship_type_id=relationship_type.character_relationship_type_id,
                code=relationship_type.code,
                display_name=relationship_type.display_name,
            )
            for relationship_type in assignable_relationship_types
        ],
        grantable_resource_capabilities=[
            GrantableResourceCapabilityResponse(
                capability_id=capability.capability_id,
                code=capability.code,
                display_name=capability.display_name,
                target_type=capability.target_type,
            )
            for capability in grantable_resource_capabilities
        ],
        members=[
            CampaignMemberSummaryResponse(
                campaign_membership_id=member.campaign_membership_id,
                user_id=member.user_id,
                display_name=member.display_name,
                status_code=member.status_code,
                status_display_name=member.status_display_name,
                joined_at=member.joined_at,
                roles=[
                    RoleSummaryResponse(
                        membership_role_id=role.membership_role_id,
                        role_id=role.role_id,
                        code=role.code,
                        display_name=role.display_name,
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
                        target_id=grant.target_id,
                        target_display_name=grant.target_display_name,
                        reason=grant.reason,
                        granted_at=grant.granted_at,
                        expires_at=grant.expires_at,
                    )
                    for grant in member.grants
                ],
            )
            for member in members
        ],
        access_groups=[
            AccessGroupSummaryResponse(
                access_group_id=group.access_group_id,
                name=group.name,
                description=group.description,
                status_code=group.status_code,
                status_display_name=group.status_display_name,
                created_at=group.created_at,
                members=[
                    AccessGroupMemberSummaryResponse(
                        access_group_membership_id=member.access_group_membership_id,
                        campaign_membership_id=member.campaign_membership_id,
                        display_name=member.display_name,
                        added_at=member.added_at,
                    )
                    for member in group.members
                ],
                grants=[
                    AccessGroupResourceGrantResponse(
                        resource_grant_id=grant.resource_grant_id,
                        capability_code=grant.capability_code,
                        capability_display_name=grant.capability_display_name,
                        effect=grant.effect,
                        target_type=grant.target_type,
                        target_id=grant.target_id,
                        target_display_name=grant.target_display_name,
                        reason=grant.reason,
                        granted_at=grant.granted_at,
                        expires_at=grant.expires_at,
                    )
                    for grant in group.grants
                ],
            )
            for group in access_groups
        ],
    )


# `login_name` is bounded to the same 3-64 character range
# `dnd_ai.commands.local_auth`'s own login-name format constraint allows
# (`ck_user_activation_tokens_login_name_format`) — a longer value can
# never match a stored one, so rejecting it here (422, FastAPI's own query-
# parameter validation) avoids sending an unbounded string to the database
# at all. No format/charset validation beyond length: an unnormalized or
# oddly-cased value is handled by `find_eligible_campaign_account`'s own
# `normalize_login_name()` call, and a value that simply never matches
# anything is indistinguishable from any other non-match (see that
# function's own docstring).
_LOGIN_NAME_MIN_LENGTH = 1
_LOGIN_NAME_MAX_LENGTH = 64


@router.get(
    "/campaigns/{campaign_id}/eligible-accounts",
    response_model=EligibleAccountLookupResponse,
    status_code=200,
)
def find_eligible_campaign_account_endpoint(
    campaign_id: uuid.UUID,
    login_name: Annotated[
        str, Query(min_length=_LOGIN_NAME_MIN_LENGTH, max_length=_LOGIN_NAME_MAX_LENGTH)
    ],
    access: Annotated[  # noqa: ARG001 — required only to enforce the access.manage capability
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> EligibleAccountLookupResponse:
    """Exact-match account lookup for the portal's "Add campaign member"
    control (Phase 13E-B checkpoint 3) — see `dnd_ai.queries.
    access_overview.find_eligible_campaign_account`'s own docstring for the
    full non-disclosure design (why this is exact lookup rather than a
    directory-style search, and why "no such account", "platform-disabled",
    and "already a member here" all collapse to the identical `account:
    null` result rather than three distinguishable outcomes). `access.
    manage` is required exactly like every other route in this module —
    reviewing who *could* be added is the same category of action as
    reviewing who currently has access. This is a pure read: no
    idempotency key, no `audit.change_log` row, no mutation, matching `GET
    .../access-overview`'s own contract."""
    account = find_eligible_campaign_account(
        connection, campaign_id=campaign_id, login_name=login_name
    )
    return EligibleAccountLookupResponse(
        account=(
            EligibleAccountResponse(user_id=account.user_id, display_name=account.display_name)
            if account is not None
            else None
        )
    )
