"""HTTP endpoints for campaign access-group lifecycle and membership
management (Phase 13E-B checkpoint 6).

Exposes `create_access_group`, `update_access_group`,
`deactivate_access_group`, `reactivate_access_group`,
`add_access_group_member`, and `remove_access_group_member` over HTTP, on the same
already-delivered authentication, transaction management, and access resolution every
other command router uses. **R01 S5-E5: all six are keyed-optional pre-write routes**
(`dnd_ai.commands.access_group_plans`: every lock before `plan.finalize`, every write a
declared step after it, one audit row per real change, one per inserted link). The direct
commands in `dnd_ai.commands.access_groups` stay, unguarded and unchanged.

Group-owned resource grants are deliberately **not**
a new route here — the portal reuses `POST /campaigns/{campaign_id}/
resource-grants`/`.../resource-grants/{id}/revoke` (`dnd_ai.api.
access_grants`, already supporting a `grantee_access_group_id` grantee,
hardened this checkpoint to require the group currently be active) rather
than a parallel grant surface.

Authorization: every route here requires `access.manage`, matching every
other access-administration route in this codebase (`dnd_ai.api.
memberships`/`.access_grants`) — group create/rename/deactivate/
reactivate/membership changes are the same category of action as
assigning a role or granting a resource, not a canon mutation.

Idempotency: every mutating route accepts an `Idempotency-Key` and uses
the same durable `security.idempotent_requests` mechanism `dnd_ai.api.
memberships`/`.access_grants` already use — a naive retry would otherwise
hit `ux_access_groups_campaign_name`/`ux_access_group_memberships_open`'s
own `IntegrityError` (409) instead of replaying the original response, or
(for the deactivate/reactivate/remove routes, each already state-
idempotent on their own harmless-no-op result) durably record a second
audit row for one real state change.

Auditing: every successful call that actually changed state records
exactly one `audit.change_log` row — `deactivate_access_group_endpoint`/
`reactivate_access_group_endpoint`/`remove_access_group_member_endpoint`
condition their write on the underlying command's own `deactivated`/
`reactivated`/`removed` result field, mirroring `revoke_resource_grant_
endpoint`'s identical "one audit row per real change, not per HTTP call"
discipline. `entity_id` is always `None` — neither `security.access_
groups` nor `.access_group_memberships` is a `core.entities` row. `world_
id` is resolved server-side from the campaign's own pinned timeline."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import Connection

from dnd_ai.commands._pre_write_steps import receipt_params
from dnd_ai.commands.access_group_plans import (
    GROUP_RECEIPT,
    prepare_add_members,
    prepare_create_group,
    prepare_deactivate_group,
    prepare_reactivate_group,
    prepare_remove_member,
    prepare_update_group,
    write_add_members,
    write_create_group,
    write_deactivate_group,
    write_reactivate_group,
    write_remove_member,
    write_update_group,
)
from dnd_ai.commands.access_groups import (
    ACCESS_GROUP_DESCRIPTION_MAX_LENGTH,
    ACCESS_GROUP_MEMBER_BATCH_MAX_SIZE,
    ACCESS_GROUP_NAME_MAX_LENGTH,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authorization import AuthorizationPlan

from .access import require_campaign_capability
from .campaigns import _begin_lifecycle_request
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .r01_route_plans import get_authorization_plan

router = APIRouter(tags=["access-groups"])
_Plan = Annotated[AuthorizationPlan, Depends(get_authorization_plan)]

_ACCESS_MANAGE_CAPABILITY = "access.manage"

_CREATE_GROUP_COMMAND_NAME = "create_access_group"
_UPDATE_GROUP_COMMAND_NAME = "update_access_group"
_DEACTIVATE_GROUP_COMMAND_NAME = "deactivate_access_group"
_REACTIVATE_GROUP_COMMAND_NAME = "reactivate_access_group"
_ADD_GROUP_MEMBER_COMMAND_NAME = "add_access_group_member"
_REMOVE_GROUP_MEMBER_COMMAND_NAME = "remove_access_group_member"


# ---------------------------------------------------------------------------
# Request/response contracts
# ---------------------------------------------------------------------------


class CreateAccessGroupRequest(BaseModel):
    # Bounds mirror ck_access_groups_name_length (migration 080)/
    # ck_access_groups_description_length (migration 106) exactly —
    # imported from dnd_ai.commands.access_groups rather than restated, so
    # an over-limit value is rejected here, before any database round trip,
    # with the same numbers the database and dnd_ai.commands.access_groups'
    # own pre-check (AccessGroupNameTooLongError/
    # AccessGroupDescriptionTooLongError) enforce. A too-long value that
    # somehow reached the command layer anyway (this endpoint is not the
    # only caller in principle) is still rejected there, not just here.
    name: str = Field(max_length=ACCESS_GROUP_NAME_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=ACCESS_GROUP_DESCRIPTION_MAX_LENGTH)


class UpdateAccessGroupRequest(BaseModel):
    name: str = Field(max_length=ACCESS_GROUP_NAME_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=ACCESS_GROUP_DESCRIPTION_MAX_LENGTH)


class AccessGroupResponse(BaseModel):
    access_group_id: uuid.UUID
    name: str


class AddAccessGroupMemberRequest(BaseModel):
    campaign_membership_ids: list[uuid.UUID] = Field(
        min_length=1,
        max_length=ACCESS_GROUP_MEMBER_BATCH_MAX_SIZE,
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_single_id(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        has_batch = "campaign_membership_ids" in value
        has_legacy_single = "campaign_membership_id" in value

        if has_batch and has_legacy_single:
            raise ValueError("provide campaign_membership_ids or campaign_membership_id, not both")

        if not has_legacy_single:
            return value

        normalized_value = dict(value)
        legacy_id = normalized_value.pop("campaign_membership_id")
        normalized_value["campaign_membership_ids"] = [legacy_id]
        return normalized_value

    @field_validator("campaign_membership_ids")
    @classmethod
    def _canonicalize_membership_ids(
        cls,
        membership_ids: list[uuid.UUID],
    ) -> list[uuid.UUID]:
        return sorted(
            set(membership_ids),
            key=lambda membership_id: membership_id.int,
        )


class AccessGroupMembershipResponse(BaseModel):
    access_group_membership_id: uuid.UUID | None = None
    access_group_membership_ids: list[uuid.UUID] = Field(default_factory=list)
    added_count: int | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _complete_receipt_with(
    connection: Connection,
    plan: AuthorizationPlan,
    reservation_id: uuid.UUID | None,
    status: int,
    response: BaseModel,
) -> None:
    if reservation_id is not None:
        plan.execute(
            connection,
            GROUP_RECEIPT,
            receipt_params(reservation_id, status, response.model_dump(mode="json")),
        )


@router.post(
    "/campaigns/{campaign_id}/access-groups", response_model=AccessGroupResponse, status_code=201
)
def create_access_group_endpoint(
    campaign_id: uuid.UUID,
    body: CreateAccessGroupRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    """Creates a new, active access group scoped to `campaign_id` — the
    portal Access page's "Create access group" action. Never accepts an
    actor, campaign, member, or grant from the request body: `campaign_id`
    comes from the path, and no member is auto-added (group creation and
    membership assignment stay distinguishable audit actions). The audit
    row records the command's own normalized description (trimmed,
    blank-to-None), never the raw request value."""
    replay, reservation_id = _begin_lifecycle_request(
        plan=plan,
        connection=connection,
        access=access,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        command_name=_CREATE_GROUP_COMMAND_NAME,
        payload={"campaign_id": str(campaign_id), **body.model_dump(mode="json")},
    )
    if replay is not None:
        return replay
    prepared = prepare_create_group(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        name=body.name,
        description=body.description,
        reservation_id=reservation_id,
    )
    plan.finalize(connection)
    new_id = write_create_group(
        connection,
        plan,
        prepared,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
    )
    response = AccessGroupResponse(access_group_id=new_id, name=prepared.name)
    _complete_receipt_with(connection, plan, reservation_id, 201, response)
    return response


@router.post(
    "/campaigns/{campaign_id}/access-groups/{access_group_id}/update",
    response_model=AccessGroupResponse,
    status_code=200,
)
def update_access_group_endpoint(
    campaign_id: uuid.UUID,
    access_group_id: uuid.UUID,
    body: UpdateAccessGroupRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    """Renames/redescribes an existing, active access group — the portal's
    "Edit access group" action. `200`, not `201`: this changes an existing
    row, it creates nothing. Records `previous_status`/`new_status` as the
    group's previous/new name, so audit-history can show an "old name → new
    name" summary without a bespoke column. A request that changes nothing
    is a 422 refusal (never stored, the key stays reusable)."""
    replay, reservation_id = _begin_lifecycle_request(
        plan=plan,
        connection=connection,
        access=access,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        command_name=_UPDATE_GROUP_COMMAND_NAME,
        payload={"access_group_id": str(access_group_id), **body.model_dump(mode="json")},
    )
    if replay is not None:
        return replay
    prepared = prepare_update_group(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        group_id=access_group_id,
        name=body.name,
        description=body.description,
        reservation_id=reservation_id,
    )
    plan.finalize(connection)
    write_update_group(
        connection,
        plan,
        prepared,
        group_id=access_group_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
    )
    response = AccessGroupResponse(access_group_id=access_group_id, name=prepared.name)
    _complete_receipt_with(connection, plan, reservation_id, 200, response)
    return response


@router.post(
    "/campaigns/{campaign_id}/access-groups/{access_group_id}/deactivate",
    response_model=AccessGroupResponse,
    status_code=200,
)
def deactivate_access_group_endpoint(
    campaign_id: uuid.UUID,
    access_group_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    """Archives an existing access group, closing its open memberships,
    revoking its active resource grants and closing its live revelations in the
    same transaction — the portal's "Deactivate access group" action, requiring
    deliberate confirmation naming the group. No request body. An already-archived
    group is the documented no-op: no write and no audit row (a fresh keyed
    request still completes its receipt). `changed_fields` records each
    dependent list as a bounded summary — exact `count`, the first 20 ids in
    ascending order, `sample_truncated` — never the full id list; the cleanup
    itself is unbounded."""
    replay, reservation_id = _begin_lifecycle_request(
        plan=plan,
        connection=connection,
        access=access,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        command_name=_DEACTIVATE_GROUP_COMMAND_NAME,
        payload={"access_group_id": str(access_group_id)},
    )
    if replay is not None:
        return replay
    prepared = prepare_deactivate_group(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        group_id=access_group_id,
        reservation_id=reservation_id,
    )
    plan.finalize(connection)
    write_deactivate_group(
        connection,
        plan,
        prepared,
        group_id=access_group_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
    )
    response = AccessGroupResponse(access_group_id=access_group_id, name=prepared.name)
    _complete_receipt_with(connection, plan, reservation_id, 200, response)
    return response


@router.post(
    "/campaigns/{campaign_id}/access-groups/{access_group_id}/reactivate",
    response_model=AccessGroupResponse,
    status_code=200,
)
def reactivate_access_group_endpoint(
    campaign_id: uuid.UUID,
    access_group_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    """Restores an archived access group to active — the portal's
    "Reactivate access group" action. Never reopens a closed membership or
    un-revokes a grant; the reactivated group is empty and powerless until a
    new add-member/grant action explicitly re-adds it. An already-active group
    is the documented no-op (the campaign status is not checked)."""
    replay, reservation_id = _begin_lifecycle_request(
        plan=plan,
        connection=connection,
        access=access,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        command_name=_REACTIVATE_GROUP_COMMAND_NAME,
        payload={"access_group_id": str(access_group_id)},
    )
    if replay is not None:
        return replay
    prepared = prepare_reactivate_group(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        group_id=access_group_id,
        reservation_id=reservation_id,
    )
    plan.finalize(connection)
    write_reactivate_group(
        connection,
        plan,
        prepared,
        group_id=access_group_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
    )
    response = AccessGroupResponse(access_group_id=access_group_id, name=prepared.name)
    _complete_receipt_with(connection, plan, reservation_id, 200, response)
    return response


@router.post(
    "/campaigns/{campaign_id}/access-groups/{access_group_id}/members",
    response_model=AccessGroupMembershipResponse,
    status_code=201,
)
def add_access_group_member_endpoint(
    campaign_id: uuid.UUID,
    access_group_id: uuid.UUID,
    body: AddAccessGroupMemberRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    """Atomically adds one or more campaign memberships to an access group.
    All-or-nothing: an already-open link or an ineligible member refuses the
    whole batch. One link and one audit row per member, in ascending member
    order."""
    membership_ids = tuple(body.campaign_membership_ids)
    replay, reservation_id = _begin_lifecycle_request(
        plan=plan,
        connection=connection,
        access=access,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        command_name=_ADD_GROUP_MEMBER_COMMAND_NAME,
        payload={
            "access_group_id": str(access_group_id),
            "campaign_membership_ids": [str(membership_id) for membership_id in membership_ids],
        },
    )
    if replay is not None:
        return replay
    prepared = prepare_add_members(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        group_id=access_group_id,
        member_ids=membership_ids,
        reservation_id=reservation_id,
    )
    plan.finalize(connection)
    added = write_add_members(
        connection,
        plan,
        prepared,
        group_id=access_group_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        correlation_id=correlation_id,
    )
    access_group_membership_ids = [link_id for _member_id, link_id in added]
    response = AccessGroupMembershipResponse(
        access_group_membership_id=(
            access_group_membership_ids[0] if len(access_group_membership_ids) == 1 else None
        ),
        access_group_membership_ids=access_group_membership_ids,
        added_count=len(access_group_membership_ids),
    )
    _complete_receipt_with(connection, plan, reservation_id, 201, response)
    return response


@router.post(
    "/campaigns/{campaign_id}/access-group-memberships/{access_group_membership_id}/remove",
    response_model=AccessGroupMembershipResponse,
    status_code=200,
)
def remove_access_group_member_endpoint(
    campaign_id: uuid.UUID,
    access_group_membership_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    """Removes one member from one access group — the portal's "Remove
    from group" action, requiring confirmation naming both the member and
    the group. Does not end the member's campaign membership, and does not
    touch the group's own grants or any other member's link to it. An
    already-removed link is the documented no-op: no write and no audit row."""
    replay, reservation_id = _begin_lifecycle_request(
        plan=plan,
        connection=connection,
        access=access,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        command_name=_REMOVE_GROUP_MEMBER_COMMAND_NAME,
        payload={"access_group_membership_id": str(access_group_membership_id)},
    )
    if replay is not None:
        return replay
    prepared = prepare_remove_member(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        link_id=access_group_membership_id,
        reservation_id=reservation_id,
    )
    plan.finalize(connection)
    write_remove_member(
        connection,
        plan,
        prepared,
        link_id=access_group_membership_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
    )
    response = AccessGroupMembershipResponse(access_group_membership_id=access_group_membership_id)
    _complete_receipt_with(connection, plan, reservation_id, 200, response)
    return response
