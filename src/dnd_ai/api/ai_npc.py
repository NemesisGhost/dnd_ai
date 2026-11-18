"""NPC-conversation and proposal-review endpoints — Phase 12's one NPC-
portrayal use case (docs/PLAN.md).

`request_npc_conversation_turn_endpoint` is authorized on `character.
interact` — an existing seeded capability (`database/seeds/security.
capabilities.yaml`) with no route using it until this module;
`dnd_ai.api.interactions`/`.movement` instead treat their own actions as
GM/adapter-level canon mutation and require `canon.edit`, but an NPC
conversation is squarely a *player*-facing action through their own
character, which `character.interact` — shared vocabulary between
`security.role_capabilities` and `security.character_relationship_type_
capabilities` — names for exactly this purpose. The caller must
additionally hold that capability *for the specific `requesting_
character_id`* they name (`AccessContext.has_capability(...,
character_id=...)`), never a bare campaign-wide grant — the same
resource-scoped check `dnd_ai.api.access.resolve_party_perspective` already
requires for exactly the same reason: a same-campaign member naming any
other member's character would otherwise be able to speak, and receive
audience-filtered knowledge, through it.

`review_proposed_change_endpoint` is authorized on `canon.edit` — reviewing
a proposal is a GM-level canon decision, the same posture every other
canon-mutating route in this codebase already takes.

The AI provider itself is resolved once per process
(`dnd_ai.config.settings`-driven, `_resolve_provider()` below) — real
(`OpenAiCompatibleProvider`, targeting real hosted OpenAI by default or a
locally hosted, OpenAI-API-compatible model server when `DND_AI_AI_
PROVIDER_BASE_URL` points elsewhere — see that class's own docstring)
whenever configuration for the resolved endpoint is present, otherwise
unavailable (503) rather than silently falling back to a fake provider in
production. Tests override this via `app.dependency_overrides` (the same
mechanism `dnd_ai.api.deps.get_engine` already uses), never a
monkeypatched module global.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import Connection, Engine

from dnd_ai.commands.ai_npc import request_npc_conversation_turn
from dnd_ai.commands.ai_perspective import (
    PERSPECTIVE_CAPABILITY,
    PartyPerspectiveRefusedError,
    RequirementFactory,
    party_perspective_requirement,
    perspective_facts_or_refuse,
)
from dnd_ai.commands.ai_proposals import review_proposed_change
from dnd_ai.config import settings
from dnd_ai.domain.access import AccessContext, AuthoritySnapshot
from dnd_ai.domain.ai_provider import AiProvider, OpenAiCompatibleProvider
from dnd_ai.domain.authorization import AuthorizationPlan, Requirement
from dnd_ai.domain.authorization_requirements import judged_requirement

from .access import (
    active_account_requirement,
    require_campaign_capability,
    route_capability_requirement,
)
from .deps import end_request_transaction, get_connection, get_engine
from .errors import ApiError, ForbiddenError
from .r01_route_plans import get_authorization_plan

router = APIRouter(tags=["ai-npc"])

_INTERACT_CAPABILITY = "character.interact"
_REVIEW_CAPABILITY = "canon.edit"

# Mirrors dnd_ai.config._DEFAULT_OPENAI_BASE_URL — duplicated (not
# imported) for the same "no dnd_ai.api dependency on dnd_ai.config
# internals" reason that module doesn't import from dnd_ai.domain either.
_DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


class AiProviderUnavailableError(ApiError):
    """No AI provider is configured — HTTP 503, distinct from every other
    error contract in this module: the request itself may well be valid,
    but this deployment cannot currently serve it. Only raised when the
    resolved endpoint is still the real, hosted OpenAI default and no API
    key is configured; a `DND_AI_AI_PROVIDER_BASE_URL` pointed at a
    locally hosted model server is always considered available — that
    server's own reachability/access control is the operator's concern,
    not this module's to pre-validate."""

    status_code = 503
    error_code = "ai_provider_unavailable"
    safe_message = "No AI provider is currently configured."


def _resolve_provider() -> AiProvider:
    if (
        settings.ai_provider_base_url == _DEFAULT_OPENAI_BASE_URL
        and settings.ai_provider_api_key is None
    ):
        raise AiProviderUnavailableError()
    return OpenAiCompatibleProvider(
        api_key=settings.ai_provider_api_key,
        model_identifier=settings.ai_provider_model,
        base_url=settings.ai_provider_base_url,
    )


def npc_turn_requirements(
    *, actor_user_id: uuid.UUID, character_id: uuid.UUID
) -> RequirementFactory:
    """The NPC turn's authority requirements, as a factory (R01 E2, design 5.1): each call returns **fresh**
    `Requirement` objects, so the request transaction, T1 and T2 each judge their own (no verdict and no
    `AccessContext` boolean crosses a transaction). They refuse exactly as the early checks do: the route's
    404 / 403, then the targeted `character.interact` 403. The party perspective (requirement 3) is built by
    the command from facts it reads in the transaction that judges it."""

    def factory() -> list[Requirement]:
        def decide_interact(snapshot: AuthoritySnapshot) -> BaseException | None:
            access = snapshot.access
            if access is None or not access.has_capability(
                _INTERACT_CAPABILITY, character_id=character_id
            ):
                return ForbiddenError()
            return None

        return [
            route_capability_requirement(
                capability_code=_INTERACT_CAPABILITY,
                allow_archived_campaign=False,
                world_capability=None,
                world_id=None,
                actor_user_id=actor_user_id,
            ),
            judged_requirement("npc_turn.character.interact", decide_interact),
            # R01 F-4: the account must be active at each transaction's final check. After the route and
            # character requirements so their refusals keep precedence.
            active_account_requirement(),
        ]

    return factory


class NpcConversationTurnRequest(BaseModel):
    agent_assignment_id: uuid.UUID
    requesting_character_id: uuid.UUID
    requesting_party_id: uuid.UUID
    player_message: str
    world_time_id: uuid.UUID


class NpcConversationTurnResponse(BaseModel):
    context_request_id: uuid.UUID
    generated_output_id: uuid.UUID
    dialogue: str | None
    ai_proposed_change_id: uuid.UUID | None
    proposal_status: str | None
    error_message: str | None


class ReviewProposedChangeRequest(BaseModel):
    decision: str
    comments: str | None = None


class ReviewProposedChangeResponse(BaseModel):
    ai_change_review_id: uuid.UUID
    status: str
    applied_event_id: uuid.UUID | None


@router.post(
    "/campaigns/{campaign_id}/ai/npc-conversation",
    response_model=NpcConversationTurnResponse,
    status_code=200,
)
def request_npc_conversation_turn_endpoint(
    request: Request,
    campaign_id: uuid.UUID,
    body: NpcConversationTurnRequest,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_INTERACT_CAPABILITY))],
    plan: Annotated[AuthorizationPlan, Depends(get_authorization_plan)],
    connection: Annotated[Connection, Depends(get_connection)],
    engine: Annotated[Engine, Depends(get_engine)],
    provider: Annotated[AiProvider, Depends(_resolve_provider)],
) -> NpcConversationTurnResponse:
    # R01 E2: the request transaction is the early check, now finalized before it ends. The command then
    # judges its own two engine transactions (T1 before the provider is called, T2 before anything is kept).
    requirements = npc_turn_requirements(
        actor_user_id=access.user_id, character_id=body.requesting_character_id
    )
    if not access.has_capability(_INTERACT_CAPABILITY, character_id=body.requesting_character_id):
        raise ForbiddenError()
    # Decision G-2: every caller, `canon.edit` included, proves the established party perspective
    # (`character.view_knowledge` for the character, the party in this campaign, the character a current
    # member at the campaign clock). One non-disclosing 404.
    if not access.has_capability(PERSPECTIVE_CAPABILITY, character_id=body.requesting_character_id):
        raise PartyPerspectiveRefusedError("party perspective not authorized")
    perspective_facts_or_refuse(
        connection,
        campaign_id=campaign_id,
        timeline_id=access.timeline_id,
        character_id=body.requesting_character_id,
        party_id=body.requesting_party_id,
    )
    for requirement in requirements():
        if requirement.name.startswith("route."):
            continue  # the dependency registered the route requirement on this plan already
        plan.require(connection, requirement)
    plan.require(
        connection,
        party_perspective_requirement(
            name="npc_turn.party_perspective",
            character_id=body.requesting_character_id,
            party_id=body.requesting_party_id,
        ),
    )
    plan.finalize(connection)
    # Authorization is decided; end the request transaction before any engine-side effect.
    end_request_transaction(request)

    result = request_npc_conversation_turn(
        engine,
        agent_assignment_id=body.agent_assignment_id,
        campaign_id=campaign_id,
        requesting_user_id=access.user_id,
        requesting_character_id=body.requesting_character_id,
        requesting_party_id=body.requesting_party_id,
        player_message=body.player_message,
        provider=provider,
        timeline_id=access.timeline_id,
        world_time_id=body.world_time_id,
        requirements=requirements,
    )
    return NpcConversationTurnResponse(
        context_request_id=result.context_request_id,
        generated_output_id=result.generated_output_id,
        dialogue=result.dialogue,
        ai_proposed_change_id=result.ai_proposed_change_id,
        proposal_status=result.proposal_status,
        error_message=result.error_message,
    )


@router.post(
    "/campaigns/{campaign_id}/ai/proposed-changes/{ai_proposed_change_id}/review",
    response_model=ReviewProposedChangeResponse,
    status_code=200,
)
def review_proposed_change_endpoint(
    campaign_id: uuid.UUID,
    ai_proposed_change_id: uuid.UUID,
    body: ReviewProposedChangeRequest,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_REVIEW_CAPABILITY))],
    plan: Annotated[AuthorizationPlan, Depends(get_authorization_plan)],
    connection: Annotated[Connection, Depends(get_connection)],
) -> ReviewProposedChangeResponse:
    # R01 E1: the review and everything it applies run in the request-owned transaction, under the
    # actor's scope locks, and the final authorization decision is the last statement (post-write).
    result = review_proposed_change(
        connection,
        plan=plan,
        ai_proposed_change_id=ai_proposed_change_id,
        campaign_id=campaign_id,
        reviewer_user_id=access.user_id,
        decision=body.decision,
        comments=body.comments,
    )
    plan.finalize(connection)
    return ReviewProposedChangeResponse(
        ai_change_review_id=result.ai_change_review_id,
        status=result.status,
        applied_event_id=result.applied_event_id,
    )
