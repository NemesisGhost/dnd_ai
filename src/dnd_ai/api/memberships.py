"""Campaign membership and role-assignment command endpoints.

Exposes
`add_campaign_member`, `assign_membership_role`, `revoke_membership_role`,
`change_membership_role`, and `end_campaign_membership` over HTTP, on the
same already-delivered OIDC authentication, transaction management, and
access resolution every other command router uses. `change_membership_role`
(Phase 13E-B's first mutation checkpoint) is the portal Access page's
"change role" action: it atomically revokes one existing, currently-active
role assignment and assigns a different role in its place — never a bulk
replace of everything a membership holds — so a membership with more than
one simultaneously active role never has an unrelated assignment silently
dropped. See `dnd_ai.commands.memberships.change_membership_role`'s own
docstring for the full behavior and error contract.

`add_campaign_member`/`end_campaign_membership` (Phase 13E-B checkpoint 3)
are the portal Access page's "Add campaign member"/"Remove member"
actions: adding an existing, eligible account to the campaign with one
initial role, and ending an existing membership (closing it and every one
of its active role assignments) — never account creation, invitations, or
reactivating a previously-departed membership. `POST .../memberships`
(previously reserved/unused, docs/PHASE13E_ACCESS_CONTRACT.md §2) is
hardened this checkpoint to require an initial `role_id` and return both
the new membership and role ids atomically. See `dnd_ai.commands.
memberships.add_campaign_member`/`.end_campaign_membership`'s own
docstrings for the full eligibility/concurrency contract.

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
docstring for the full concurrency argument. `revoke_membership_role_
endpoint` (Phase 13E-B checkpoint 2 correction) now uses the identical
mechanism too — see that route's own docstring for the duplicate-audit gap
this closes; `dnd_ai.commands.memberships.revoke_membership_role` remains
state-idempotent on its own (an ordinary retry with no key reused still
converges on the same revoked state), but state-idempotency alone was not
enough to keep the *audit trail* free of one row per HTTP retry.

Auditing: every successful call inserts one `audit.change_log` row
(`dnd_ai.api.audit.record_change_log`). `entity_id` is always `None` —
neither `security.campaign_memberships` nor `.membership_roles` is a
`core.entities` row (people and their campaign authorization are not world
entities), matching `audit.change_log.entity_id`'s own documented
contract, "the `core.entities` row this change concerns, *when there is
one*" (migration 007). `world_id` is resolved server-side from the
campaign's own pinned timeline (`dnd_ai.api._shared.timeline_world_id`),
the same "never trust a caller-supplied world/timeline pairing" rule every
other command router already applies. `revoke_membership_role_endpoint`
writes its row only when `dnd_ai.commands.memberships.
RevokeMembershipRoleResult.revoked` is `True` — never on the pre-existing
harmless no-op path (an already-revoked target) — so a retry that reaches
the command a second time (a fresh `Idempotency-Key`, or none at all)
converges on the same state without a second audit row, even outside of an
idempotent replay.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.commands.memberships import (
    add_campaign_member,
    assign_membership_role,
    change_membership_role,
    end_campaign_membership,
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

_ADD_MEMBER_COMMAND_NAME = "add_campaign_member"
_ASSIGN_ROLE_COMMAND_NAME = "assign_membership_role"
_REVOKE_ROLE_COMMAND_NAME = "revoke_membership_role"
_CHANGE_ROLE_COMMAND_NAME = "change_membership_role"
_END_MEMBERSHIP_COMMAND_NAME = "end_campaign_membership"

_CREATED_CHANGE_ACTION = "created"
_UPDATED_CHANGE_ACTION = "updated"


# ---------------------------------------------------------------------------
# Request/response contracts
# ---------------------------------------------------------------------------


class CreateCampaignMembershipRequest(BaseModel):
    user_id: uuid.UUID
    role_id: uuid.UUID


class CampaignMembershipResponse(BaseModel):
    campaign_membership_id: uuid.UUID
    membership_role_id: uuid.UUID


class EndCampaignMembershipResponse(BaseModel):
    campaign_membership_id: uuid.UUID


class AssignMembershipRoleRequest(BaseModel):
    role_id: uuid.UUID
    expires_at: datetime | None = None


class MembershipRoleResponse(BaseModel):
    membership_role_id: uuid.UUID


class ChangeMembershipRoleRequest(BaseModel):
    new_role_id: uuid.UUID


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
    """Adds an existing, eligible account to `campaign_id` with one initial
    role — the portal Access page's "Add campaign member" action (Phase
    13E-B checkpoint 3, `dnd_ai.commands.memberships.add_campaign_member`).
    `role_id` (new this checkpoint) is required, not optional: this route
    was previously reserved/unused (docs/PHASE13E_ACCESS_CONTRACT.md §2)
    with no real caller to preserve compatibility for, so hardening its
    request contract to require an initial role — never a roleless
    membership a second call would have to complete — costs nothing. See
    that command's own docstring for the full eligibility/concurrency
    contract (campaign must be active, target account must be platform-
    active, target role must be scoped to this campaign and active; a
    duplicate-open-membership race is left to `ux_campaign_memberships_
    open`'s own 409, not pre-checked)."""
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
            command_name=_ADD_MEMBER_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return CampaignMembershipResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = add_campaign_member(
        connection,
        campaign_id=campaign_id,
        user_id=body.user_id,
        role_id=body.role_id,
        added_by_membership_id=access.campaign_membership_id,
    )

    world_id = timeline_world_id(connection, access.timeline_id)

    # Two rows, one per table this call inserted into — matching each
    # table's own pre-existing single-row audit convention
    # (create_campaign_membership_endpoint's/assign_membership_role_
    # endpoint's own, now combined into this one atomic call) rather than
    # inventing a new "one row describes two tables" shape.
    record_change_log(
        connection,
        change_action_code=_CREATED_CHANGE_ACTION,
        schema_name="security",
        table_name="campaign_memberships",
        record_id=result.campaign_membership_id,
        entity_id=None,
        world_id=world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_ADD_MEMBER_COMMAND_NAME,
        event_id=None,
    )
    record_change_log(
        connection,
        change_action_code=_CREATED_CHANGE_ACTION,
        schema_name="security",
        table_name="membership_roles",
        record_id=result.membership_role_id,
        entity_id=None,
        world_id=world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_ADD_MEMBER_COMMAND_NAME,
        event_id=None,
    )

    response = CampaignMembershipResponse(
        campaign_membership_id=result.campaign_membership_id,
        membership_role_id=result.membership_role_id,
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
    response_model=MembershipRoleResponse,
    status_code=200,
)
def revoke_membership_role_endpoint(
    campaign_id: uuid.UUID,
    membership_role_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> MembershipRoleResponse:
    """Revokes one existing, currently-active role assignment — the portal
    Access page's "revoke role" action (Phase 13E-B checkpoint 2). Self-
    revocation is permitted, with no special-case check here or in the
    command: the campaign's own retention invariant is what actually
    protects an active campaign from ending up with no `access.manage`
    holder, exactly as it already does for `change_membership_role_
    endpoint`. `200`, not the pre-checkpoint-2 `204`: this route's response
    now carries a body — see "Response contract change" below.

    Response contract change (Phase 13E-B checkpoint 2 correction): this
    route previously returned a bare `204 No Content` and accepted no
    `Idempotency-Key`, on the theory that `revoke_membership_role`'s own
    state-idempotency (a retry against an already-revoked row is a harmless
    no-op) made a durable key unnecessary. That reasoning covered *state*
    but not the *audit trail*: every call — including a plain retry with no
    key at all — wrote its own `audit.change_log` row unconditionally, so
    an ordinary network retry (the exact "unknown outcome, retry" case this
    application's own idempotency story exists for) could durably record
    two revocation events for one real revocation. Fixed two ways, matching
    every other mutating endpoint in this module: (1) an `Idempotency-Key`
    replay returns the original cached response verbatim, never re-running
    the command at all; (2) even *without* a matching key, the audit write
    below is now conditioned on `RevokeMembershipRoleResult.revoked`, so a
    second call that lands on an already-revoked row (whether or not it
    reuses a key) writes no second row. A `MembershipRoleResponse` echoing
    `membership_role_id` back (reusing the existing assign-role response
    shape) gives `begin_idempotent_request`/`complete_idempotent_request`
    something to cache, which a bodyless `204` could not."""
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {"membership_role_id": str(membership_role_id)}
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_REVOKE_ROLE_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return MembershipRoleResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = revoke_membership_role(
        connection, membership_role_id=membership_role_id, campaign_id=campaign_id
    )

    if result.revoked:
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

    response = MembershipRoleResponse(membership_role_id=membership_role_id)

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=200,
            response_body=response.model_dump(mode="json"),
        )

    return response


@router.post(
    "/campaigns/{campaign_id}/memberships/roles/{membership_role_id}/change",
    response_model=MembershipRoleResponse,
    status_code=201,
)
def change_membership_role_endpoint(
    campaign_id: uuid.UUID,
    membership_role_id: uuid.UUID,
    body: ChangeMembershipRoleRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> MembershipRoleResponse:
    """Changes one existing, currently-active role assignment to a
    different role — the portal Access page's single "change role" action
    (Phase 13E-B). Self-change is permitted (no special-case check here or
    in the command): the campaign's own retention invariant, re-evaluated
    on current PostgreSQL state after both the revoke and the new
    assignment apply, is what actually protects an active campaign from
    ending up with no `access.manage` holder — including when the caller
    is changing their own last such assignment. 201, not 200: this both
    revokes the old assignment and creates a new `security.membership_roles`
    row, matching `assign_membership_role_endpoint`'s own status code for
    "a new row now exists," even though an existing row also changed."""
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "membership_role_id": str(membership_role_id),
            **body.model_dump(mode="json"),
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_CHANGE_ROLE_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return MembershipRoleResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = change_membership_role(
        connection,
        membership_role_id=membership_role_id,
        campaign_id=campaign_id,
        new_role_id=body.new_role_id,
        granted_by_membership_id=access.campaign_membership_id,
    )

    record_change_log(
        connection,
        change_action_code=_UPDATED_CHANGE_ACTION,
        schema_name="security",
        table_name="membership_roles",
        record_id=result.membership_role_id,
        entity_id=None,
        world_id=timeline_world_id(connection, access.timeline_id),
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_CHANGE_ROLE_COMMAND_NAME,
        event_id=None,
        previous_status=result.previous_role_code,
        new_status=result.new_role_code,
        changed_fields={
            "previous_membership_role_id": str(result.previous_membership_role_id),
        },
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
    "/campaigns/{campaign_id}/memberships/{campaign_membership_id}/end",
    response_model=EndCampaignMembershipResponse,
    status_code=200,
)
def end_campaign_membership_endpoint(
    campaign_id: uuid.UUID,
    campaign_membership_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> EndCampaignMembershipResponse:
    """Ends one existing, currently open campaign membership — the portal
    Access page's "Remove member" action (Phase 13E-B checkpoint 3,
    `dnd_ai.commands.memberships.end_campaign_membership`). No request
    body: the route path already carries everything this command needs.
    Self-removal is permitted, with no special-case check here or in the
    command — the campaign's own access-manager retention invariant, the
    identical one `revoke_membership_role_endpoint`/`change_membership_
    role_endpoint` already rely on, is what actually protects an active
    campaign from ending up with no `access.manage` holder, including when
    the caller is removing their own last such membership.

    Response contract mirrors `revoke_membership_role_endpoint`'s own
    "200/an id echoed back, not a bodyless 204" shape for the identical
    reason: `begin_idempotent_request`/`complete_idempotent_request` need
    something to cache. `200`, not `201`: this closes an existing row, it
    creates nothing.

    Idempotency/audit mirrors `revoke_membership_role_endpoint` exactly:
    an `Idempotency-Key` replay returns the original cached response
    verbatim, never re-running the command; independent of any key, the
    audit write below is conditioned on `EndCampaignMembershipResult.
    ended`, so a plain retry that lands on an already-ended membership
    (whether or not it reuses a key) writes no second audit row for one
    real removal."""
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "campaign_membership_id": str(campaign_membership_id)
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_END_MEMBERSHIP_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return EndCampaignMembershipResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = end_campaign_membership(
        connection,
        campaign_membership_id=campaign_membership_id,
        campaign_id=campaign_id,
        ended_by_membership_id=access.campaign_membership_id,
    )

    if result.ended:
        record_change_log(
            connection,
            change_action_code=_UPDATED_CHANGE_ACTION,
            schema_name="security",
            table_name="campaign_memberships",
            record_id=campaign_membership_id,
            entity_id=None,
            world_id=timeline_world_id(connection, access.timeline_id),
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=_END_MEMBERSHIP_COMMAND_NAME,
            event_id=None,
            previous_status="active",
            new_status="revoked",
            changed_fields={
                "revoked_membership_role_ids": [
                    str(role_id) for role_id in result.revoked_membership_role_ids
                ],
            },
        )

    response = EndCampaignMembershipResponse(campaign_membership_id=campaign_membership_id)

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=200,
            response_body=response.model_dump(mode="json"),
        )

    return response
