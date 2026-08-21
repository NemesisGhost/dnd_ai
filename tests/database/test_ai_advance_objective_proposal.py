"""`advance_quest_objective` — Phase 12's second proposal-kind vertical
slice (docs/PLAN.md Phase 12). Mirrors `tests/database/test_ai_npc.py`'s
own structure and fixture shape exactly (context-assembly tests against the
rollback-wrapped `db_connection`; the full multi-transaction proposal
pipeline against the real, session-scoped `postgres_engine`), extended with
the quest/objective fixtures this proposal kind needs and the adversarial
scenarios specific to a second, riskier proposal kind (unlike
`reveal_knowledge`, `advance_quest_objective` is always `requires_approval`
— see `dnd_ai.domain.ai_policy.classify_advance_quest_objective_risk`).
"""

import json
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from dnd_ai.commands.ai_npc import request_npc_conversation_turn
from dnd_ai.commands.ai_proposals import (
    ProposedChangeNotFoundError,
    ProposedChangeNotPendingError,
    _apply_proposal,
    review_proposed_change,
)
from dnd_ai.commands.quests import advance_objective
from dnd_ai.domain.ai_provider import FakeAiProvider, NpcTurnOutput, ProviderResult
from dnd_ai.domain.context_assembly import NpcConversationContext, assemble_npc_conversation_context
from tests.factories import (
    make_agent,
    make_agent_assignment,
    make_campaign,
    make_campaign_party,
    make_character,
    make_context_request,
    make_generated_output,
    make_objective_state,
    make_party,
    make_party_membership,
    make_proposed_change,
    make_quest,
    make_quest_objective,
    make_quest_participant,
    make_quest_stage,
    make_quest_state,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database


class Fixture:
    agent_id: uuid.UUID
    assignment_id: uuid.UUID

    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )
        self.npc_id = make_character(connection, self.world_id, name="Old Innkeeper")
        self.pc_id = make_character(connection, self.world_id, name="Hero")
        self.party_id = make_party(connection, self.world_id)
        make_campaign_party(connection, self.campaign_id, self.party_id)
        make_party_membership(
            connection, self.timeline_id, self.party_id, self.pc_id, self.world_time_id
        )

        self.quest_id = make_quest(connection, self.world_id, name="Find the Lost Amulet")
        self.quest_stage_id = make_quest_stage(connection, self.quest_id)
        make_quest_participant(
            connection, self.quest_id, self.npc_id, participant_role="quest_giver"
        )
        make_quest_state(
            connection,
            self.timeline_id,
            self.quest_id,
            party_id=self.party_id,
            status_code="active",
        )

        # Eligible: visible, never started (no campaign.objective_state row
        # at all) — _advance_objective_impl treats "no row yet" as
        # non-terminal, so this must be offered.
        self.open_objective_id = make_quest_objective(
            connection, self.quest_stage_id, name="Recover the amulet", visibility_policy="visible"
        )
        # Already terminal — must never be offered even though it is
        # otherwise visible and belongs to a related quest.
        self.terminal_objective_id = make_quest_objective(
            connection, self.quest_stage_id, name="Already done", visibility_policy="visible"
        )
        make_objective_state(
            connection,
            self.timeline_id,
            self.terminal_objective_id,
            party_id=self.party_id,
            status_code="completed",
        )
        # GM-only — must never be offered regardless of status.
        self.gm_only_objective_id = make_quest_objective(
            connection, self.quest_stage_id, name="Secret GM twist", visibility_policy="gm_only"
        )

        # A quest this NPC does not participate in — its objective must
        # never be offered either, no matter how eligible it looks.
        self.other_quest_id = make_quest(connection, self.world_id, name="Unrelated Quest")
        other_stage_id = make_quest_stage(connection, self.other_quest_id)
        self.foreign_objective_id = make_quest_objective(
            connection, other_stage_id, name="Not this NPC's business", visibility_policy="visible"
        )


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, f"ai-advobj-{uuid.uuid4().hex[:8]}")


# ---------------------------------------------------------------------------
# Context assembly — the closed candidate set advance_quest_objective draws
# from (db_connection, no commit needed)
# ---------------------------------------------------------------------------


def _context(connection: Connection, f: Fixture) -> NpcConversationContext:
    return assemble_npc_conversation_context(
        connection,
        npc_entity_id=f.npc_id,
        timeline_id=f.timeline_id,
        expected_world_id=f.world_id,
        requesting_character_id=f.pc_id,
        requesting_party_id=f.party_id,
    )


def test_context_offers_only_the_eligible_open_objective(
    db_connection: Connection, f: Fixture
) -> None:
    context = _context(db_connection, f)
    offered_ids = {o.quest_objective_id for o in context.advanceable_objectives}
    assert offered_ids == {f.open_objective_id}


def test_context_payload_excludes_inaccessible_objectives(
    db_connection: Connection, f: Fixture
) -> None:
    context = _context(db_connection, f)
    payload = context.as_prompt_payload()
    payload_text = json.dumps(payload)
    assert str(f.open_objective_id) in payload_text
    assert str(f.terminal_objective_id) not in payload_text
    assert str(f.gm_only_objective_id) not in payload_text
    assert str(f.foreign_objective_id) not in payload_text


# ---------------------------------------------------------------------------
# Full pipeline — engine-based, multi-transaction (mirrors test_ai_npc.py's
# own `committed` fixture exactly)
# ---------------------------------------------------------------------------


@pytest.fixture
def committed(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"ai-advobj-commit-{uuid.uuid4().hex[:8]}")
        fixture.agent_id = make_agent(connection)
        fixture.assignment_id = make_agent_assignment(
            connection, fixture.agent_id, fixture.campaign_id, fixture.npc_id
        )
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(text("DELETE FROM ai.agents WHERE agent_id = :a"), {"a": fixture.agent_id})


def _objective_status(
    engine: Engine, *, timeline_id: uuid.UUID, objective_id: uuid.UUID
) -> str | None:
    with engine.connect() as connection:
        return connection.execute(
            text("""
                SELECT os.code FROM campaign.objective_state ost
                JOIN campaign.objective_statuses os ON os.objective_status_id = ost.objective_status_id
                WHERE ost.timeline_id = :timeline AND ost.quest_objective_id = :objective
            """),
            {"timeline": timeline_id, "objective": objective_id},
        ).scalar()


def test_dialogue_only_turn_creates_no_proposal(
    postgres_engine: Engine, committed: Fixture
) -> None:
    result = request_npc_conversation_turn(
        postgres_engine,
        agent_assignment_id=committed.assignment_id,
        requesting_user_id=None,
        requesting_character_id=committed.pc_id,
        requesting_party_id=committed.party_id,
        player_message="Just saying hello.",
        provider=FakeAiProvider(dialogue="Well met, traveler."),
        timeline_id=committed.timeline_id,
        expected_world_id=committed.world_id,
        world_time_id=committed.world_time_id,
    )
    assert result.dialogue == "Well met, traveler."
    assert result.ai_proposed_change_id is None
    assert result.proposal_status is None
    assert result.applied_event_id is None


def test_advance_proposal_is_pending_and_never_auto_applied(
    postgres_engine: Engine, committed: Fixture
) -> None:
    """Unlike reveal_knowledge, advance_quest_objective is always
    requires_approval — see classify_advance_quest_objective_risk."""
    result = request_npc_conversation_turn(
        postgres_engine,
        agent_assignment_id=committed.assignment_id,
        requesting_user_id=None,
        requesting_character_id=committed.pc_id,
        requesting_party_id=committed.party_id,
        player_message="We found the amulet!",
        provider=FakeAiProvider(dialogue="At last!", advance_first_candidate=True),
        timeline_id=committed.timeline_id,
        expected_world_id=committed.world_id,
        world_time_id=committed.world_time_id,
    )
    assert result.ai_proposed_change_id is not None
    assert result.proposal_status == "pending"
    assert result.applied_event_id is None

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT proposal_kind, risk_tier, status
                FROM ai.proposed_changes WHERE ai_proposed_change_id = :id
            """),
            {"id": result.ai_proposed_change_id},
        ).one()
        assert row.proposal_kind == "advance_quest_objective"
        assert row.risk_tier == "requires_approval"
        assert row.status == "pending"

    assert (
        _objective_status(
            postgres_engine,
            timeline_id=committed.timeline_id,
            objective_id=committed.open_objective_id,
        )
        is None
    )


def test_approving_advance_objective_invokes_the_quest_command_and_records_event(
    postgres_engine: Engine, committed: Fixture
) -> None:
    with postgres_engine.begin() as connection:
        reviewer_user_id = make_user(connection, "Reviewer")

    result = request_npc_conversation_turn(
        postgres_engine,
        agent_assignment_id=committed.assignment_id,
        requesting_user_id=None,
        requesting_character_id=committed.pc_id,
        requesting_party_id=committed.party_id,
        player_message="We found the amulet!",
        provider=FakeAiProvider(dialogue="At last!", advance_first_candidate=True),
        timeline_id=committed.timeline_id,
        expected_world_id=committed.world_id,
        world_time_id=committed.world_time_id,
    )
    assert result.ai_proposed_change_id is not None

    review = review_proposed_change(
        postgres_engine,
        ai_proposed_change_id=result.ai_proposed_change_id,
        campaign_id=committed.campaign_id,
        reviewer_user_id=reviewer_user_id,
        decision="approve",
    )
    assert review.status == "applied"
    assert review.applied_event_id is not None

    assert (
        _objective_status(
            postgres_engine,
            timeline_id=committed.timeline_id,
            objective_id=committed.open_objective_id,
        )
        == "completed"
    )

    with postgres_engine.connect() as verify:
        event_row = verify.execute(
            text("""
                SELECT et.code FROM narrative.events e
                JOIN narrative.event_types et ON et.event_type_id = e.event_type_id
                WHERE e.event_id = :id
            """),
            {"id": review.applied_event_id},
        ).one()
        assert event_row.code == "objective_completed"

        effect_count = verify.execute(
            text("""
                SELECT count(*) FROM narrative.event_effects
                WHERE event_id = :event AND target_quest_objective_id = :objective
            """),
            {"event": review.applied_event_id, "objective": committed.open_objective_id},
        ).scalar()
        assert effect_count == 1

    with postgres_engine.begin() as cleanup:
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = :u"), {"u": reviewer_user_id}
        )


def test_rejecting_advance_objective_leaves_canonical_state_unchanged(
    postgres_engine: Engine, committed: Fixture
) -> None:
    with postgres_engine.begin() as connection:
        reviewer_user_id = make_user(connection, "Reviewer")

    result = request_npc_conversation_turn(
        postgres_engine,
        agent_assignment_id=committed.assignment_id,
        requesting_user_id=None,
        requesting_character_id=committed.pc_id,
        requesting_party_id=committed.party_id,
        player_message="We found the amulet!",
        provider=FakeAiProvider(dialogue="At last!", advance_first_candidate=True),
        timeline_id=committed.timeline_id,
        expected_world_id=committed.world_id,
        world_time_id=committed.world_time_id,
    )
    assert result.ai_proposed_change_id is not None

    review = review_proposed_change(
        postgres_engine,
        ai_proposed_change_id=result.ai_proposed_change_id,
        campaign_id=committed.campaign_id,
        reviewer_user_id=reviewer_user_id,
        decision="reject",
    )
    assert review.status == "rejected"
    assert review.applied_event_id is None

    assert (
        _objective_status(
            postgres_engine,
            timeline_id=committed.timeline_id,
            objective_id=committed.open_objective_id,
        )
        is None
    )

    with postgres_engine.connect() as verify:
        status = verify.execute(
            text("SELECT status FROM ai.proposed_changes WHERE ai_proposed_change_id = :id"),
            {"id": result.ai_proposed_change_id},
        ).scalar()
        assert status == "rejected"

    with postgres_engine.begin() as cleanup:
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = :u"), {"u": reviewer_user_id}
        )


# ---------------------------------------------------------------------------
# Adversarial: a model naming an objective id outside the authorized
# candidate set — dnd_ai.commands.ai_npc must silently create no proposal
# at all, never trusting the model's own claim.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _NamedObjectiveProvider:
    """A minimal AiProvider stub that names a fixed objective id directly —
    used only to prove `dnd_ai.commands.ai_npc` re-validates a model-named
    id against `context.advanceable_objectives` itself, rather than
    trusting it. Unrelated to `OpenAiCompatibleProvider`'s own mocked-HTTP
    coverage (`tests/unit/test_ai_provider.py`); this never touches HTTP at
    all — the "provider" here is just a fixed structured-output value, the
    same role `FakeAiProvider` plays for the always-in-context case."""

    objective_id: uuid.UUID
    dialogue: str = "Perhaps."

    def generate_npc_turn(
        self,
        *,
        context: NpcConversationContext,
        player_message: str,  # noqa: ARG002
    ) -> ProviderResult:
        return ProviderResult(
            raw_response=self.dialogue,
            structured_output=NpcTurnOutput(
                dialogue=self.dialogue,
                advance_quest_objective_id=self.objective_id,
                advance_quest_objective_new_status="completed",
            ),
            finish_reason="stop",
            latency_ms=0,
            error_message=None,
        )

    def generate_synthesis(
        self, *, context: dict[str, Any], audience_tier: str, question_text: str
    ) -> Any:
        raise NotImplementedError


def _assert_named_objective_produces_no_proposal(
    postgres_engine: Engine, committed: Fixture, objective_id: uuid.UUID
) -> None:
    result = request_npc_conversation_turn(
        postgres_engine,
        agent_assignment_id=committed.assignment_id,
        requesting_user_id=None,
        requesting_character_id=committed.pc_id,
        requesting_party_id=committed.party_id,
        player_message="We found the amulet!",
        provider=_NamedObjectiveProvider(objective_id=objective_id),
        timeline_id=committed.timeline_id,
        expected_world_id=committed.world_id,
        world_time_id=committed.world_time_id,
    )
    assert result.dialogue == "Perhaps."
    assert result.ai_proposed_change_id is None
    assert result.proposal_status is None
    assert result.applied_event_id is None


def test_terminal_objective_named_by_the_model_produces_no_proposal(
    postgres_engine: Engine, committed: Fixture
) -> None:
    _assert_named_objective_produces_no_proposal(
        postgres_engine, committed, committed.terminal_objective_id
    )


def test_gm_only_objective_named_by_the_model_produces_no_proposal(
    postgres_engine: Engine, committed: Fixture
) -> None:
    _assert_named_objective_produces_no_proposal(
        postgres_engine, committed, committed.gm_only_objective_id
    )


def test_foreign_quest_objective_named_by_the_model_produces_no_proposal(
    postgres_engine: Engine, committed: Fixture
) -> None:
    """An objective that exists, is visible, and is even non-terminal — but
    belongs to a quest this NPC has no narrative.quest_participants row
    for — must be exactly as rejected as one that doesn't exist at all."""
    _assert_named_objective_produces_no_proposal(
        postgres_engine, committed, committed.foreign_objective_id
    )


def test_nonexistent_objective_id_named_by_the_model_produces_no_proposal(
    postgres_engine: Engine, committed: Fixture
) -> None:
    _assert_named_objective_produces_no_proposal(postgres_engine, committed, uuid.uuid4())


# ---------------------------------------------------------------------------
# Adversarial: defense in depth at apply time — even if a proposed_changes
# row somehow carried an invalid payload (a tampered row, a future bug
# upstream), _apply_proposal must fail closed and never partially mutate
# canonical state.
# ---------------------------------------------------------------------------


def test_apply_rejects_an_unsupported_transition(
    postgres_engine: Engine, committed: Fixture
) -> None:
    with pytest.raises(ValueError, match="new_status_code"), postgres_engine.begin() as connection:
        _apply_proposal(
            connection,
            ai_proposed_change_id=uuid.uuid4(),
            proposal_kind="advance_quest_objective",
            proposed_arguments={
                "quest_objective_id": str(committed.open_objective_id),
                "new_status_code": "skipped",
                "timeline_id": str(committed.timeline_id),
                "world_time_id": str(committed.world_time_id),
                "party_id": str(committed.party_id),
            },
            campaign_id=committed.campaign_id,
        )
    assert (
        _objective_status(
            postgres_engine,
            timeline_id=committed.timeline_id,
            objective_id=committed.open_objective_id,
        )
        is None
    )


def test_apply_rejects_a_missing_argument(postgres_engine: Engine, committed: Fixture) -> None:
    with (
        pytest.raises(ValueError, match="quest_objective_id"),
        postgres_engine.begin() as connection,
    ):
        _apply_proposal(
            connection,
            ai_proposed_change_id=uuid.uuid4(),
            proposal_kind="advance_quest_objective",
            proposed_arguments={
                "new_status_code": "completed",
                "timeline_id": str(committed.timeline_id),
                "world_time_id": str(committed.world_time_id),
            },
            campaign_id=committed.campaign_id,
        )


def test_apply_rejects_a_malformed_argument(postgres_engine: Engine, committed: Fixture) -> None:
    with pytest.raises(ValueError), postgres_engine.begin() as connection:
        _apply_proposal(
            connection,
            ai_proposed_change_id=uuid.uuid4(),
            proposal_kind="advance_quest_objective",
            proposed_arguments={
                "quest_objective_id": "not-a-valid-uuid",
                "new_status_code": "completed",
                "timeline_id": str(committed.timeline_id),
                "world_time_id": str(committed.world_time_id),
            },
            campaign_id=committed.campaign_id,
        )


def test_apply_rejects_an_unknown_proposal_kind(
    postgres_engine: Engine, committed: Fixture
) -> None:
    with (
        pytest.raises(ValueError, match="unknown proposal_kind"),
        postgres_engine.begin() as connection,
    ):
        _apply_proposal(
            connection,
            ai_proposed_change_id=uuid.uuid4(),
            proposal_kind="bogus_kind",
            proposed_arguments={},
            campaign_id=committed.campaign_id,
        )


def test_already_terminal_at_apply_time_rolls_back_the_whole_review(
    postgres_engine: Engine, committed: Fixture
) -> None:
    """The race this proves safe: a proposal is created while the objective
    is still open, but by the time a human reviewer approves it, someone
    else has already resolved the objective independently. Approval must
    fail (the same _advance_objective_impl guard that protects a direct
    call), and — since review-row-insert and apply share one transaction —
    the review decision itself must never be recorded either."""
    with postgres_engine.begin() as connection:
        reviewer_user_id = make_user(connection, "Reviewer")

    result = request_npc_conversation_turn(
        postgres_engine,
        agent_assignment_id=committed.assignment_id,
        requesting_user_id=None,
        requesting_character_id=committed.pc_id,
        requesting_party_id=committed.party_id,
        player_message="We found the amulet!",
        provider=FakeAiProvider(dialogue="At last!", advance_first_candidate=True),
        timeline_id=committed.timeline_id,
        expected_world_id=committed.world_id,
        world_time_id=committed.world_time_id,
    )
    assert result.ai_proposed_change_id is not None

    # Someone else resolves the same objective first, independently of the
    # pending proposal.
    advance_objective(
        postgres_engine,
        quest_objective_id=committed.open_objective_id,
        timeline_id=committed.timeline_id,
        world_time_id=committed.world_time_id,
        new_status_code="failed",
        party_id=committed.party_id,
        campaign_id=committed.campaign_id,
    )

    with pytest.raises(ValueError, match="terminal"):
        review_proposed_change(
            postgres_engine,
            ai_proposed_change_id=result.ai_proposed_change_id,
            campaign_id=committed.campaign_id,
            reviewer_user_id=reviewer_user_id,
            decision="approve",
        )

    with postgres_engine.connect() as verify:
        # The proposal itself is untouched — still pending, since the
        # review transaction rolled back before its own UPDATE could commit.
        status = verify.execute(
            text("SELECT status FROM ai.proposed_changes WHERE ai_proposed_change_id = :id"),
            {"id": result.ai_proposed_change_id},
        ).scalar()
        assert status == "pending"

        # No review row was ever committed for this attempt.
        review_count = verify.execute(
            text("SELECT count(*) FROM ai.change_reviews WHERE ai_proposed_change_id = :id"),
            {"id": result.ai_proposed_change_id},
        ).scalar()
        assert review_count == 0

    # The objective still reflects only the independent advance_objective()
    # call above — 'failed', not overwritten or duplicated by the rolled-
    # back review attempt.
    assert (
        _objective_status(
            postgres_engine,
            timeline_id=committed.timeline_id,
            objective_id=committed.open_objective_id,
        )
        == "failed"
    )

    with postgres_engine.begin() as cleanup:
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = :u"), {"u": reviewer_user_id}
        )


# ---------------------------------------------------------------------------
# Review lifecycle: a proposal is reviewed exactly once — duplicate/repeat
# decisions and concurrent reviewers.
# ---------------------------------------------------------------------------


def _pending_advance_proposal(postgres_engine: Engine, committed: Fixture) -> uuid.UUID:
    result = request_npc_conversation_turn(
        postgres_engine,
        agent_assignment_id=committed.assignment_id,
        requesting_user_id=None,
        requesting_character_id=committed.pc_id,
        requesting_party_id=committed.party_id,
        player_message="We found the amulet!",
        provider=FakeAiProvider(dialogue="At last!", advance_first_candidate=True),
        timeline_id=committed.timeline_id,
        expected_world_id=committed.world_id,
        world_time_id=committed.world_time_id,
    )
    assert result.ai_proposed_change_id is not None
    return result.ai_proposed_change_id


def test_duplicate_approval_is_rejected(postgres_engine: Engine, committed: Fixture) -> None:
    with postgres_engine.begin() as connection:
        reviewer_user_id = make_user(connection, "Reviewer")
    proposal_id = _pending_advance_proposal(postgres_engine, committed)

    review_proposed_change(
        postgres_engine,
        ai_proposed_change_id=proposal_id,
        campaign_id=committed.campaign_id,
        reviewer_user_id=reviewer_user_id,
        decision="approve",
    )
    with pytest.raises(ProposedChangeNotPendingError):
        review_proposed_change(
            postgres_engine,
            ai_proposed_change_id=proposal_id,
            campaign_id=committed.campaign_id,
            reviewer_user_id=reviewer_user_id,
            decision="approve",
        )

    with postgres_engine.begin() as cleanup:
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = :u"), {"u": reviewer_user_id}
        )


def test_rejection_after_approval_is_rejected(postgres_engine: Engine, committed: Fixture) -> None:
    with postgres_engine.begin() as connection:
        reviewer_user_id = make_user(connection, "Reviewer")
    proposal_id = _pending_advance_proposal(postgres_engine, committed)

    review_proposed_change(
        postgres_engine,
        ai_proposed_change_id=proposal_id,
        campaign_id=committed.campaign_id,
        reviewer_user_id=reviewer_user_id,
        decision="approve",
    )
    with pytest.raises(ProposedChangeNotPendingError):
        review_proposed_change(
            postgres_engine,
            ai_proposed_change_id=proposal_id,
            campaign_id=committed.campaign_id,
            reviewer_user_id=reviewer_user_id,
            decision="reject",
        )

    with postgres_engine.begin() as cleanup:
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = :u"), {"u": reviewer_user_id}
        )


def test_approval_after_rejection_is_rejected(postgres_engine: Engine, committed: Fixture) -> None:
    with postgres_engine.begin() as connection:
        reviewer_user_id = make_user(connection, "Reviewer")
    proposal_id = _pending_advance_proposal(postgres_engine, committed)

    review_proposed_change(
        postgres_engine,
        ai_proposed_change_id=proposal_id,
        campaign_id=committed.campaign_id,
        reviewer_user_id=reviewer_user_id,
        decision="reject",
    )
    with pytest.raises(ProposedChangeNotPendingError):
        review_proposed_change(
            postgres_engine,
            ai_proposed_change_id=proposal_id,
            campaign_id=committed.campaign_id,
            reviewer_user_id=reviewer_user_id,
            decision="approve",
        )

    with postgres_engine.begin() as cleanup:
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = :u"), {"u": reviewer_user_id}
        )


def test_concurrent_reviews_serialize_and_apply_exactly_once(
    postgres_engine: Engine, committed: Fixture
) -> None:
    """Two reviewers racing to decide the same pending proposal must
    serialize on _lock_pending_proposal's own SELECT ... FOR UPDATE —
    exactly one succeeds, the other observes a no-longer-pending proposal,
    and the objective is advanced exactly once (never duplicated)."""
    with postgres_engine.begin() as connection:
        reviewer_a = make_user(connection, "Reviewer A")
        reviewer_b = make_user(connection, "Reviewer B")
    proposal_id = _pending_advance_proposal(postgres_engine, committed)

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    errors: dict[str, Exception] = {}

    def _review(label: str, reviewer_user_id: uuid.UUID) -> None:
        barrier.wait(timeout=30)
        try:
            results[label] = review_proposed_change(
                postgres_engine,
                ai_proposed_change_id=proposal_id,
                campaign_id=committed.campaign_id,
                reviewer_user_id=reviewer_user_id,
                decision="approve",
            )
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            errors[label] = exc

    thread_a = threading.Thread(target=_review, args=("a", reviewer_a))
    thread_b = threading.Thread(target=_review, args=("b", reviewer_b))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=30)
    thread_b.join(timeout=30)

    assert len(results) == 1, f"expected exactly one success, got {results!r} / {errors!r}"
    assert len(errors) == 1
    (failed_label,) = errors
    assert isinstance(errors[failed_label], ProposedChangeNotPendingError)

    with postgres_engine.connect() as verify:
        review_count = verify.execute(
            text("SELECT count(*) FROM ai.change_reviews WHERE ai_proposed_change_id = :id"),
            {"id": proposal_id},
        ).scalar()
        assert review_count == 1

        event_count = verify.execute(
            text("""
                SELECT count(*) FROM narrative.event_effects
                WHERE target_quest_objective_id = :objective
            """),
            {"objective": committed.open_objective_id},
        ).scalar()
        assert event_count == 1

    assert (
        _objective_status(
            postgres_engine,
            timeline_id=committed.timeline_id,
            objective_id=committed.open_objective_id,
        )
        == "completed"
    )

    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("DELETE FROM security.users WHERE user_id = :u"), {"u": reviewer_a})
        cleanup.execute(text("DELETE FROM security.users WHERE user_id = :u"), {"u": reviewer_b})


def test_review_still_rejects_a_proposal_from_a_different_campaign(
    postgres_engine: Engine, committed: Fixture
) -> None:
    with postgres_engine.begin() as connection:
        other_campaign_id = make_campaign(
            connection, committed.timeline_id, "Other Campaign", lifecycle_status_code="pending"
        )
        reviewer_user_id = make_user(connection, "Cross-Campaign Reviewer")
    proposal_id = _pending_advance_proposal(postgres_engine, committed)

    with pytest.raises(ProposedChangeNotFoundError):
        review_proposed_change(
            postgres_engine,
            ai_proposed_change_id=proposal_id,
            campaign_id=other_campaign_id,
            reviewer_user_id=reviewer_user_id,
            decision="approve",
        )

    with postgres_engine.begin() as cleanup:
        cleanup.execute(
            text("DELETE FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": other_campaign_id},
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = :u"), {"u": reviewer_user_id}
        )


# ---------------------------------------------------------------------------
# Migration/constraint: the widened ai.proposed_changes.proposal_kind CHECK
# (migration 097_advance_objective_kind) — schema-level, not command-level.
# ---------------------------------------------------------------------------


def _parent_generated_output(connection: Connection, f: Fixture) -> uuid.UUID:
    agent_id = make_agent(connection)
    assignment_id = make_agent_assignment(connection, agent_id, f.campaign_id, f.npc_id)
    context_request_id = make_context_request(connection, assignment_id)
    return make_generated_output(connection, context_request_id)


def test_advance_quest_objective_is_a_valid_proposal_kind(
    db_connection: Connection, f: Fixture
) -> None:
    generated_output_id = _parent_generated_output(db_connection, f)
    proposal_id = make_proposed_change(
        db_connection,
        generated_output_id,
        f.campaign_id,
        proposal_kind="advance_quest_objective",
        proposed_arguments={"quest_objective_id": str(f.open_objective_id)},
    )
    assert proposal_id is not None


def test_reveal_knowledge_is_still_a_valid_proposal_kind(
    db_connection: Connection, f: Fixture
) -> None:
    generated_output_id = _parent_generated_output(db_connection, f)
    proposal_id = make_proposed_change(
        db_connection,
        generated_output_id,
        f.campaign_id,
        proposal_kind="reveal_knowledge",
        proposed_arguments={"knowledge_item_id": str(uuid.uuid4())},
    )
    assert proposal_id is not None


def test_an_unrecognized_proposal_kind_is_rejected_by_the_database(
    db_connection: Connection, f: Fixture
) -> None:
    generated_output_id = _parent_generated_output(db_connection, f)
    with pytest.raises(IntegrityError):
        make_proposed_change(
            db_connection,
            generated_output_id,
            f.campaign_id,
            proposal_kind="bogus_kind",
            proposed_arguments={},
        )
