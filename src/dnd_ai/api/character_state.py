"""Non-combat character-state endpoints — Phase 11 workstream 6.

Exposes `dnd_ai.commands.character_state.adjust_hit_points`/
`apply_character_condition`/`remove_character_condition`/
`adjust_character_resource` over HTTP, on the same already-delivered OIDC
authentication, transaction management, and access resolution every other
command router uses. Mirrors `dnd_ai.api.movement`'s shape closely — see
that module's own docstring for the template this one follows.

Authorization: `canon.edit`, the same GM/adapter-level scoping `dnd_ai.
api.movement`/`.encounters` already use for their own canon-affecting
mutations. Extending that to a narrower, player-initiated capability (a
player healing their own character with a potion, for instance) is future
scope once a caller actually needs it — the same "don't invent it
speculatively" deferral `dnd_ai.api.movement`'s own docstring already
states for its identical first cut.

All four routes pass `allow_foundry_system=True` to `require_campaign_
capability` (Phase 11 workstream 2 correction) — this module is squarely
the "synchronize non-combat HP/condition/resource state" surface a Foundry
adapter exists to drive, and none of the four names an `external_system_id`
of its own for `dnd_ai.domain.access.assert_foundry_system_matches` to
check (contrast `dnd_ai.api.integration`), so `require_campaign_
capability`'s own world-binding check is the only additional gate a
Foundry principal needs here. See `dnd_ai.domain.access.
AuthenticatedPrincipal`'s docstring for the defect this correction closes
and why every route accepting a Foundry credential must opt in
explicitly rather than being reachable by default.

Idempotency: every route here wires the durable `security.
idempotent_requests` mechanism (`dnd_ai.api.idempotency`) every other
create/mutate endpoint uses, protecting a dropped-response retry from
double-applying a heal, condition change, or resource spend — none of
these four operations has its own natural dedup key the way `narrative.
encounter_turns`' unique index gives `resolve_combat_turn_endpoint` one.

Auditing: one `audit.change_log` row per call that actually changed
something (`result.changed`); a no-op call (see each command's own
docstring — healing at full HP, applying an already-applied condition,
removing one not present, adjusting a resource by a net-zero delta)
records neither an event nor an audit row, mirroring `enter_location_
endpoint`'s identical "nothing changed, nothing to log" rule. `entity_id`
is always `character_id` — none of `campaign.character_state`/
`.character_conditions`/`.character_resources` is itself a `core.
entities` row, the same owning-entity indirection `dnd_ai.api.movement`
already applies for `character_location_history`. `world_id` is resolved
server-side from the campaign's own pinned timeline, never caller-
supplied. `acting_external_system_id` (Phase 11 workstream 2 correction)
is always `access.principal.foundry_external_system_id` — `None` for an
OIDC-authenticated GM, the authenticating system for a Foundry adapter —
so the audit trail can distinguish the two without losing the linked
`actor_user_id` either way (`dnd_ai.api.audit.record_change_log`'s own
docstring).

`record_id=None` on every call here — the first callers of `record_change_
log` to do so. `campaign.character_state`/`.character_conditions`/
`.character_resources` all have composite primary keys
`(timeline_id, character_id[, ...])`, not a single surrogate id column,
so there is no one `record_id` to name; `audit.change_log.record_id`'s
own column comment already documents it as "unconstrained by design," and
`entity_id` (always set to `character_id` here) plus `event_id` together
already identify what changed and why without it.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.commands.character_state import (
    _adjust_character_resource_impl,
    _adjust_hit_points_impl,
    _apply_character_condition_impl,
    _remove_character_condition_impl,
)
from dnd_ai.domain.access import AccessContext

from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .idempotency import IdempotentReplay, begin_idempotent_request, complete_idempotent_request

router = APIRouter(tags=["character-state"])

# Canon-affecting mutation, same first-cut scoping dnd_ai.api.movement/
# .encounters already chose — see this module's own docstring.
_CANON_EDIT_CAPABILITY = "canon.edit"

_ADJUST_HIT_POINTS_COMMAND_NAME = "adjust_hit_points"
_APPLY_CONDITION_COMMAND_NAME = "apply_character_condition"
_REMOVE_CONDITION_COMMAND_NAME = "remove_character_condition"
_ADJUST_RESOURCE_COMMAND_NAME = "adjust_character_resource"

_CREATED_CHANGE_ACTION = "created"
_UPDATED_CHANGE_ACTION = "updated"
_DELETED_CHANGE_ACTION = "deleted"


# ---------------------------------------------------------------------------
# Request/response contracts
# ---------------------------------------------------------------------------


class AdjustHitPointsRequest(BaseModel):
    world_time_id: uuid.UUID
    delta: int
    session_id: uuid.UUID | None = None
    details: str | None = None


class AdjustHitPointsResponse(BaseModel):
    event_id: uuid.UUID | None
    previous_hit_points: int
    new_hit_points: int
    changed: bool


class ApplyCharacterConditionRequest(BaseModel):
    world_time_id: uuid.UUID
    # A real rules.conditions row, not a bare code — see
    # dnd_ai.commands.character_state._apply_character_condition_impl's
    # own docstring for why (code is only unique per ruleset_version_id).
    condition_id: uuid.UUID
    source_description: str | None = None
    session_id: uuid.UUID | None = None
    details: str | None = None


class ApplyCharacterConditionResponse(BaseModel):
    event_id: uuid.UUID | None
    changed: bool


class RemoveCharacterConditionRequest(BaseModel):
    world_time_id: uuid.UUID
    session_id: uuid.UUID | None = None
    details: str | None = None


class RemoveCharacterConditionResponse(BaseModel):
    event_id: uuid.UUID | None
    changed: bool


class AdjustCharacterResourceRequest(BaseModel):
    world_time_id: uuid.UUID
    # A real rules.resource_definitions row, not a bare code — same
    # reasoning as ApplyCharacterConditionRequest.condition_id above.
    resource_definition_id: uuid.UUID
    delta: int
    session_id: uuid.UUID | None = None
    details: str | None = None


class AdjustCharacterResourceResponse(BaseModel):
    event_id: uuid.UUID | None
    previous_amount: int
    new_amount: int
    changed: bool


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/campaigns/{campaign_id}/characters/{character_id}/hit-points",
    response_model=AdjustHitPointsResponse,
    status_code=200,
)
def adjust_hit_points_endpoint(
    campaign_id: uuid.UUID,  # noqa: ARG001
    character_id: uuid.UUID,
    body: AdjustHitPointsRequest,
    access: Annotated[
        AccessContext,
        Depends(require_campaign_capability(_CANON_EDIT_CAPABILITY, allow_foundry_system=True)),
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> AdjustHitPointsResponse:
    assert access.principal is not None
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "character_id": str(character_id),
            **body.model_dump(mode="json"),
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_ADJUST_HIT_POINTS_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return AdjustHitPointsResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = _adjust_hit_points_impl(
        connection,
        timeline_id=access.timeline_id,
        character_id=character_id,
        world_time_id=body.world_time_id,
        delta=body.delta,
        campaign_id=campaign_id,
        session_id=body.session_id,
        details=body.details,
    )

    if result.changed:
        record_change_log(
            connection,
            change_action_code=_UPDATED_CHANGE_ACTION,
            schema_name="campaign",
            table_name="character_state",
            record_id=None,
            entity_id=character_id,
            world_id=timeline_world_id(connection, access.timeline_id),
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=_ADJUST_HIT_POINTS_COMMAND_NAME,
            event_id=result.event_id,
            acting_external_system_id=access.principal.foundry_external_system_id,
            acting_foundry_actor_id=access.principal.foundry_claimed_actor_id,
        )

    response = AdjustHitPointsResponse(
        event_id=result.event_id,
        previous_hit_points=result.previous_hit_points,
        new_hit_points=result.new_hit_points,
        changed=result.changed,
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
    "/campaigns/{campaign_id}/characters/{character_id}/conditions",
    response_model=ApplyCharacterConditionResponse,
    status_code=200,
)
def apply_character_condition_endpoint(
    campaign_id: uuid.UUID,  # noqa: ARG001
    character_id: uuid.UUID,
    body: ApplyCharacterConditionRequest,
    access: Annotated[
        AccessContext,
        Depends(require_campaign_capability(_CANON_EDIT_CAPABILITY, allow_foundry_system=True)),
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> ApplyCharacterConditionResponse:
    assert access.principal is not None
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "character_id": str(character_id),
            **body.model_dump(mode="json"),
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_APPLY_CONDITION_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return ApplyCharacterConditionResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = _apply_character_condition_impl(
        connection,
        timeline_id=access.timeline_id,
        character_id=character_id,
        condition_id=body.condition_id,
        world_time_id=body.world_time_id,
        source_description=body.source_description,
        campaign_id=campaign_id,
        session_id=body.session_id,
        details=body.details,
    )

    if result.changed:
        record_change_log(
            connection,
            change_action_code=_CREATED_CHANGE_ACTION,
            schema_name="campaign",
            table_name="character_conditions",
            record_id=None,
            entity_id=character_id,
            world_id=timeline_world_id(connection, access.timeline_id),
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=_APPLY_CONDITION_COMMAND_NAME,
            event_id=result.event_id,
            acting_external_system_id=access.principal.foundry_external_system_id,
            acting_foundry_actor_id=access.principal.foundry_claimed_actor_id,
        )

    response = ApplyCharacterConditionResponse(event_id=result.event_id, changed=result.changed)

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=200,
            response_body=response.model_dump(mode="json"),
        )

    return response


@router.post(
    "/campaigns/{campaign_id}/characters/{character_id}/conditions/{condition_id}/remove",
    response_model=RemoveCharacterConditionResponse,
    status_code=200,
)
def remove_character_condition_endpoint(
    campaign_id: uuid.UUID,  # noqa: ARG001
    character_id: uuid.UUID,
    condition_id: uuid.UUID,
    body: RemoveCharacterConditionRequest,
    access: Annotated[
        AccessContext,
        Depends(require_campaign_capability(_CANON_EDIT_CAPABILITY, allow_foundry_system=True)),
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> RemoveCharacterConditionResponse:
    assert access.principal is not None
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "character_id": str(character_id),
            "condition_id": str(condition_id),
            **body.model_dump(mode="json"),
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_REMOVE_CONDITION_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return RemoveCharacterConditionResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = _remove_character_condition_impl(
        connection,
        timeline_id=access.timeline_id,
        character_id=character_id,
        condition_id=condition_id,
        world_time_id=body.world_time_id,
        campaign_id=campaign_id,
        session_id=body.session_id,
        details=body.details,
    )

    if result.changed:
        record_change_log(
            connection,
            change_action_code=_DELETED_CHANGE_ACTION,
            schema_name="campaign",
            table_name="character_conditions",
            record_id=None,
            entity_id=character_id,
            world_id=timeline_world_id(connection, access.timeline_id),
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=_REMOVE_CONDITION_COMMAND_NAME,
            event_id=result.event_id,
            acting_external_system_id=access.principal.foundry_external_system_id,
            acting_foundry_actor_id=access.principal.foundry_claimed_actor_id,
        )

    response = RemoveCharacterConditionResponse(event_id=result.event_id, changed=result.changed)

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=200,
            response_body=response.model_dump(mode="json"),
        )

    return response


@router.post(
    "/campaigns/{campaign_id}/characters/{character_id}/resources",
    response_model=AdjustCharacterResourceResponse,
    status_code=200,
)
def adjust_character_resource_endpoint(
    campaign_id: uuid.UUID,  # noqa: ARG001
    character_id: uuid.UUID,
    body: AdjustCharacterResourceRequest,
    access: Annotated[
        AccessContext,
        Depends(require_campaign_capability(_CANON_EDIT_CAPABILITY, allow_foundry_system=True)),
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> AdjustCharacterResourceResponse:
    assert access.principal is not None
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "character_id": str(character_id),
            **body.model_dump(mode="json"),
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_ADJUST_RESOURCE_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return AdjustCharacterResourceResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = _adjust_character_resource_impl(
        connection,
        timeline_id=access.timeline_id,
        character_id=character_id,
        resource_definition_id=body.resource_definition_id,
        delta=body.delta,
        world_time_id=body.world_time_id,
        campaign_id=campaign_id,
        session_id=body.session_id,
        details=body.details,
    )

    if result.changed:
        record_change_log(
            connection,
            change_action_code=_UPDATED_CHANGE_ACTION,
            schema_name="campaign",
            table_name="character_resources",
            record_id=None,
            entity_id=character_id,
            world_id=timeline_world_id(connection, access.timeline_id),
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=_ADJUST_RESOURCE_COMMAND_NAME,
            event_id=result.event_id,
            acting_external_system_id=access.principal.foundry_external_system_id,
            acting_foundry_actor_id=access.principal.foundry_claimed_actor_id,
        )

    response = AdjustCharacterResourceResponse(
        event_id=result.event_id,
        previous_amount=result.previous_amount,
        new_amount=result.new_amount,
        changed=result.changed,
    )

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=200,
            response_body=response.model_dump(mode="json"),
        )

    return response
