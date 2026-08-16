"""Interaction performance and check-resolution endpoints.

Exposes `perform_interaction` and
`resolve_check` (docs/PHASE6_VERIFICATION.md) over HTTP, on the same
already-delivered OIDC authentication (`dnd_ai.api.auth`), transaction
management (`dnd_ai.api.deps`), and access resolution (`dnd_ai.api.access`,
`dnd_ai.domain.access`) every other command router uses.

Both routes run on the request's own `get_connection` transaction and call
the connection-taking `_..._impl` form of their command (never the public
engine-based wrapper, which would open a second, nested transaction) —
identical to every route in `dnd_ai.api.encounters`/`.items`/`.quests`/
`.relationships`.

Authorization: both routes require the `canon.edit` role capability in the
target campaign (`dnd_ai.api.access.require_campaign_capability`), the same
capability every other command router uses for this first cut.
Interactions and check resolutions are, in principle, more naturally
player-initiated than the GM/adapter-level actions every earlier workstream
scoped to `canon.edit` — extending to a narrower, character-scoped
capability (e.g. `character.control`) is future scope once a caller
actually needs it, not invented speculatively here, the same deliberate
scoping every other command router's own docstring records.

Cross-campaign session integrity: `perform_interaction_endpoint` passes the
URL's own (already-authorized) `campaign_id` and the request body's
caller-supplied `session_id` straight through to `_perform_interaction_impl`,
which validates the two agree
(`dnd_ai.commands._shared.validate_session_campaign`) before writing
anything, raising `SessionNotInCampaignError` — a `SafeMessageError` the
existing generic handler maps to a fixed, non-disclosing 404 — for a
nonexistent or foreign-campaign session.

Campaign ownership: unlike `dnd_ai.api.items`/`.quests`/`.relationships`,
`interaction.interactions` *does* carry its own `campaign_id` column, the
same as `narrative.encounters`. `resolve_check_endpoint` therefore passes
the URL's own `campaign_id` as `_resolve_check_impl`'s `expected_campaign_id`
argument, which resolves `check_request_id`'s parent interaction under a
row lock and asserts that interaction's own `campaign_id` matches before
anything is mutated (`dnd_ai.commands.interactions.
_lock_interaction_for_check_resolution`), raising `InteractionNotFoundError`
(a fixed, non-disclosing 404) for a nonexistent check request or one
belonging to a different campaign — the same "does this resource belong to
my campaign" ownership check `dnd_ai.api.encounters` established for
`narrative.encounters`, and closing the same class of gap workstream 6's
correction pass closed for items (a caller-supplied identifier the
database's own foreign keys can't scope to a campaign by themselves).
`perform_interaction_endpoint` has no analogous check to make: it creates
a new interaction rather than mutating an existing one, so there is
nothing pre-existing whose ownership could be spoofed.

Auditing: every successful call inserts one `audit.change_log` row
(`dnd_ai.api.audit.record_change_log`) identifying the authenticated
`actor_user_id`, the request's correlation ID, the command name, and the
resulting `event_id` — on the same connection, so it commits atomically
with the command it describes. Neither `interaction.interactions` nor
`interaction.check_results` is a `core.entities` row (unlike
`narrative.events` — see `dnd_ai.api.events`), so `entity_id` on both
routes is the acting character's own `actor_entity_id` — a real
`core.entities` row the change concerns, the same reasoning
`dnd_ai.commands.quests`' workstream 7 correction pass applied when
`quest_objective_id` itself turned out not to be an entity.

Idempotency: durable, PostgreSQL-backed, via `dnd_ai.api.idempotency` and
`security.idempotent_requests` (migration 082) — identical mechanism to
every other command router; see `dnd_ai.api.items`'s module docstring for
the full concurrency argument.

`resolve_check_endpoint` gained the hazard trigger/disarm, mechanism
activation, and discovery consequences `dnd_ai.commands.interactions.
_resolve_check_impl` added for docs/PLAN.md §25 steps 8-11 — see that
function's own docstring. `party_id` in the request body is trusted
directly rather than resolved through `dnd_ai.api.access.resolve_party_
perspective`, since this route already requires `canon.edit`
(GM/adapter-level), the same bypass every other GM-gated Phase 10 endpoint
gives a party-perspective check.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from dnd_ai.commands.interactions import (
    CheckRequestSpec,
    TargetSpec,
    _perform_interaction_impl,
    _resolve_check_impl,
)
from dnd_ai.domain.access import AccessContext

from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .idempotency import IdempotentReplay, begin_idempotent_request, complete_idempotent_request

router = APIRouter(tags=["interactions"])

# Interaction/check-resolution management is a canon-affecting mutation
# (docs/architecture/DATABASE_MODEL.md §12.3) — see this module's docstring
# for why every route here requires it rather than a narrower,
# character-scoped capability.
_INTERACTION_MANAGE_CAPABILITY = "canon.edit"

# audit.change_log.command_name / the idempotency store's fingerprinted
# command_name — one literal per route, never derived from request data.
_PERFORM_INTERACTION_COMMAND_NAME = "perform_interaction"
_RESOLVE_CHECK_COMMAND_NAME = "resolve_check"

# audit.change_actions.code (revision 007 seed): both routes always create
# new rows (an interaction/action/target/check_request tree, or a single
# check_results row) — there is no "insert vs. update" ambiguity the way a
# typed current-state table's own upsert has.
_CREATED_CHANGE_ACTION = "created"


# ---------------------------------------------------------------------------
# Request/response contracts
# ---------------------------------------------------------------------------


class TargetSpecRequest(BaseModel):
    target_entity_id: uuid.UUID | None = None
    target_area_connection_id: uuid.UUID | None = None
    target_area_feature_id: uuid.UUID | None = None
    target_area_hazard_id: uuid.UUID | None = None
    target_area_interactable_id: uuid.UUID | None = None
    target_component: str | None = None
    target_description: str | None = None


class CheckRequestSpecRequest(BaseModel):
    check_kind: str
    difficulty: int
    ability_id: uuid.UUID | None = None
    skill_id: uuid.UUID | None = None
    advantage_state: str = "normal"
    stakes: str | None = None
    target_index: int | None = None


class PerformInteractionRequest(BaseModel):
    world_time_id: uuid.UUID
    actor_entity_id: uuid.UUID
    interaction_type_code: str = "other"
    session_id: uuid.UUID | None = None
    action_description: str | None = None
    targets: list[TargetSpecRequest] = Field(default_factory=list)
    check_requests: list[CheckRequestSpecRequest] = Field(default_factory=list)


class PerformInteractionResponse(BaseModel):
    interaction_id: uuid.UUID
    action_id: uuid.UUID
    target_ids: list[uuid.UUID]
    check_request_ids: list[uuid.UUID]


class ResolveCheckRequest(BaseModel):
    degree_of_success: str
    roll: int | None = None
    total_modifier: int | None = None
    total: int | None = None
    is_visible_to_players: bool = True
    external_system_source: str | None = None
    event_details: str | None = None
    # Trusted directly, not resolved through dnd_ai.api.access.
    # resolve_party_perspective — this route requires canon.edit
    # (GM/adapter-level), which already bypasses a party-perspective check
    # everywhere else in Phase 10 (see dnd_ai.commands.interactions.
    # _resolve_check_impl's own docstring).
    party_id: uuid.UUID | None = None


class ResolveCheckResponse(BaseModel):
    check_result_id: uuid.UUID
    event_id: uuid.UUID | None
    area_connection_opened: bool
    hazard_status_code: str | None
    interactable_activated: bool
    discovery_event_id: uuid.UUID | None
    discovered_knowledge_item_id: uuid.UUID | None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/campaigns/{campaign_id}/interactions",
    response_model=PerformInteractionResponse,
    status_code=201,
)
def perform_interaction_endpoint(
    campaign_id: uuid.UUID,
    body: PerformInteractionRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_INTERACTION_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> PerformInteractionResponse:
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = body.model_dump(mode="json")
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_PERFORM_INTERACTION_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return PerformInteractionResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = _perform_interaction_impl(
        connection,
        timeline_id=access.timeline_id,
        world_time_id=body.world_time_id,
        actor_entity_id=body.actor_entity_id,
        interaction_type_code=body.interaction_type_code,
        campaign_id=campaign_id,
        session_id=body.session_id,
        action_description=body.action_description,
        targets=tuple(
            TargetSpec(
                target_entity_id=t.target_entity_id,
                target_area_connection_id=t.target_area_connection_id,
                target_area_feature_id=t.target_area_feature_id,
                target_area_hazard_id=t.target_area_hazard_id,
                target_area_interactable_id=t.target_area_interactable_id,
                target_component=t.target_component,
                target_description=t.target_description,
            )
            for t in body.targets
        ),
        check_requests=tuple(
            CheckRequestSpec(
                check_kind=c.check_kind,
                difficulty=c.difficulty,
                ability_id=c.ability_id,
                skill_id=c.skill_id,
                advantage_state=c.advantage_state,
                stakes=c.stakes,
                target_index=c.target_index,
            )
            for c in body.check_requests
        ),
    )

    record_change_log(
        connection,
        change_action_code=_CREATED_CHANGE_ACTION,
        schema_name="interaction",
        table_name="interactions",
        record_id=result.interaction_id,
        # interaction.interactions rows have no core.entities identity of
        # their own — this records the acting character's own entity_id
        # instead, the same "owning entity" indirection
        # dnd_ai.commands.quests' workstream 7 correction pass applied.
        entity_id=body.actor_entity_id,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_PERFORM_INTERACTION_COMMAND_NAME,
        event_id=None,
    )

    response = PerformInteractionResponse(
        interaction_id=result.interaction_id,
        action_id=result.action_id,
        target_ids=list(result.target_ids),
        check_request_ids=list(result.check_request_ids),
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
    "/campaigns/{campaign_id}/checks/{check_request_id}/resolve",
    response_model=ResolveCheckResponse,
    status_code=201,
)
def resolve_check_endpoint(
    campaign_id: uuid.UUID,
    check_request_id: uuid.UUID,
    body: ResolveCheckRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_INTERACTION_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> ResolveCheckResponse:
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "check_request_id": str(check_request_id),
            **body.model_dump(mode="json"),
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_RESOLVE_CHECK_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return ResolveCheckResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = _resolve_check_impl(
        connection,
        check_request_id=check_request_id,
        degree_of_success=body.degree_of_success,
        roll=body.roll,
        total_modifier=body.total_modifier,
        total=body.total,
        is_visible_to_players=body.is_visible_to_players,
        external_system_source=body.external_system_source,
        event_details=body.event_details,
        expected_campaign_id=campaign_id,
        party_id=body.party_id,
    )

    record_change_log(
        connection,
        change_action_code=_CREATED_CHANGE_ACTION,
        schema_name="interaction",
        table_name="check_results",
        record_id=result.check_result_id,
        # interaction.check_results rows have no core.entities identity of
        # their own — this records the checking character's own entity_id
        # instead, the same "owning entity" indirection used above.
        entity_id=result.actor_entity_id,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_RESOLVE_CHECK_COMMAND_NAME,
        # A discovery-only outcome (no primary connection/hazard/
        # interactable state change) still leaves result.event_id None —
        # audit.change_log.event_id falls back to the discovery event so
        # a real state change is never audited with no event reference at
        # all.
        event_id=result.event_id or result.discovery_event_id,
    )

    response = ResolveCheckResponse(
        check_result_id=result.check_result_id,
        event_id=result.event_id,
        area_connection_opened=result.area_connection_opened,
        hazard_status_code=result.hazard_status_code,
        interactable_activated=result.interactable_activated,
        discovery_event_id=result.discovery_event_id,
        discovered_knowledge_item_id=result.discovered_knowledge_item_id,
    )

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=201,
            response_body=response.model_dump(mode="json"),
        )

    return response
