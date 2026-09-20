"""HTTP endpoints for campaign access-group lifecycle and membership
management (Phase 13E-B checkpoint 6).

Exposes `create_access_group`, `update_access_group`,
`deactivate_access_group`, `reactivate_access_group`,
`add_access_group_member`, and `remove_access_group_member`
(`dnd_ai.commands.access_groups`) over HTTP, on the same already-delivered
authentication, transaction management, and access resolution every other
command router uses. Group-owned resource grants are deliberately **not**
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
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from dnd_ai.commands.access_groups import (
    ACCESS_GROUP_DESCRIPTION_MAX_LENGTH,
    ACCESS_GROUP_NAME_MAX_LENGTH,
    add_access_group_member,
    create_access_group,
    deactivate_access_group,
    reactivate_access_group,
    remove_access_group_member,
    update_access_group,
)
from dnd_ai.domain.access import AccessContext

from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .idempotency import IdempotentReplay, begin_idempotent_request, complete_idempotent_request

router = APIRouter(tags=["access-groups"])

_ACCESS_MANAGE_CAPABILITY = "access.manage"

_CREATE_GROUP_COMMAND_NAME = "create_access_group"
_UPDATE_GROUP_COMMAND_NAME = "update_access_group"
_DEACTIVATE_GROUP_COMMAND_NAME = "deactivate_access_group"
_REACTIVATE_GROUP_COMMAND_NAME = "reactivate_access_group"
_ADD_GROUP_MEMBER_COMMAND_NAME = "add_access_group_member"
_REMOVE_GROUP_MEMBER_COMMAND_NAME = "remove_access_group_member"

_CREATED_CHANGE_ACTION = "created"
_UPDATED_CHANGE_ACTION = "updated"

# Checkpoint-6 correction: deactivate_access_group_endpoint used to write
# every removed access_group_membership_id/revoked resource_grant_id into
# changed_fields verbatim — an unbounded JSONB payload sized by however many
# open memberships/active grants the group happened to own at the moment it
# was archived, with no cap at all. Full transactional cleanup
# (dnd_ai.commands.access_groups.deactivate_access_group) is unaffected —
# every dependent row is still closed/revoked regardless of how many there
# are — only this audit *representation* is bounded now.
_DEACTIVATE_AUDIT_ID_SAMPLE_LIMIT = 20


def _bounded_id_sample(ids: tuple[uuid.UUID, ...]) -> dict[str, Any]:
    """Bounds an unboundedly-sized tuple of ids for one `changed_fields`
    entry: an exact `count`, a `sample_ids` prefix capped at
    `_DEACTIVATE_AUDIT_ID_SAMPLE_LIMIT`, and a `sample_truncated` flag
    naming whether `sample_ids` is the whole list (`False`) or only a
    prefix of it (`True`) — so a reader of the raw `audit.change_log` row
    can always tell the two apart rather than mistaking a capped sample for
    the complete set."""
    sample = ids[:_DEACTIVATE_AUDIT_ID_SAMPLE_LIMIT]
    return {
        "count": len(ids),
        "sample_ids": [str(entity_id) for entity_id in sample],
        "sample_truncated": len(ids) > len(sample),
    }


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
    campaign_membership_id: uuid.UUID


class AccessGroupMembershipResponse(BaseModel):
    access_group_membership_id: uuid.UUID


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/campaigns/{campaign_id}/access-groups", response_model=AccessGroupResponse, status_code=201
)
def create_access_group_endpoint(
    campaign_id: uuid.UUID,
    body: CreateAccessGroupRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> AccessGroupResponse:
    """Creates a new, active access group scoped to `campaign_id` — the
    portal Access page's "Create access group" action. Never accepts an
    actor, campaign, member, or grant from the request body: `campaign_id`
    comes from the path, and no member is auto-added (group creation and
    membership assignment stay distinguishable audit actions)."""
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
            command_name=_CREATE_GROUP_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return AccessGroupResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = create_access_group(
        connection, campaign_id=campaign_id, name=body.name, description=body.description
    )

    record_change_log(
        connection,
        change_action_code=_CREATED_CHANGE_ACTION,
        schema_name="security",
        table_name="access_groups",
        record_id=result.access_group_id,
        entity_id=None,
        world_id=timeline_world_id(connection, access.timeline_id),
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_CREATE_GROUP_COMMAND_NAME,
        event_id=None,
        # The command's own normalized description (trimmed, blank-to-
        # None), never body.description raw — a caller-supplied
        # whitespace-only description is persisted as NULL, and the audit
        # record must agree with what was actually stored, not what was
        # merely requested.
        changed_fields={"name": result.name, "description": result.description},
    )

    response = AccessGroupResponse(access_group_id=result.access_group_id, name=result.name)

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=201,
            response_body=response.model_dump(mode="json"),
        )

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
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> AccessGroupResponse:
    """Renames/redescribes an existing, active access group — the portal's
    "Edit access group" action. `200`, not `201`: this changes an existing
    row, it creates nothing. Records `previous_status`/`new_status` as the
    group's previous/new name (mirroring `change_membership_role_
    endpoint`'s own use of those generic columns for a name-shaped
    change), so audit-history can show an "old name → new name" summary
    without a bespoke column."""
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "access_group_id": str(access_group_id),
            **body.model_dump(mode="json"),
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_UPDATE_GROUP_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return AccessGroupResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = update_access_group(
        connection,
        access_group_id=access_group_id,
        campaign_id=campaign_id,
        name=body.name,
        description=body.description,
    )

    record_change_log(
        connection,
        change_action_code=_UPDATED_CHANGE_ACTION,
        schema_name="security",
        table_name="access_groups",
        record_id=result.access_group_id,
        entity_id=None,
        world_id=timeline_world_id(connection, access.timeline_id),
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_UPDATE_GROUP_COMMAND_NAME,
        event_id=None,
        previous_status=result.previous_name,
        new_status=result.name,
        # result.description, not body.description raw — see
        # create_access_group_endpoint's identical comment above.
        changed_fields={"description": result.description},
    )

    response = AccessGroupResponse(access_group_id=result.access_group_id, name=result.name)

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=200,
            response_body=response.model_dump(mode="json"),
        )

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
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> AccessGroupResponse:
    """Archives an existing access group, closing its open memberships and
    revoking its active resource grants in the same transaction — the
    portal's "Deactivate access group" action, requiring deliberate
    confirmation naming the group. No request body: the path already
    carries everything this command needs. The audit write below is
    conditioned on `DeactivateAccessGroupResult.deactivated`, so a plain
    retry that lands on an already-archived group (whether or not it
    reuses a key) writes no second row. `changed_fields` records each
    dependent list (`removed_access_group_memberships`/`revoked_
    resource_grants`) as a bounded `_bounded_id_sample()` summary — exact
    `count`, a capped `sample_ids` prefix, `sample_truncated` — never the
    full, unbounded id list; full transactional cleanup is unaffected by
    this bound, only its audit representation."""
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {"access_group_id": str(access_group_id)}
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_DEACTIVATE_GROUP_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return AccessGroupResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = deactivate_access_group(
        connection, access_group_id=access_group_id, campaign_id=campaign_id
    )

    # The group's own current name is not returned by the command (it
    # never changes here) — read once, outside any lock, purely for the
    # response label; safe because it is presentation-only, never an
    # authorization decision.
    group_name = connection.execute(
        text("SELECT name FROM security.access_groups WHERE access_group_id = :group"),
        {"group": access_group_id},
    ).scalar()

    if result.deactivated:
        record_change_log(
            connection,
            change_action_code=_UPDATED_CHANGE_ACTION,
            schema_name="security",
            table_name="access_groups",
            record_id=access_group_id,
            entity_id=None,
            world_id=timeline_world_id(connection, access.timeline_id),
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=_DEACTIVATE_GROUP_COMMAND_NAME,
            event_id=None,
            previous_status="active",
            new_status="archived",
            changed_fields={
                "removed_access_group_memberships": _bounded_id_sample(
                    result.removed_access_group_membership_ids
                ),
                "revoked_resource_grants": _bounded_id_sample(result.revoked_resource_grant_ids),
            },
        )

    response = AccessGroupResponse(
        access_group_id=access_group_id, name=str(group_name) if group_name is not None else ""
    )

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=200,
            response_body=response.model_dump(mode="json"),
        )

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
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> AccessGroupResponse:
    """Restores an archived access group to active — the portal's
    "Reactivate access group" action. Never reopens a closed membership or
    un-revokes a grant (see `dnd_ai.commands.access_groups.
    reactivate_access_group()`'s own docstring); the reactivated group is
    empty and powerless until a new add-member/grant action explicitly
    re-adds it. The audit write below is conditioned on
    `ReactivateAccessGroupResult.reactivated`, matching `deactivate_
    access_group_endpoint`'s identical no-op discipline."""
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {"access_group_id": str(access_group_id)}
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_REACTIVATE_GROUP_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return AccessGroupResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = reactivate_access_group(
        connection, access_group_id=access_group_id, campaign_id=campaign_id
    )

    group_name = connection.execute(
        text("SELECT name FROM security.access_groups WHERE access_group_id = :group"),
        {"group": access_group_id},
    ).scalar()

    if result.reactivated:
        record_change_log(
            connection,
            change_action_code=_UPDATED_CHANGE_ACTION,
            schema_name="security",
            table_name="access_groups",
            record_id=access_group_id,
            entity_id=None,
            world_id=timeline_world_id(connection, access.timeline_id),
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=_REACTIVATE_GROUP_COMMAND_NAME,
            event_id=None,
            previous_status="archived",
            new_status="active",
        )

    response = AccessGroupResponse(
        access_group_id=access_group_id, name=str(group_name) if group_name is not None else ""
    )

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=200,
            response_body=response.model_dump(mode="json"),
        )

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
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> AccessGroupMembershipResponse:
    """Adds an existing, active campaign membership to an existing, active
    access group — the portal's "Add member to group" action. `campaign_
    membership_id` is the authoritative campaign-membership id, never a
    bare user id — the portal's member selector already offers only
    server-authoritative active campaign members (the same `members` list
    `GET /campaigns/{campaign_id}/access-overview` already returns)."""
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "access_group_id": str(access_group_id),
            **body.model_dump(mode="json"),
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_ADD_GROUP_MEMBER_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return AccessGroupMembershipResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = add_access_group_member(
        connection,
        access_group_id=access_group_id,
        campaign_membership_id=body.campaign_membership_id,
        campaign_id=campaign_id,
        added_by_membership_id=access.campaign_membership_id,
    )

    record_change_log(
        connection,
        change_action_code=_CREATED_CHANGE_ACTION,
        schema_name="security",
        table_name="access_group_memberships",
        record_id=result.access_group_membership_id,
        entity_id=None,
        world_id=timeline_world_id(connection, access.timeline_id),
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_ADD_GROUP_MEMBER_COMMAND_NAME,
        event_id=None,
        changed_fields={
            "access_group_id": str(access_group_id),
            "campaign_membership_id": str(body.campaign_membership_id),
        },
    )

    response = AccessGroupMembershipResponse(
        access_group_membership_id=result.access_group_membership_id
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
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> AccessGroupMembershipResponse:
    """Removes one member from one access group — the portal's "Remove
    from group" action, requiring confirmation naming both the member and
    the group. Does not end the member's campaign membership, and does not
    touch the group's own grants or any other member's link to it. The
    audit write below is conditioned on `RemoveAccessGroupMemberResult.
    removed`, matching `revoke_resource_grant_endpoint`'s identical no-op
    discipline."""
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "access_group_membership_id": str(access_group_membership_id)
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_REMOVE_GROUP_MEMBER_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return AccessGroupMembershipResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = remove_access_group_member(
        connection, access_group_membership_id=access_group_membership_id, campaign_id=campaign_id
    )

    if result.removed:
        record_change_log(
            connection,
            change_action_code=_UPDATED_CHANGE_ACTION,
            schema_name="security",
            table_name="access_group_memberships",
            record_id=access_group_membership_id,
            entity_id=None,
            world_id=timeline_world_id(connection, access.timeline_id),
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=_REMOVE_GROUP_MEMBER_COMMAND_NAME,
            event_id=None,
            changed_fields={
                "access_group_id": (
                    str(result.access_group_id) if result.access_group_id is not None else None
                ),
                "campaign_membership_id": (
                    str(result.campaign_membership_id)
                    if result.campaign_membership_id is not None
                    else None
                ),
            },
        )

    response = AccessGroupMembershipResponse(access_group_membership_id=access_group_membership_id)

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=200,
            response_body=response.model_dump(mode="json"),
        )

    return response
