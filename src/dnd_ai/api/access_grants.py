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

from dnd_ai.commands.access_grants import (
    change_character_relationship,
    create_resource_grant,
    grant_character_relationship,
    revoke_character_relationship,
    revoke_resource_grant,
)
from dnd_ai.domain.access import AccessContext

from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .idempotency import IdempotentReplay, begin_idempotent_request, complete_idempotent_request

router = APIRouter(tags=["access-grants"])

# Access administration is distinct from canon mutation — see this
# module's docstring for why every route here requires it instead of
# canon.edit.
_ACCESS_MANAGE_CAPABILITY = "access.manage"

_GRANT_RELATIONSHIP_COMMAND_NAME = "grant_character_relationship"
_CHANGE_RELATIONSHIP_COMMAND_NAME = "change_character_relationship"
_REVOKE_RELATIONSHIP_COMMAND_NAME = "revoke_character_relationship"
_CREATE_RESOURCE_GRANT_COMMAND_NAME = "create_resource_grant"
_REVOKE_RESOURCE_GRANT_COMMAND_NAME = "revoke_resource_grant"

_CREATED_CHANGE_ACTION = "created"
_UPDATED_CHANGE_ACTION = "updated"


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
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> CharacterRelationshipResponse:
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
            command_name=_GRANT_RELATIONSHIP_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return CharacterRelationshipResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = grant_character_relationship(
        connection,
        campaign_membership_id=campaign_membership_id,
        character_id=body.character_id,
        relationship_type_code=body.relationship_type_code,
        campaign_id=campaign_id,
        expected_world_id=timeline_world_id(connection, access.timeline_id),
        granted_by_membership_id=access.campaign_membership_id,
        timeline_id=body.timeline_id,
        effective_from_world_time_id=body.effective_from_world_time_id,
        effective_to_world_time_id=body.effective_to_world_time_id,
    )

    record_change_log(
        connection,
        change_action_code=_CREATED_CHANGE_ACTION,
        schema_name="security",
        table_name="membership_character_relationships",
        record_id=result.membership_character_relationship_id,
        entity_id=None,
        world_id=timeline_world_id(connection, access.timeline_id),
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_GRANT_RELATIONSHIP_COMMAND_NAME,
        event_id=None,
    )

    response = CharacterRelationshipResponse(
        membership_character_relationship_id=result.membership_character_relationship_id
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
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> CharacterRelationshipResponse:
    """Changes one existing, currently-active character-relationship
    assignment to a different relationship type — the portal Access page's
    "change relationship type" action. Self-change is permitted (no
    special-case check here or in the command): a character relationship
    never carries `access.manage`, so there is no retention invariant for
    this route to protect, unlike `change_membership_role_endpoint`. 201,
    not 200: this both revokes the old assignment and creates a new
    `security.membership_character_relationships` row, matching `grant_
    character_relationship_endpoint`'s own status code for "a new row now
    exists," even though an existing row also changed.

    `expected_world_id` (checkpoint-4 review correction) is resolved
    server-side from the caller's own already-authorized campaign timeline
    (`timeline_world_id(connection, access.timeline_id)`), exactly like
    `grant_character_relationship_endpoint`'s identical argument — never
    accepted from the request body, so a caller can never widen the world
    the command checks the relationship's character against."""
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "membership_character_relationship_id": str(membership_character_relationship_id),
            **body.model_dump(mode="json"),
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_CHANGE_RELATIONSHIP_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return CharacterRelationshipResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = change_character_relationship(
        connection,
        membership_character_relationship_id=membership_character_relationship_id,
        campaign_id=campaign_id,
        expected_world_id=timeline_world_id(connection, access.timeline_id),
        new_relationship_type_id=body.new_relationship_type_id,
        granted_by_membership_id=access.campaign_membership_id,
    )

    record_change_log(
        connection,
        change_action_code=_UPDATED_CHANGE_ACTION,
        schema_name="security",
        table_name="membership_character_relationships",
        record_id=result.membership_character_relationship_id,
        entity_id=None,
        world_id=timeline_world_id(connection, access.timeline_id),
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_CHANGE_RELATIONSHIP_COMMAND_NAME,
        event_id=None,
        previous_status=result.previous_relationship_type_code,
        new_status=result.new_relationship_type_code,
        changed_fields={
            "previous_membership_character_relationship_id": (
                str(result.previous_membership_character_relationship_id)
            ),
        },
    )

    response = CharacterRelationshipResponse(
        membership_character_relationship_id=result.membership_character_relationship_id
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
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> CharacterRelationshipResponse:
    """Revokes one existing, currently-active character-relationship
    assignment — the portal Access page's "revoke character relationship"
    action.

    Response contract: `200`, not the pre-hardening bare `204 No Content` —
    matching the identical correction `dnd_ai.api.memberships.
    revoke_membership_role_endpoint` already made (Phase 13E-B checkpoint 2
    correction). A bare `204`/no-`Idempotency-Key` route relied on `revoke_
    character_relationship`'s own state-idempotency (a retry against an
    already-revoked row is a harmless no-op) to cover *state*, but every
    call — including a plain retry with no key at all — wrote its own
    `audit.change_log` row unconditionally, so an ordinary network retry
    could durably record two revocation events for one real revocation.
    Fixed the same two ways: (1) an `Idempotency-Key` replay returns the
    original cached response verbatim, never re-running the command at
    all; (2) even *without* a matching key, the audit write below is now
    conditioned on `RevokeCharacterRelationshipResult.revoked`, so a second
    call that lands on an already-revoked row writes no second row. A
    `CharacterRelationshipResponse` echoing `membership_character_
    relationship_id` back (reusing the existing grant-relationship response
    shape) gives `begin_idempotent_request`/`complete_idempotent_request`
    something to cache, which a bodyless `204` could not."""
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "membership_character_relationship_id": str(membership_character_relationship_id)
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_REVOKE_RELATIONSHIP_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return CharacterRelationshipResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = revoke_character_relationship(
        connection,
        membership_character_relationship_id=membership_character_relationship_id,
        campaign_id=campaign_id,
    )

    if result.revoked:
        record_change_log(
            connection,
            change_action_code=_UPDATED_CHANGE_ACTION,
            schema_name="security",
            table_name="membership_character_relationships",
            record_id=membership_character_relationship_id,
            entity_id=None,
            world_id=timeline_world_id(connection, access.timeline_id),
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=_REVOKE_RELATIONSHIP_COMMAND_NAME,
            event_id=None,
        )

    response = CharacterRelationshipResponse(
        membership_character_relationship_id=membership_character_relationship_id
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
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> ResourceGrantResponse:
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
            command_name=_CREATE_RESOURCE_GRANT_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return ResourceGrantResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = create_resource_grant(
        connection,
        campaign_id=campaign_id,
        grantee_campaign_membership_id=body.grantee_campaign_membership_id,
        grantee_access_group_id=body.grantee_access_group_id,
        character_id=body.character_id,
        entity_id=body.entity_id,
        knowledge_item_id=body.knowledge_item_id,
        quest_id=body.quest_id,
        session_id=body.session_id,
        event_id=body.event_id,
        capability_code=body.capability_code,
        effect=body.effect,
        expected_world_id=timeline_world_id(connection, access.timeline_id),
        granted_by_membership_id=access.campaign_membership_id,
        reason=body.reason,
    )

    target_kind, target_id = _resource_grant_target_kind_and_id(body)
    record_change_log(
        connection,
        change_action_code=_CREATED_CHANGE_ACTION,
        schema_name="security",
        table_name="resource_grants",
        record_id=result.resource_grant_id,
        entity_id=None,
        world_id=timeline_world_id(connection, access.timeline_id),
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_CREATE_RESOURCE_GRANT_COMMAND_NAME,
        event_id=None,
        changed_fields={
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
    )

    response = ResourceGrantResponse(resource_grant_id=result.resource_grant_id)

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=201,
            response_body=response.model_dump(mode="json"),
        )

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
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> ResourceGrantResponse:
    """Revokes one existing, currently-active resource grant — the portal
    Access page's "Revoke direct resource access" action.

    Response contract (checkpoint 5): `200`/`ResourceGrantResponse`
    (`{resource_grant_id: UUID}`, reusing the existing create-grant response
    shape), not the pre-hardening bare `204 No Content` — the identical
    correction `revoke_character_relationship_endpoint`/`dnd_ai.api.
    memberships.revoke_membership_role_endpoint` already made. A bare
    `204`/no-`Idempotency-Key` route relied on `revoke_resource_grant`'s own
    state-idempotency (a retry against an already-revoked row is a harmless
    no-op) to cover *state*, but every call — including a plain retry with
    no key at all — wrote its own `audit.change_log` row unconditionally,
    so an ordinary network retry could durably record two revocation events
    for one real revocation. Fixed the same two ways: (1) an
    `Idempotency-Key` replay returns the original cached response verbatim,
    never re-running the command at all; (2) even *without* a matching key,
    the audit write below is now conditioned on `RevokeResourceGrantResult.
    revoked`, so a second call that lands on an already-revoked row writes
    no second row."""
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {"resource_grant_id": str(resource_grant_id)}
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_REVOKE_RESOURCE_GRANT_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return ResourceGrantResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = revoke_resource_grant(
        connection, resource_grant_id=resource_grant_id, campaign_id=campaign_id
    )

    if result.revoked:
        record_change_log(
            connection,
            change_action_code=_UPDATED_CHANGE_ACTION,
            schema_name="security",
            table_name="resource_grants",
            record_id=resource_grant_id,
            entity_id=None,
            world_id=timeline_world_id(connection, access.timeline_id),
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=_REVOKE_RESOURCE_GRANT_COMMAND_NAME,
            event_id=None,
            changed_fields={
                "grantee_campaign_membership_id": (
                    str(result.grantee_campaign_membership_id)
                    if result.grantee_campaign_membership_id is not None
                    else None
                ),
                "grantee_access_group_id": (
                    str(result.grantee_access_group_id)
                    if result.grantee_access_group_id is not None
                    else None
                ),
                "target_kind": result.target_field_name,
                "target_id": (str(result.target_id) if result.target_id is not None else None),
                "capability_code": result.capability_code,
                "effect": result.effect,
            },
        )

    response = ResourceGrantResponse(resource_grant_id=resource_grant_id)

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=200,
            response_body=response.model_dump(mode="json"),
        )

    return response
