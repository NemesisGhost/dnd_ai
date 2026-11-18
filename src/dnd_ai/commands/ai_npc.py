"""RequestNpcConversationTurn — Phase 12's NPC-portrayal use case
(docs/PLAN.md Phase 12), producing at most one of two proposal kinds per
turn: `reveal_knowledge` or `advance_quest_objective`.

Deliberately three separate transactions, the same shape
`dnd_ai.commands.integration.apply_foundry_combat_sync` already established
for "don't hold a lock, or even a transaction, across an external network
call": (1) resolve the agent assignment and assemble+record context, (2) —
no open transaction — call the AI provider, (3) record the response and, if
the model proposed a canonical change, create the proposal and, for an
`auto_approve` risk tier, apply it immediately (`advance_quest_objective` is
always `requires_approval` — see `dnd_ai.domain.ai_policy.classify_advance_
quest_objective_risk` — so only `reveal_knowledge` can ever reach this
phase's auto-approve path). A provider failure between (1) and (3) leaves a
`context_requests`/`context_snapshots` pair with no `generated_outputs`
row — a legitimate, auditable "the request was made but never got a
response" state, not a partial write of anything canonical.

`reveal_knowledge_item_id`/`advance_quest_objective_id` from the model are
each validated against the context's own `revealable_knowledge`/
`advanceable_objectives` set before anything is proposed — see `dnd_ai.
domain.context_assembly`'s own docstring for why those closed, pre-computed
candidate sets are what keeps this safe even when a proposal is
auto-approved: the model can select from real, already-authored,
already-authorized items, never name one that doesn't exist or that this
party isn't entitled to have proposed to it. `NpcTurnOutput`'s own schema
validation additionally guarantees the two kinds are never both present at
once (`dnd_ai.domain.ai_provider`'s own docstring), so at most one of
`_validated_reveal_target`/`_validated_advance_target` below is ever
non-`None` for a given turn.

Applying an `advance_quest_objective` proposal dispatches to `dnd_ai.
commands.quests._advance_objective_impl` — the same canonical command a
human-driven quest advancement already uses (docs/ENTITY_LIFECYCLE.md §10's
"applying a proposal uses the same domain command path as human-authored
changes" rule) — via `dnd_ai.commands.ai_proposals._apply_proposal`'s
explicit, closed dispatch table; see that module's own docstring.
"""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from dnd_ai.domain.ai_policy import (
    RISK_TIER_AUTO_APPROVE,
    classify_advance_quest_objective_risk,
    classify_reveal_knowledge_risk,
)
from dnd_ai.domain.ai_provider import AiProvider, NpcTurnOutput
from dnd_ai.domain.context_assembly import NpcConversationContext, assemble_npc_conversation_context
from dnd_ai.domain.errors import DomainAuthorizationError

from ._shared import lifecycle_code, require_state_targetable
from .ai_perspective import (
    RequirementFactory,
    perspective_facts_or_refuse,
    register_perspective,
    register_requirements,
)
from .ai_proposals import _apply_proposal
from .authorized_transaction import authorized_transaction


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
    connection: Connection, agent_assignment_id: uuid.UUID, campaign_id: uuid.UUID
) -> _AssignmentContext:
    """The active assignment, bound to the path campaign (R01 E2, D-1): an assignment of another campaign is
    the same 404 as an unknown one."""
    row = connection.execute(
        text("""
            SELECT agent_id, campaign_id, entity_id
            FROM ai.agent_assignments
            WHERE agent_assignment_id = :id AND campaign_id = :campaign AND ended_at IS NULL
        """),
        {"id": agent_assignment_id, "campaign": campaign_id},
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
    require_state_targetable(connection, assignment.npc_entity_id)
    context = assemble_npc_conversation_context(
        connection,
        npc_entity_id=assignment.npc_entity_id,
        campaign_id=assignment.campaign_id,
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


def _validated_advance_target(
    context: NpcConversationContext, structured_output: NpcTurnOutput | None
) -> tuple[uuid.UUID, uuid.UUID, str] | None:
    """The (`quest_objective_id`, `quest_id`, `new_status_code`) triple the
    model proposed advancing, only if `quest_objective_id` is actually a
    member of `context.advanceable_objectives` — the same never-trust-the-
    model's-own-id posture `_validated_reveal_target` already applies.
    `new_status_code` itself was already constrained to `'completed'`/
    `'failed'` by `NpcTurnOutput`'s own `Literal` field (a provider response
    naming anything else fails schema validation before this ever runs), so
    only candidate-set membership needs checking here. Returns `None` for
    no proposal or an invalid/unlisted one (silently ignored, not an error —
    same reasoning as `_validated_reveal_target`)."""
    if structured_output is None or structured_output.advance_quest_objective_id is None:
        return None
    assert structured_output.advance_quest_objective_new_status is not None
    for candidate in context.advanceable_objectives:
        if candidate.quest_objective_id == structured_output.advance_quest_objective_id:
            return (
                candidate.quest_objective_id,
                candidate.quest_id,
                structured_output.advance_quest_objective_new_status,
            )
    return None


@dataclass(frozen=True)
class _FreshRevealItem:
    """The reveal candidate as read under lock in T2 (R01 E2, N3 to N5): the values the proposal's tier and
    qualification are decided from, never T1's."""

    sensitivity: str
    qualifies: bool


def _lock_and_read_reveal_candidate(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    knowledge_item_id: uuid.UUID,
    npc_entity_id: uuid.UUID,
    expected_world_id: uuid.UUID,
) -> _FreshRevealItem | None:
    """T2's fresh read of the reveal candidate, in the order the design fixes (6.2):

    N3 the campaign `FOR KEY SHARE`, before any entity lock (so a grant, which takes the campaign `FOR UPDATE`
    and then the entity, and this turn cannot wait for each other: E1's P-2 shape stays absent);
    N4 the item's entity row `FOR SHARE`, a lock only (the human reveal's and the definition edit's order, so
    the edit and this turn meet at the entity row: P-3 is removed for this path);
    N5 `knowledge_items FOR UPDATE`, with the fresh sensitivity and subject.

    Returns `None` when the item no longer exists. A candidate that stopped qualifying (another world, not
    published, not active, another subject) comes back with `qualifies=False`: no proposal, not an error."""
    connection.execute(
        text("SELECT 1 FROM campaign.campaigns WHERE campaign_id = :c FOR KEY SHARE"),
        {"c": campaign_id},
    ).scalar()
    entity = connection.execute(
        text("""
            SELECT e.world_id, e.canon_status_id, e.lifecycle_status_id
            FROM core.entities e
            WHERE e.entity_id = :item
            FOR SHARE OF e
        """),
        {"item": knowledge_item_id},
    ).one_or_none()
    item = connection.execute(
        text("""
            SELECT ki.sensitivity, ki.subject_entity_id
            FROM knowledge.knowledge_items ki
            WHERE ki.knowledge_item_id = :item
            FOR UPDATE OF ki
        """),
        {"item": knowledge_item_id},
    ).one_or_none()
    if entity is None or item is None:
        return None
    canon_code = connection.execute(
        text("SELECT code FROM core.canon_statuses WHERE canon_status_id = :s"),
        {"s": entity.canon_status_id},
    ).scalar()
    qualifies = (
        entity.world_id == expected_world_id
        and canon_code == "canon"
        and lifecycle_code(connection, entity.lifecycle_status_id) == "active"
        and item.subject_entity_id == npc_entity_id
    )
    return _FreshRevealItem(sensitivity=item.sensitivity, qualifies=qualifies)


def _timeline_world(connection: Connection, timeline_id: uuid.UUID) -> uuid.UUID:
    value = connection.execute(
        text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :t"), {"t": timeline_id}
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def request_npc_conversation_turn(
    engine: Engine,
    *,
    agent_assignment_id: uuid.UUID,
    campaign_id: uuid.UUID,
    requesting_user_id: uuid.UUID,
    requesting_character_id: uuid.UUID,
    requesting_party_id: uuid.UUID,
    player_message: str,
    provider: AiProvider,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    requirements: RequirementFactory,
    expected_world_id: uuid.UUID | None = None,
) -> NpcConversationTurnResult:
    """Two engine transactions around the provider call (R01 E2). Each is an `authorized_transaction` with its
    own plan: `requirements()` is called once per transaction, and the party perspective is read and judged
    inside it. T1 commits before the provider is called (the disclosure is decided at T1's final check); T2
    persists, and applies, only if its own final check passes. No transaction or lock spans the provider call."""
    with authorized_transaction(engine, requesting_user_id, campaign_id) as (connection, plan):
        register_requirements(connection, plan, requirements)
        register_perspective(
            connection,
            plan,
            name="npc_turn.party_perspective",
            character_id=requesting_character_id,
            party_id=requesting_party_id,
        )
        world_id = expected_world_id or _timeline_world(connection, timeline_id)
        assignment = _lock_active_assignment(connection, agent_assignment_id, campaign_id)
        perspective_facts_or_refuse(
            connection,
            campaign_id=campaign_id,
            timeline_id=timeline_id,
            character_id=requesting_character_id,
            party_id=requesting_party_id,
        )
        context_request_id, context = _record_request_and_context(
            connection,
            agent_assignment_id=agent_assignment_id,
            assignment=assignment,
            requesting_user_id=requesting_user_id,
            requesting_character_id=requesting_character_id,
            requesting_party_id=requesting_party_id,
            player_message=player_message,
            timeline_id=timeline_id,
            expected_world_id=world_id,
        )
    provider_result = provider.generate_npc_turn(context=context, player_message=player_message)

    with authorized_transaction(engine, requesting_user_id, campaign_id) as (connection, plan):
        register_requirements(connection, plan, requirements)
        register_perspective(
            connection,
            plan,
            name="npc_turn.party_perspective",
            character_id=requesting_character_id,
            party_id=requesting_party_id,
        )
        perspective_facts_or_refuse(
            connection,
            campaign_id=campaign_id,
            timeline_id=timeline_id,
            character_id=requesting_character_id,
            party_id=requesting_party_id,
        )
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

        # At most one of these is ever non-None: NpcTurnOutput._at_most_one_
        # proposal already rejected a response naming both at the schema-
        # validation stage (provider_result.structured_output would be None
        # in that case), and each validator only returns non-None for a
        # candidate actually present in this request's own deterministic
        # context — never an arbitrary model-supplied id.
        reveal_target = _validated_reveal_target(context, provider_result.structured_output)
        advance_target = _validated_advance_target(context, provider_result.structured_output)

        proposal_kind: str | None = None
        proposed_arguments: dict[str, str] | None = None
        risk_tier: str | None = None
        if reveal_target is not None:
            knowledge_item_id, _t1_sensitivity = (
                reveal_target  # T1's sensitivity is never used (OP-3)
            )
            fresh = _lock_and_read_reveal_candidate(
                connection,
                campaign_id=campaign_id,
                knowledge_item_id=knowledge_item_id,
                npc_entity_id=assignment.npc_entity_id,
                expected_world_id=world_id,
            )
            if fresh is not None and fresh.qualifies:
                proposal_kind = "reveal_knowledge"
                risk_tier = classify_reveal_knowledge_risk(sensitivity=fresh.sensitivity)
                proposed_arguments = {
                    "knowledge_item_id": str(knowledge_item_id),
                    "party_id": str(requesting_party_id),
                    "timeline_id": str(timeline_id),
                    "world_time_id": str(world_time_id),
                }
        elif advance_target is not None:
            quest_objective_id, _quest_id, new_status_code = advance_target
            proposal_kind = "advance_quest_objective"
            risk_tier = classify_advance_quest_objective_risk(new_status_code=new_status_code)
            proposed_arguments = {
                "quest_objective_id": str(quest_objective_id),
                "new_status_code": new_status_code,
                "party_id": str(requesting_party_id),
                "timeline_id": str(timeline_id),
                "world_time_id": str(world_time_id),
                # The NPC portraying this proposal is the causing actor —
                # trusted context (assignment.npc_entity_id), never
                # model-supplied text.
                "actor_entity_id": str(assignment.npc_entity_id),
            }

        ai_proposed_change_id: uuid.UUID | None = None
        proposal_status: str | None = None
        applied_event_id: uuid.UUID | None = None

        if proposal_kind is not None:
            assert proposed_arguments is not None
            assert risk_tier is not None
            ai_proposed_change_id = connection.execute(
                text("""
                    INSERT INTO ai.proposed_changes
                        (generated_output_id, campaign_id, proposal_kind, proposed_arguments,
                         risk_tier)
                    VALUES (:output, :campaign, :kind, :arguments, :risk_tier)
                    RETURNING ai_proposed_change_id
                """),
                {
                    "output": generated_output_id,
                    "campaign": assignment.campaign_id,
                    "kind": proposal_kind,
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
                    proposal_kind=proposal_kind,
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
