"""RequestNpcConversationTurn — Phase 12's one NPC-portrayal use case
(docs/PLAN.md Phase 12).

Deliberately three separate transactions, the same shape
`dnd_ai.commands.integration.apply_foundry_combat_sync` already established
for "don't hold a lock, or even a transaction, across an external network
call": (1) resolve the agent assignment and assemble+record context, (2) —
no open transaction — call the AI provider, (3) record the response and, if
the model proposed revealing a fact, create the proposal and, for an
`auto_approve` risk tier, apply it immediately. A provider failure between
(1) and (3) leaves a `context_requests`/`context_snapshots` pair with no
`generated_outputs` row — a legitimate, auditable "the request was made but
never got a response" state, not a partial write of anything canonical.

`reveal_knowledge_item_id` from the model is validated against the
context's own `revealable_knowledge` set before anything is proposed — see
`dnd_ai.domain.context_assembly`'s own docstring for why that closed,
pre-computed candidate set is what keeps this safe even when a proposal is
auto-approved: the model can select from real, already-authored,
already-authorized items, never name one that doesn't exist or that this
party isn't entitled to have proposed to it.
"""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from dnd_ai.domain.ai_policy import RISK_TIER_AUTO_APPROVE, classify_reveal_knowledge_risk
from dnd_ai.domain.ai_provider import AiProvider, NpcTurnOutput
from dnd_ai.domain.context_assembly import NpcConversationContext, assemble_npc_conversation_context
from dnd_ai.domain.errors import DomainAuthorizationError

from .ai_proposals import _apply_proposal


class AgentAssignmentNotFoundError(DomainAuthorizationError):
    """Raised for an `agent_assignment_id` that does not resolve to a
    currently-active `ai.agent_assignments` row. Fixed, non-disclosing
    404, matching every other resource-scoped lookup in this codebase."""


@dataclass(frozen=True)
class NpcConversationTurnResult:
    context_request_id: uuid.UUID
    generated_output_id: uuid.UUID
    dialogue: str | None
    ai_proposed_change_id: uuid.UUID | None
    proposal_status: str | None
    applied_event_id: uuid.UUID | None
    error_message: str | None


@dataclass(frozen=True)
class _AssignmentContext:
    agent_id: uuid.UUID
    campaign_id: uuid.UUID
    npc_entity_id: uuid.UUID


def _lock_active_assignment(
    connection: Connection, agent_assignment_id: uuid.UUID
) -> _AssignmentContext:
    row = connection.execute(
        text("""
            SELECT agent_id, campaign_id, entity_id
            FROM ai.agent_assignments
            WHERE agent_assignment_id = :id AND ended_at IS NULL
        """),
        {"id": agent_assignment_id},
    ).one_or_none()
    if row is None:
        raise AgentAssignmentNotFoundError(
            f"agent assignment {agent_assignment_id} not found or no longer active"
        )
    return _AssignmentContext(
        agent_id=row.agent_id, campaign_id=row.campaign_id, npc_entity_id=row.entity_id
    )


def _record_request_and_context(
    connection: Connection,
    *,
    agent_assignment_id: uuid.UUID,
    assignment: _AssignmentContext,
    requesting_user_id: uuid.UUID | None,
    requesting_character_id: uuid.UUID,
    requesting_party_id: uuid.UUID,
    player_message: str,
    timeline_id: uuid.UUID,
    expected_world_id: uuid.UUID,
) -> tuple[uuid.UUID, NpcConversationContext]:
    context = assemble_npc_conversation_context(
        connection,
        npc_entity_id=assignment.npc_entity_id,
        timeline_id=timeline_id,
        expected_world_id=expected_world_id,
        requesting_character_id=requesting_character_id,
        requesting_party_id=requesting_party_id,
    )

    context_request_id = connection.execute(
        text("""
            INSERT INTO ai.context_requests
                (agent_assignment_id, requesting_user_id, requesting_character_id, request_kind,
                 input_text)
            VALUES (:assignment, :user, :character, 'npc_conversation', :input_text)
            RETURNING context_request_id
        """),
        {
            "assignment": agent_assignment_id,
            "user": requesting_user_id,
            "character": requesting_character_id,
            "input_text": player_message,
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


def _validated_reveal_target(
    context: NpcConversationContext, structured_output: NpcTurnOutput | None
) -> tuple[uuid.UUID, str] | None:
    """The (`knowledge_item_id`, `sensitivity`) pair the model proposed
    revealing, only if it is actually a member of `context.
    revealable_knowledge` — never trusts the model's own id in isolation.
    Returns `None` for no proposal or an invalid/unlisted one (silently
    ignored, not an error: a model naming something outside the candidate
    set is a provider-quality problem, not a request the caller made)."""
    if structured_output is None or structured_output.reveal_knowledge_item_id is None:
        return None
    for candidate in context.revealable_knowledge:
        if candidate.knowledge_item_id == structured_output.reveal_knowledge_item_id:
            return candidate.knowledge_item_id, candidate.sensitivity
    return None


def request_npc_conversation_turn(
    engine: Engine,
    *,
    agent_assignment_id: uuid.UUID,
    requesting_user_id: uuid.UUID | None,
    requesting_character_id: uuid.UUID,
    requesting_party_id: uuid.UUID,
    player_message: str,
    provider: AiProvider,
    timeline_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    world_time_id: uuid.UUID,
) -> NpcConversationTurnResult:
    with engine.begin() as connection:
        assignment = _lock_active_assignment(connection, agent_assignment_id)
        context_request_id, context = _record_request_and_context(
            connection,
            agent_assignment_id=agent_assignment_id,
            assignment=assignment,
            requesting_user_id=requesting_user_id,
            requesting_character_id=requesting_character_id,
            requesting_party_id=requesting_party_id,
            player_message=player_message,
            timeline_id=timeline_id,
            expected_world_id=expected_world_id,
        )

    provider_result = provider.generate_npc_turn(context=context, player_message=player_message)

    with engine.begin() as connection:
        agent_row = connection.execute(
            text("SELECT provider, model_identifier FROM ai.agents WHERE agent_id = :id"),
            {"id": assignment.agent_id},
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

        reveal_target = _validated_reveal_target(context, provider_result.structured_output)
        ai_proposed_change_id: uuid.UUID | None = None
        proposal_status: str | None = None
        applied_event_id: uuid.UUID | None = None

        if reveal_target is not None:
            knowledge_item_id, sensitivity = reveal_target
            risk_tier = classify_reveal_knowledge_risk(sensitivity=sensitivity)
            proposed_arguments = {
                "knowledge_item_id": str(knowledge_item_id),
                "party_id": str(requesting_party_id),
                "timeline_id": str(timeline_id),
                "world_time_id": str(world_time_id),
            }
            ai_proposed_change_id = connection.execute(
                text("""
                    INSERT INTO ai.proposed_changes
                        (generated_output_id, campaign_id, proposal_kind, proposed_arguments,
                         risk_tier)
                    VALUES (:output, :campaign, 'reveal_knowledge', :arguments, :risk_tier)
                    RETURNING ai_proposed_change_id
                """),
                {
                    "output": generated_output_id,
                    "campaign": assignment.campaign_id,
                    "arguments": json.dumps(proposed_arguments),
                    "risk_tier": risk_tier,
                },
            ).scalar()
            assert isinstance(ai_proposed_change_id, uuid.UUID)
            proposal_status = "pending"

            if risk_tier == RISK_TIER_AUTO_APPROVE:
                applied_event_id = _apply_proposal(
                    connection,
                    ai_proposed_change_id=ai_proposed_change_id,
                    proposal_kind="reveal_knowledge",
                    proposed_arguments=proposed_arguments,
                    campaign_id=assignment.campaign_id,
                )
                connection.execute(
                    text("""
                        UPDATE ai.proposed_changes
                        SET status = 'applied', decided_at = now(), applied_event_id = :event
                        WHERE ai_proposed_change_id = :id
                    """),
                    {"event": applied_event_id, "id": ai_proposed_change_id},
                )
                proposal_status = "applied"

        return NpcConversationTurnResult(
            context_request_id=context_request_id,
            generated_output_id=generated_output_id,
            dialogue=(
                provider_result.structured_output.dialogue
                if provider_result.structured_output is not None
                else None
            ),
            ai_proposed_change_id=ai_proposed_change_id,
            proposal_status=proposal_status,
            applied_event_id=applied_event_id,
            error_message=provider_result.error_message,
        )
