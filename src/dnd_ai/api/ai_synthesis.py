"""Audience-aware campaign synthesis endpoint — GM briefs, player-character
question answers, and observer-safe summaries (docs/PLAN.md Phase 12).

Authorization is the mechanism that makes this route's exit criterion true
("the same question produces appropriately different GM, player-character,
and observer answers ... and inaccessible facts never enter the provider
request"): each `audience_tier` is gated by a *different* check, resolved
before `dnd_ai.domain.context_assembly.assemble_campaign_synthesis_context`
ever runs, so an unauthorized tier is rejected outright rather than
assembled-then-withheld.

- `gm_brief` requires `canon.edit` — the same GM-level capability every
  other draft-inclusive read in this codebase requires
  (`dnd_ai.queries.summary`'s own `include_draft_events` gate).
- `player_summary` requires `dnd_ai.api.access.resolve_party_perspective` to
  succeed for the caller's own named `requesting_character_id`/
  `requesting_party_id` — the identical proof-of-perspective check
  `dnd_ai.api.dungeon`/`.quests` already require before trusting a
  caller-supplied party id for anything.
- `observer_summary` requires only `campaign.view` (any campaign member) —
  and, structurally, never even reaches `resolve_party_perspective`: a
  `requesting_character_id`/`requesting_party_id` on an `observer_summary`
  request is accepted but never used (`dnd_ai.domain.context_assembly.
  assemble_campaign_synthesis_context`'s own docstring), so this route
  simply never resolves or authorizes one for that tier.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection, Engine

from dnd_ai.commands.ai_synthesis import request_campaign_synthesis
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.ai_provider import AiProvider
from dnd_ai.domain.context_assembly import GM_BRIEF, OBSERVER_SUMMARY, PLAYER_SUMMARY

from .access import require_campaign_capability, resolve_party_perspective
from .ai_npc import _resolve_provider
from .deps import get_connection, get_engine
from .errors import ApiError, ForbiddenError

router = APIRouter(tags=["ai-synthesis"])

# Any campaign member may ask; per-tier authorization is resolved inside the
# handler (see this module's own docstring) — canon.edit for gm_brief, an
# authorized perspective for player_summary, nothing further for
# observer_summary.
_BASELINE_CAPABILITY = "campaign.view"
_GM_BRIEF_CAPABILITY = "canon.edit"


class InvalidAudienceTierError(ApiError):
    status_code = 400
    error_code = "invalid_audience_tier"
    safe_message = "audience_tier must be one of gm_brief, player_summary, observer_summary."


class CampaignSynthesisRequest(BaseModel):
    agent_assignment_id: uuid.UUID
    audience_tier: str
    question_text: str
    requesting_character_id: uuid.UUID | None = None
    requesting_party_id: uuid.UUID | None = None


class CampaignSynthesisResponse(BaseModel):
    context_request_id: uuid.UUID
    generated_output_id: uuid.UUID
    answer: str | None
    error_message: str | None


@router.post(
    "/campaigns/{campaign_id}/ai/synthesis",
    response_model=CampaignSynthesisResponse,
    status_code=200,
)
def request_campaign_synthesis_endpoint(
    campaign_id: uuid.UUID,
    body: CampaignSynthesisRequest,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_BASELINE_CAPABILITY))],
    connection: Annotated[Connection, Depends(get_connection)],
    engine: Annotated[Engine, Depends(get_engine)],
    provider: Annotated[AiProvider, Depends(_resolve_provider)],
) -> CampaignSynthesisResponse:
    if body.audience_tier not in (GM_BRIEF, PLAYER_SUMMARY, OBSERVER_SUMMARY):
        raise InvalidAudienceTierError()

    authorized_character_id: uuid.UUID | None = None
    authorized_party_id: uuid.UUID | None = None

    if body.audience_tier == GM_BRIEF:
        if not access.has_capability(_GM_BRIEF_CAPABILITY):
            raise ForbiddenError()
    elif body.audience_tier == PLAYER_SUMMARY:
        authorized_party_id = resolve_party_perspective(
            connection,
            access=access,
            campaign_id=campaign_id,
            character_id=body.requesting_character_id,
            party_id=body.requesting_party_id,
        )
        authorized_character_id = body.requesting_character_id
        if authorized_party_id is None:
            raise ForbiddenError()
    # observer_summary: baseline campaign.view already checked; no further
    # authorization, and the request's own character_id/party_id are never
    # forwarded — see this module's own docstring.

    result = request_campaign_synthesis(
        engine,
        agent_assignment_id=body.agent_assignment_id,
        campaign_id=campaign_id,
        audience_tier=body.audience_tier,
        requesting_user_id=access.user_id,
        question_text=body.question_text,
        provider=provider,
        timeline_id=access.timeline_id,
        requesting_character_id=authorized_character_id,
        requesting_party_id=authorized_party_id,
    )
    return CampaignSynthesisResponse(
        context_request_id=result.context_request_id,
        generated_output_id=result.generated_output_id,
        answer=result.answer,
        error_message=result.error_message,
    )
