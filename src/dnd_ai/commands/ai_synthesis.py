"""RequestCampaignSynthesis — the audience-aware GM-brief/player-summary/
observer-summary use case (docs/PLAN.md Phase 12: "audience-aware on-demand
synthesis over the deterministic summary/detail query services").

Same three-transaction shape as `dnd_ai.commands.ai_npc.request_npc_
conversation_turn` — see that module's own docstring for why a network call
never happens while a transaction is open. Purely informational: unlike
`reveal_knowledge`, a synthesis answer never proposes a canonical mutation,
so this module writes only `ai.context_requests`/`.context_snapshots`/
`.generated_outputs` — no `ai.proposed_changes` row, ever.

Authorization for *which* audience tier a caller may request is entirely
`dnd_ai.api.ai_synthesis`'s job (canon.edit for `gm_brief`, an authorized
character/party perspective for `player_summary`, `campaign.view` alone for
`observer_summary`) — this module trusts `audience_tier` and
`requesting_party_id` exactly as every other command trusts its own
already-authorized arguments. The one thing this module does enforce
itself, structurally: `dnd_ai.domain.context_assembly.assemble_campaign_
synthesis_context` only ever consults `requesting_party_id` for
`PLAYER_SUMMARY` — see that function's own docstring.
"""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from dnd_ai.domain.ai_provider import AiProvider
from dnd_ai.domain.context_assembly import (
    CampaignSynthesisContext,
    assemble_campaign_synthesis_context,
)
from dnd_ai.domain.errors import DomainAuthorizationError


class SynthesisAgentAssignmentNotFoundError(DomainAuthorizationError):
    """Raised for an `agent_assignment_id` that does not resolve to a
    currently-active `ai.agent_assignments` row belonging to `campaign_id`."""


@dataclass(frozen=True)
class CampaignSynthesisResult:
    context_request_id: uuid.UUID
    generated_output_id: uuid.UUID
    answer: str | None
    error_message: str | None


def _lock_campaign_agent_assignment(
    connection: Connection, *, agent_assignment_id: uuid.UUID, campaign_id: uuid.UUID
) -> None:
    row = connection.execute(
        text("""
            SELECT 1 FROM ai.agent_assignments
            WHERE agent_assignment_id = :id AND campaign_id = :campaign AND ended_at IS NULL
        """),
        {"id": agent_assignment_id, "campaign": campaign_id},
    ).scalar()
    if row is None:
        raise SynthesisAgentAssignmentNotFoundError(
            f"agent assignment {agent_assignment_id} not found for campaign {campaign_id}"
        )


def _record_synthesis_request(
    connection: Connection,
    *,
    agent_assignment_id: uuid.UUID,
    requesting_user_id: uuid.UUID | None,
    requesting_character_id: uuid.UUID | None,
    audience_tier: str,
    question_text: str,
    campaign_id: uuid.UUID,
    timeline_id: uuid.UUID | None,
    requesting_party_id: uuid.UUID | None,
) -> tuple[uuid.UUID, CampaignSynthesisContext]:
    context = assemble_campaign_synthesis_context(
        connection,
        campaign_id=campaign_id,
        audience_tier=audience_tier,
        timeline_id=timeline_id,
        requesting_party_id=requesting_party_id,
    )

    context_request_id = connection.execute(
        text("""
            INSERT INTO ai.context_requests
                (agent_assignment_id, requesting_user_id, requesting_character_id, request_kind,
                 input_text)
            VALUES (:assignment, :user, :character, :kind, :input_text)
            RETURNING context_request_id
        """),
        {
            "assignment": agent_assignment_id,
            "user": requesting_user_id,
            "character": requesting_character_id,
            "kind": audience_tier,
            "input_text": question_text,
        },
    ).scalar()
    assert isinstance(context_request_id, uuid.UUID)

    connection.execute(
        text("""
            INSERT INTO ai.context_snapshots (context_request_id, assembled_context)
            VALUES (:request, :context)
        """),
        {"request": context_request_id, "context": json.dumps(context.as_prompt_payload())},
    )
    return context_request_id, context


def request_campaign_synthesis(
    engine: Engine,
    *,
    agent_assignment_id: uuid.UUID,
    campaign_id: uuid.UUID,
    audience_tier: str,
    requesting_user_id: uuid.UUID | None,
    question_text: str,
    provider: AiProvider,
    timeline_id: uuid.UUID | None = None,
    requesting_character_id: uuid.UUID | None = None,
    requesting_party_id: uuid.UUID | None = None,
) -> CampaignSynthesisResult:
    with engine.begin() as connection:
        _lock_campaign_agent_assignment(
            connection, agent_assignment_id=agent_assignment_id, campaign_id=campaign_id
        )
        context_request_id, context = _record_synthesis_request(
            connection,
            agent_assignment_id=agent_assignment_id,
            requesting_user_id=requesting_user_id,
            requesting_character_id=requesting_character_id,
            audience_tier=audience_tier,
            question_text=question_text,
            campaign_id=campaign_id,
            timeline_id=timeline_id,
            requesting_party_id=requesting_party_id,
        )

    provider_result = provider.generate_synthesis(
        context=context.as_prompt_payload(),
        audience_tier=audience_tier,
        question_text=question_text,
    )

    with engine.begin() as connection:
        agent_row = connection.execute(
            text("""
                SELECT a.provider, a.model_identifier
                FROM ai.agents a
                JOIN ai.agent_assignments aa ON aa.agent_id = a.agent_id
                WHERE aa.agent_assignment_id = :assignment
            """),
            {"assignment": agent_assignment_id},
        ).one()

        generated_output_id = connection.execute(
            text("""
                INSERT INTO ai.generated_outputs
                    (context_request_id, provider, model_identifier, raw_response,
                     structured_output, finish_reason, latency_ms, error_message)
                VALUES (:request, :provider, :model, :raw, :structured, :finish_reason, :latency,
                        :error)
                RETURNING generated_output_id
            """),
            {
                "request": context_request_id,
                "provider": agent_row.provider,
                "model": agent_row.model_identifier,
                "raw": provider_result.raw_response,
                "structured": (
                    json.dumps(provider_result.structured_output.model_dump(mode="json"))
                    if provider_result.structured_output is not None
                    else None
                ),
                "finish_reason": provider_result.finish_reason,
                "latency": provider_result.latency_ms,
                "error": provider_result.error_message,
            },
        ).scalar()
        assert isinstance(generated_output_id, uuid.UUID)

        return CampaignSynthesisResult(
            context_request_id=context_request_id,
            generated_output_id=generated_output_id,
            answer=(
                provider_result.structured_output.answer
                if provider_result.structured_output is not None
                else None
            ),
            error_message=provider_result.error_message,
        )
