"""HTTP endpoints for character relationships and resource grants.

Exposes `grant_character_relationship`, `change_character_relationship`
(Phase 13E-B character-relationship-management checkpoint),
`revoke_character_relationship`, `create_resource_grant`, and
`revoke_resource_grant` over HTTP, on the same already-delivered OIDC
authentication, transaction management, and access resolution every other
command router uses. `CreateResourceGrantRequest` exposes all six
`security.resource_grants` target kinds and `GrantCharacterRelationshipRequest`
exposes the full `timeline_id`/`effective_from_world_time_id`/`effective_
to_world_time_id` temporal scope — see `dnd_ai.commands.access_grants`'
own module docstring for the validation each one gets.

Every route runs on the request's own `get_connection` transaction — these
commands take a `Connection` directly (no `_impl`/engine-wrapper split;
see `dnd_ai.commands.access_grants`' own docstring for why).

Authorization: all five routes require `access.manage`, the same
capability `dnd_ai.api.memberships` requires — granting a character
relationship or a typed resource override is access administration, the
same category of action as assigning a role, not a canon mutation.

Idempotency: `grant_character_relationship`/`change_character_relationship`/
`create_resource_grant` use the same durable `security.idempotent_requests`
mechanism `dnd_ai.api.memberships` uses for its own create/change-shaped
commands — a naive retry would otherwise hit `ux_membership_character_
relationships_active_type`/`ux_resource_grants_active` (existing
`IntegrityError` handler, 409) instead of replaying the original response.
`revoke_character_relationship_endpoint`/`revoke_resource_grant_endpoint`
also use it now (character-relationship-management checkpoint correction
for the former; checkpoint 5 closed the identical gap for the latter,
matching the identical fix Phase 13E-B checkpoint 2 already made to
`dnd_ai.api.memberships.revoke_membership_role_endpoint` — see that
route's own docstring): a bare-`204`/no-key route relied on the underlying
command's state-idempotency alone, which covers *state* but not the
*audit trail* (every call wrote its own row unconditionally).

Auditing: every successful call records one `audit.change_log` row.
`revoke_character_relationship_endpoint`/`change_character_relationship_
endpoint`/`revoke_resource_grant_endpoint` (checkpoint 5 added the latter)
write theirs only for an actual state change — see each route's own
docstring. `entity_id` is always `None` for the same reason `dnd_ai.api.
memberships` gives — none of `security.membership_character_relationships`/
`.resource_grants` is a `core.entities` row. `world_id` is resolved
server-side from the campaign's own pinned timeline.

Checkpoint-5 correction: `create_resource_grant_endpoint`/`revoke_resource_
grant_endpoint`'s own audit rows previously carried no `changed_fields` at
all — `record_id` alone (the `resource_grant_id`) told a reviewer *that*
some resource grant changed, but not *what* changed: which kind of grantee
(a member or an access group), which one, which of the six target kinds and
resource, which capability, or whether the change was an `allow` or a
`deny`. Reconstructing any of that required a second, separate query against
a row that, for a revocation, may since have been further superseded or
deleted-by-cascade (a campaign/membership/target archival cascades onto
`security.resource_grants` via `ON DELETE CASCADE` in a few of its foreign
keys — see migration 080). Both routes now record a bounded, non-free-form
`changed_fields` payload — `grantee_campaign_membership_id`/`grantee_access_
group_id` (exactly one non-null), `target_kind`/`target_id`, `capability_
code`, and `effect` — identifying exactly what the grant was without ever
recording `reason` (free-form caller text) or anything from `dnd_ai.api.
local_auth`'s own "Never store" list. `create_resource_grant_endpoint` reads
these straight from the already-validated request body (the command already
succeeded by the time the audit row is written, so the body's own values are
exactly what was persisted); `revoke_resource_grant_endpoint` reads them from
`RevokeResourceGrantResult`'s own new fields — populated server-side by
`revoke_resource_grant()` from the row it already locks, never re-derived
from caller input, so a caller who only ever supplies `resource_grant_id`
still yields a complete audit record of what was actually revoked."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.commands._pre_write_steps import receipt_params
from dnd_ai.commands.access_grant_plans import (
    GRANT_RECEIPT,
    prepare_change_relationship,
    prepare_create_grant,
    prepare_grant_relationship,
    prepare_revoke_grant,
    prepare_revoke_relationship,
    write_change_relationship,
    write_create_grant,
    write_grant_relationship,
    write_revoke_grant,
    write_revoke_relationship,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authorization import AuthorizationPlan

from .access import require_campaign_capability
from .campaigns import _begin_lifecycle_request
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .r01_route_plans import get_authorization_plan

router = APIRouter(tags=["access-grants"])
_Plan = Annotated[AuthorizationPlan, Depends(get_authorization_plan)]

# Access administration is distinct from canon mutation — see this
# module's docstring for why every route here requires it instead of
# canon.edit.
_ACCESS_MANAGE_CAPABILITY = "access.manage"

_GRANT_RELATIONSHIP_COMMAND_NAME = "grant_character_relationship"
_CHANGE_RELATIONSHIP_COMMAND_NAME = "change_character_relationship"
_REVOKE_RELATIONSHIP_COMMAND_NAME = "revoke_character_relationship"
_CREATE_RESOURCE_GRANT_COMMAND_NAME = "create_resource_grant"
_REVOKE_RESOURCE_GRANT_COMMAND_NAME = "revoke_resource_grant"


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
            GRANT_RECEIPT,
            receipt_params(reservation_id, status, response.model_dump(mode="json")),
        )


# ---------------------------------------------------------------------------
# Request/response contracts
# ---------------------------------------------------------------------------


class GrantCharacterRelationshipRequest(BaseModel):
    character_id: uuid.UUID
    relationship_type_code: str
    timeline_id: uuid.UUID | None = None
    effective_from_world_time_id: uuid.UUID | None = None
    effective_to_world_time_id: uuid.UUID | None = None


class CharacterRelationshipResponse(BaseModel):
    membership_character_relationship_id: uuid.UUID


class ChangeCharacterRelationshipRequest(BaseModel):
    new_relationship_type_id: uuid.UUID


class CreateResourceGrantRequest(BaseModel):
    capability_code: str
    effect: str = "allow"
    grantee_campaign_membership_id: uuid.UUID | None = None
    grantee_access_group_id: uuid.UUID | None = None
    character_id: uuid.UUID | None = None
    entity_id: uuid.UUID | None = None
    knowledge_item_id: uuid.UUID | None = None
    quest_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    event_id: uuid.UUID | None = None
    reason: str | None = None


class ResourceGrantResponse(BaseModel):
    resource_grant_id: uuid.UUID


# Mirrors dnd_ai.commands.access_grants._RESOURCE_GRANT_TARGET_FIELDS exactly
# (that tuple is module-private, so this route layer keeps its own copy
# rather than reaching into another module's private name) — the six
# `CreateResourceGrantRequest` fields that name a resource-grant target kind,
# in the same order. Used only to build this checkpoint's own audit
# `changed_fields` payload (see this module's own docstring, "Checkpoint-5
# correction"), never for validation — the command itself is the only thing
# that enforces "exactly one."
_RESOURCE_GRANT_TARGET_FIELDS = (
    "character_id",
    "entity_id",
    "knowledge_item_id",
    "quest_id",
    "session_id",
    "event_id",
)


def _resource_grant_target_kind_and_id(
    body: CreateResourceGrantRequest,
) -> tuple[str | None, uuid.UUID | None]:
    """The one non-`None` target field on an already-validated (command
    already succeeded) `CreateResourceGrantRequest`, or `(None, None)` for
    the malformed-shape case the command's own `CHECK` constraint would have
    already rejected before this is ever called."""
    for field_name in _RESOURCE_GRANT_TARGET_FIELDS:
        value = getattr(body, field_name)
        if value is not None:
            return field_name, value
    return None, None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/campaigns/{campaign_id}/memberships/{campaign_membership_id}/character-relationships",
    response_model=CharacterRelationshipResponse,
    status_code=201,
)
def grant_character_relationship_endpoint(
    campaign_id: uuid.UUID,
    campaign_membership_id: uuid.UUID,
    body: GrantCharacterRelationshipRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    """A keyed-optional pre-write route (R01 S5-E4, `dnd_ai.commands.access_grant_plans`). The eligibility rules
    and their errors are the command's own; authority is judged at `finalize`, before the insert (a self-grant is
    judged on the pre-command authority)."""
    replay, reservation_id = _begin_lifecycle_request(
        plan=plan,
        connection=connection,
        access=access,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        command_name=_GRANT_RELATIONSHIP_COMMAND_NAME,
        payload={
            "campaign_membership_id": str(campaign_membership_id),
            **body.model_dump(mode="json"),
        },
    )
    if replay is not None:
        return replay
    prepared = prepare_grant_relationship(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        target_membership_id=campaign_membership_id,
        character_id=body.character_id,
        relationship_type_code=body.relationship_type_code,
        timeline_id=body.timeline_id,
        time_from_id=body.effective_from_world_time_id,
        time_to_id=body.effective_to_world_time_id,
        reservation_id=reservation_id,
    )
    plan.finalize(connection)
    new_id = write_grant_relationship(
        connection,
        plan,
        prepared,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        correlation_id=correlation_id,
    )
    response = CharacterRelationshipResponse(membership_character_relationship_id=new_id)
    _complete_receipt_with(connection, plan, reservation_id, 201, response)
    return response


@router.post(
    "/campaigns/{campaign_id}/character-relationships/{membership_character_relationship_id}/change",
    response_model=CharacterRelationshipResponse,
    status_code=201,
)
def change_character_relationship_endpoint(
    campaign_id: uuid.UUID,
    membership_character_relationship_id: uuid.UUID,
    body: ChangeCharacterRelationshipRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    """Changes one existing, currently-active character-relationship assignment to a different relationship type —
    the portal Access page's "change relationship type" action; a keyed-optional pre-write route (R01 S5-E4,
    `dnd_ai.commands.access_grant_plans`). Self-change is permitted (a character relationship never carries
    `access.manage`, so there is no retention invariant to protect). 201, not 200: this both revokes the old
    assignment and creates a new row. The world the character is checked against is the campaign's own, resolved
    server-side, never accepted from the request body. The owning membership is locked **before** the relationship
    row (the order every end of a membership takes), which is what removes the change-versus-end deadlock."""
    replay, reservation_id = _begin_lifecycle_request(
        plan=plan,
        connection=connection,
        access=access,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        command_name=_CHANGE_RELATIONSHIP_COMMAND_NAME,
        payload={
            "membership_character_relationship_id": str(membership_character_relationship_id),
            **body.model_dump(mode="json"),
        },
    )
    if replay is not None:
        return replay
    prepared = prepare_change_relationship(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        relationship_id=membership_character_relationship_id,
        new_type_id=body.new_relationship_type_id,
        reservation_id=reservation_id,
    )
    plan.finalize(connection)
    new_id = write_change_relationship(
        connection,
        plan,
        prepared,
        relationship_id=membership_character_relationship_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        correlation_id=correlation_id,
    )
    response = CharacterRelationshipResponse(membership_character_relationship_id=new_id)
    _complete_receipt_with(connection, plan, reservation_id, 201, response)
    return response


@router.post(
    "/campaigns/{campaign_id}/character-relationships/{membership_character_relationship_id}/revoke",
    response_model=CharacterRelationshipResponse,
    status_code=200,
)
def revoke_character_relationship_endpoint(
    campaign_id: uuid.UUID,
    membership_character_relationship_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    """Revokes one existing, currently-active character-relationship assignment — the portal Access page's
    "revoke character relationship" action; a keyed-optional pre-write route (R01 S5-E4,
    `dnd_ai.commands.access_grant_plans`). `200` and the relationship id. An already-revoked assignment is the
    documented no-op: no write and no audit row (a fresh keyed request still completes its receipt)."""
    replay, reservation_id = _begin_lifecycle_request(
        plan=plan,
        connection=connection,
        access=access,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        command_name=_REVOKE_RELATIONSHIP_COMMAND_NAME,
        payload={"membership_character_relationship_id": str(membership_character_relationship_id)},
    )
    if replay is not None:
        return replay
    prepared = prepare_revoke_relationship(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        relationship_id=membership_character_relationship_id,
        reservation_id=reservation_id,
    )
    plan.finalize(connection)
    write_revoke_relationship(
        connection,
        plan,
        prepared,
        relationship_id=membership_character_relationship_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
    )
    response = CharacterRelationshipResponse(
        membership_character_relationship_id=membership_character_relationship_id
    )
    _complete_receipt_with(connection, plan, reservation_id, 200, response)
    return response


@router.post(
    "/campaigns/{campaign_id}/resource-grants",
    response_model=ResourceGrantResponse,
    status_code=201,
)
def create_resource_grant_endpoint(
    campaign_id: uuid.UUID,
    body: CreateResourceGrantRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    """Creates one resource grant (an allow or a deny) for a membership or an access group, on one of the six
    target kinds; a keyed-optional pre-write route (R01 S5-E4, `dnd_ai.commands.access_grant_plans`). A group
    grantee's row is the first row the request locks (see that module). The audit row carries the grant's bounded,
    non-free-form `changed_fields` (never `reason`)."""
    replay, reservation_id = _begin_lifecycle_request(
        plan=plan,
        connection=connection,
        access=access,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        command_name=_CREATE_RESOURCE_GRANT_COMMAND_NAME,
        payload={"campaign_id": str(campaign_id), **body.model_dump(mode="json")},
    )
    if replay is not None:
        return replay
    prepared = prepare_create_grant(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        grantee_membership_id=body.grantee_campaign_membership_id,
        grantee_group_id=body.grantee_access_group_id,
        capability_code=body.capability_code,
        effect=body.effect,
        character_id=body.character_id,
        entity_id=body.entity_id,
        knowledge_item_id=body.knowledge_item_id,
        quest_id=body.quest_id,
        session_id=body.session_id,
        event_id=body.event_id,
        reservation_id=reservation_id,
    )
    plan.finalize(connection)
    target_kind, target_id = _resource_grant_target_kind_and_id(body)
    new_id = write_create_grant(
        connection,
        plan,
        prepared,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        grantee_membership_id=body.grantee_campaign_membership_id,
        grantee_group_id=body.grantee_access_group_id,
        effect=body.effect,
        character_id=body.character_id,
        entity_id=body.entity_id,
        knowledge_item_id=body.knowledge_item_id,
        quest_id=body.quest_id,
        session_id=body.session_id,
        event_id=body.event_id,
        reason=body.reason,
        changed={
            "grantee_campaign_membership_id": (
                str(body.grantee_campaign_membership_id)
                if body.grantee_campaign_membership_id is not None
                else None
            ),
            "grantee_access_group_id": (
                str(body.grantee_access_group_id)
                if body.grantee_access_group_id is not None
                else None
            ),
            "target_kind": target_kind,
            "target_id": str(target_id) if target_id is not None else None,
            "capability_code": body.capability_code,
            "effect": body.effect,
        },
        correlation_id=correlation_id,
    )
    response = ResourceGrantResponse(resource_grant_id=new_id)
    _complete_receipt_with(connection, plan, reservation_id, 201, response)
    return response


@router.post(
    "/campaigns/{campaign_id}/resource-grants/{resource_grant_id}/revoke",
    response_model=ResourceGrantResponse,
    status_code=200,
)
def revoke_resource_grant_endpoint(
    campaign_id: uuid.UUID,
    resource_grant_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    plan: _Plan,
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> Any:
    """Revokes one existing, currently-active resource grant — the portal Access page's "Revoke direct resource
    access" action; a keyed-optional pre-write route (R01 S5-E4, `dnd_ai.commands.access_grant_plans`). `200` and
    the grant id. An already-revoked grant is the documented no-op: no write and no audit row (a fresh keyed
    request still completes its receipt)."""
    replay, reservation_id = _begin_lifecycle_request(
        plan=plan,
        connection=connection,
        access=access,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        command_name=_REVOKE_RESOURCE_GRANT_COMMAND_NAME,
        payload={"resource_grant_id": str(resource_grant_id)},
    )
    if replay is not None:
        return replay
    prepared = prepare_revoke_grant(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=access.user_id,
        actor_membership_id=access.campaign_membership_id,
        resource_grant_id=resource_grant_id,
        reservation_id=reservation_id,
    )
    plan.finalize(connection)
    write_revoke_grant(
        connection,
        plan,
        prepared,
        resource_grant_id=resource_grant_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
    )
    response = ResourceGrantResponse(resource_grant_id=resource_grant_id)
    _complete_receipt_with(connection, plan, reservation_id, 200, response)
    return response
