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
of its active role assignments — and, as of checkpoint-5's own correction,
every active character relationship, direct resource grant, and access-group
membership too, so a later reopened membership never silently regains any of
them) — never account creation, invitations, or reactivating a previously-
departed membership. `POST .../memberships`
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

from dnd_ai.commands._pre_write_steps import receipt_params
from dnd_ai.commands.membership_end_plans import prepare_end_membership, write_end_membership
from dnd_ai.commands.membership_role_plans import (
    MEMBERSHIP_RECEIPT,
    prepare_add_member,
    prepare_assign_role,
    prepare_change_role,
    prepare_revoke_role,
    prepare_transfer,
    write_add_member,
    write_assign_role,
    write_change_role,
    write_revoke_role,
    write_transfer,
)
from dnd_ai.domain.access import LOCAL_AUTH_ISSUER, AccessContext
from dnd_ai.domain.authorization import AuthorizationPlan

from .access import require_campaign_capability
from .campaigns import _begin_lifecycle_request
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .r01_route_plans import get_authorization_plan

router = APIRouter(tags=["memberships"])
_Plan = Annotated[AuthorizationPlan, Depends(get_authorization_plan)]

# Access/role administration is distinct from canon mutation — see this
# module's docstring for why every route here requires it instead of
# canon.edit.
_ACCESS_MANAGE_CAPABILITY = "access.manage"

_ADD_MEMBER_COMMAND_NAME = "add_campaign_member"
_ASSIGN_ROLE_COMMAND_NAME = "assign_membership_role"
_REVOKE_ROLE_COMMAND_NAME = "revoke_membership_role"
_CHANGE_ROLE_COMMAND_NAME = "change_membership_role"
_END_MEMBERSHIP_COMMAND_NAME = "end_campaign_membership"
_TRANSFER_OWNERSHIP_COMMAND_NAME = "transfer_campaign_ownership"

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
            MEMBERSHIP_RECEIPT,
            receipt_params(reservation_id, status, response.model_dump(mode="json")),
        )


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
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    """Adds an existing, eligible account to `campaign_id` with one initial role (Phase 13E-B checkpoint 3,
    `dnd_ai.commands.memberships.add_campaign_member`). A keyed-optional pre-write route (R01 S5-E2;
    `dnd_ai.commands.membership_role_plans`): the eligibility rules and their errors are the command's own."""
    replay, reservation_id = _begin_lifecycle_request(
        plan=plan,
        connection=connection,
        access=access,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        command_name=_ADD_MEMBER_COMMAND_NAME,
        payload={"campaign_id": str(campaign_id), **body.model_dump(mode="json")},
    )
    if replay is not None:
        return replay
    prepared = prepare_add_member(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        user_id=body.user_id,
        role_id=body.role_id,
        local_issuer=LOCAL_AUTH_ISSUER,
        reservation_id=reservation_id,
    )
    plan.finalize(connection)
    membership_id, role_assignment_id = write_add_member(
        connection,
        plan,
        prepared,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        user_id=body.user_id,
        correlation_id=correlation_id,
    )
    response = CampaignMembershipResponse(
        campaign_membership_id=membership_id, membership_role_id=role_assignment_id
    )
    _complete_receipt_with(connection, plan, reservation_id, 201, response)
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
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    """A keyed-optional pre-write route (R01 S5-E2). Self-assignment is judged against the pre-command
    authority: `finalize` runs before the insert."""
    replay, reservation_id = _begin_lifecycle_request(
        plan=plan,
        connection=connection,
        access=access,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        command_name=_ASSIGN_ROLE_COMMAND_NAME,
        payload={
            "campaign_membership_id": str(campaign_membership_id),
            **body.model_dump(mode="json"),
        },
    )
    if replay is not None:
        return replay
    prepared = prepare_assign_role(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        target_membership_id=campaign_membership_id,
        role_id=body.role_id,
        reservation_id=reservation_id,
    )
    plan.finalize(connection)
    new_id = write_assign_role(
        connection,
        plan,
        prepared,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        expires_at=body.expires_at,
        correlation_id=correlation_id,
    )
    response = MembershipRoleResponse(membership_role_id=new_id)
    _complete_receipt_with(connection, plan, reservation_id, 201, response)
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
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    """Revokes one existing role assignment (Phase 13E-B checkpoint 2); a keyed-optional pre-write route
    (R01 S5-E2). Self-revocation is permitted and judged against the pre-command authority. An
    already-revoked assignment is the documented no-op: no write and no audit row (a fresh keyed one
    still completes its receipt). The "a manager survives" check runs before `finalize`."""
    replay, reservation_id = _begin_lifecycle_request(
        plan=plan,
        connection=connection,
        access=access,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        command_name=_REVOKE_ROLE_COMMAND_NAME,
        payload={"membership_role_id": str(membership_role_id)},
    )
    if replay is not None:
        return replay
    prepared = prepare_revoke_role(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        membership_role_id=membership_role_id,
        reservation_id=reservation_id,
    )
    plan.finalize(connection)
    write_revoke_role(
        connection,
        plan,
        prepared,
        membership_role_id=membership_role_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
    )
    response = MembershipRoleResponse(membership_role_id=membership_role_id)
    _complete_receipt_with(connection, plan, reservation_id, 200, response)
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
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    """Changes one active role assignment to a different role (Phase 13E-B); a keyed-optional pre-write
    route (R01 S5-E2). Self-change is permitted: the retention pre-check (before `finalize`) counts the
    new assignment, and authority is judged before either write."""
    replay, reservation_id = _begin_lifecycle_request(
        plan=plan,
        connection=connection,
        access=access,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        command_name=_CHANGE_ROLE_COMMAND_NAME,
        payload={"membership_role_id": str(membership_role_id), **body.model_dump(mode="json")},
    )
    if replay is not None:
        return replay
    prepared = prepare_change_role(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        membership_role_id=membership_role_id,
        new_role_id=body.new_role_id,
        reservation_id=reservation_id,
    )
    plan.finalize(connection)
    new_id = write_change_role(
        connection,
        plan,
        prepared,
        membership_role_id=membership_role_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        correlation_id=correlation_id,
    )
    response = MembershipRoleResponse(membership_role_id=new_id)
    _complete_receipt_with(connection, plan, reservation_id, 201, response)
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
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    """Ends one existing, currently open campaign membership: the portal Access page's "Remove member" action
    (Phase 13E-B checkpoint 3); a keyed-optional pre-write route (R01 S5-E3,
    `dnd_ai.commands.membership_end_plans`). No request body. Self-removal is permitted and judged against the
    pre-command authority; the campaign's access-manager retention invariant (checked before `finalize`, with the
    deferred triggers as the backstop) is what protects an active campaign from losing its last `access.manage`
    holder. `200`, not `201`: this closes an existing row. An already-ended membership is the documented no-op:
    no write and no audit row (a fresh keyed one still completes its receipt)."""
    replay, reservation_id = _begin_lifecycle_request(
        plan=plan,
        connection=connection,
        access=access,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        command_name=_END_MEMBERSHIP_COMMAND_NAME,
        payload={"campaign_membership_id": str(campaign_membership_id)},
    )
    if replay is not None:
        return replay
    prepared = prepare_end_membership(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        target_membership_id=campaign_membership_id,
        reservation_id=reservation_id,
    )
    plan.finalize(connection)
    write_end_membership(
        connection,
        plan,
        prepared,
        campaign_membership_id=campaign_membership_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        correlation_id=correlation_id,
    )
    response = EndCampaignMembershipResponse(campaign_membership_id=campaign_membership_id)
    _complete_receipt_with(connection, plan, reservation_id, 200, response)
    return response


class TransferCampaignOwnershipRequest(BaseModel):
    target_campaign_membership_id: uuid.UUID
    relinquish_own_ownership: bool = False


class TransferCampaignOwnershipResponse(BaseModel):
    target_campaign_membership_id: uuid.UUID
    assigned: bool
    relinquished: bool


@router.post(
    "/campaigns/{campaign_id}/ownership-transfer",
    response_model=TransferCampaignOwnershipResponse,
    status_code=200,
)
def transfer_campaign_ownership_endpoint(
    campaign_id: uuid.UUID,
    body: TransferCampaignOwnershipRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> TransferCampaignOwnershipResponse:
    """Makes an existing member a campaign owner and optionally relinquishes the
    caller's own ownership (docs/adr/0020-scoped-system-world-and-campaign-roles.md).
    One transaction and one audit row; a repeat that changes nothing writes none.

    An **unkeyed** pre-write route (R01 S5-E2 amendment; `dnd_ai.commands.membership_role_plans`,
    `R01_UNKEYED_PRE_WRITE_ROUTES`): it stays non-idempotent and an `Idempotency-Key` header is
    ignored. Every lock and refusal precedes `plan.finalize`; the writes and the single audit row
    are declared steps after it."""
    prepared = prepare_transfer(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        target_membership_id=body.target_campaign_membership_id,
        relinquish_own_ownership=body.relinquish_own_ownership,
    )
    plan.finalize(connection)
    result = write_transfer(
        connection,
        plan,
        prepared,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        correlation_id=correlation_id,
    )
    return TransferCampaignOwnershipResponse(
        target_campaign_membership_id=result.target_campaign_membership_id,
        assigned=result.assigned_membership_role_id is not None,
        relinquished=bool(result.revoked_membership_role_ids),
    )
