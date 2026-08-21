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
import time
import traceback
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from dnd_ai.commands.ai_npc import request_npc_conversation_turn
from dnd_ai.commands.ai_proposals import (
    ProposedChangeNotFoundError,
    ProposedChangeNotPendingError,
    ReviewProposedChangeResult,
    _apply_proposal,
    review_proposed_change,
)
from dnd_ai.commands.quests import advance_objective
from dnd_ai.domain.ai_provider import FakeAiProvider, NpcTurnOutput, ProviderResult
from dnd_ai.domain.context_assembly import NpcConversationContext, assemble_npc_conversation_context
from tests.factories import (
    cleanup_committed_ai_world,
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
        # Bounded so a worker thread left genuinely stuck by this file's
        # own concurrency tests (test_concurrent_reviews_serialize_and_
        # apply_exactly_once, test_a_concurrent_visibility_change_during_
        # approval_is_always_safe, and the other deterministic races) can
        # never turn a single failing test into an indefinitely hung test
        # session — a lock this cleanup can't acquire within 30s raises a
        # clear, immediately diagnosable timeout instead of hanging
        # forever.
        cleanup.execute(text("SET LOCAL statement_timeout = '30s'"))
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup_committed_ai_world(
            cleanup,
            world_id=fixture.world_id,
            campaign_id=fixture.campaign_id,
            agent_id=fixture.agent_id,
        )


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


def _complete_advance_arguments(f: Fixture, **overrides: object) -> dict[str, object]:
    """A syntactically complete advance_quest_objective proposed_arguments
    payload — every _ADVANCE_QUEST_OBJECTIVE_KEYS key present and
    well-typed — with individual fields overridden by the caller, so each
    adversarial test below isolates exactly the one thing it claims to be
    testing rather than incidentally also tripping the exact-key-set
    check (missing keys) at the same time."""
    base: dict[str, object] = {
        "quest_objective_id": str(f.open_objective_id),
        "new_status_code": "completed",
        "party_id": str(f.party_id),
        "timeline_id": str(f.timeline_id),
        "world_time_id": str(f.world_time_id),
        "actor_entity_id": str(f.npc_id),
    }
    base.update(overrides)
    return base


def test_apply_rejects_an_unsupported_transition(
    postgres_engine: Engine, committed: Fixture
) -> None:
    with pytest.raises(ValueError, match="new_status_code"), postgres_engine.begin() as connection:
        _apply_proposal(
            connection,
            ai_proposed_change_id=uuid.uuid4(),
            proposal_kind="advance_quest_objective",
            proposed_arguments=_complete_advance_arguments(committed, new_status_code="skipped"),
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
    arguments = _complete_advance_arguments(committed)
    del arguments["quest_objective_id"]
    with (
        pytest.raises(ValueError, match="quest_objective_id"),
        postgres_engine.begin() as connection,
    ):
        _apply_proposal(
            connection,
            ai_proposed_change_id=uuid.uuid4(),
            proposal_kind="advance_quest_objective",
            proposed_arguments=arguments,
            campaign_id=committed.campaign_id,
        )


def test_apply_rejects_a_malformed_argument(postgres_engine: Engine, committed: Fixture) -> None:
    with pytest.raises(ValueError), postgres_engine.begin() as connection:
        _apply_proposal(
            connection,
            ai_proposed_change_id=uuid.uuid4(),
            proposal_kind="advance_quest_objective",
            proposed_arguments=_complete_advance_arguments(
                committed, quest_objective_id="not-a-valid-uuid"
            ),
            campaign_id=committed.campaign_id,
        )


@pytest.mark.parametrize(
    "missing_key",
    [
        "quest_objective_id",
        "new_status_code",
        "party_id",
        "timeline_id",
        "world_time_id",
        "actor_entity_id",
    ],
)
def test_apply_rejects_each_missing_required_key_individually(
    postgres_engine: Engine, committed: Fixture, missing_key: str
) -> None:
    arguments = _complete_advance_arguments(committed)
    del arguments[missing_key]
    with pytest.raises(ValueError) as exc_info, postgres_engine.begin() as connection:
        _apply_proposal(
            connection,
            ai_proposed_change_id=uuid.uuid4(),
            proposal_kind="advance_quest_objective",
            proposed_arguments=arguments,
            campaign_id=committed.campaign_id,
        )
    assert f"missing ['{missing_key}']" in str(exc_info.value)


@pytest.mark.parametrize(
    "uuid_key",
    ["quest_objective_id", "party_id", "timeline_id", "world_time_id", "actor_entity_id"],
)
def test_apply_rejects_each_malformed_uuid_individually(
    postgres_engine: Engine, committed: Fixture, uuid_key: str
) -> None:
    with pytest.raises(ValueError), postgres_engine.begin() as connection:
        _apply_proposal(
            connection,
            ai_proposed_change_id=uuid.uuid4(),
            proposal_kind="advance_quest_objective",
            proposed_arguments=_complete_advance_arguments(
                committed, **{uuid_key: "not-a-valid-uuid"}
            ),
            campaign_id=committed.campaign_id,
        )


def test_apply_rejects_an_unexpected_extra_key(postgres_engine: Engine, committed: Fixture) -> None:
    arguments = _complete_advance_arguments(committed)
    arguments["session_id"] = str(uuid.uuid4())
    with pytest.raises(ValueError, match="session_id"), postgres_engine.begin() as connection:
        _apply_proposal(
            connection,
            ai_proposed_change_id=uuid.uuid4(),
            proposal_kind="advance_quest_objective",
            proposed_arguments=arguments,
            campaign_id=committed.campaign_id,
        )


def test_apply_rejects_a_missing_party_id_and_creates_no_campaign_wide_state(
    postgres_engine: Engine, committed: Fixture
) -> None:
    """party_id must never silently default to None: _advance_objective_
    impl treats party_id=None as the campaign-wide campaign.objective_state
    row (party_id IS NULL), a materially broader scope than the party-
    scoped row this objective's candidacy was actually checked against."""
    arguments = _complete_advance_arguments(committed)
    del arguments["party_id"]
    with pytest.raises(ValueError, match="party_id"), postgres_engine.begin() as connection:
        _apply_proposal(
            connection,
            ai_proposed_change_id=uuid.uuid4(),
            proposal_kind="advance_quest_objective",
            proposed_arguments=arguments,
            campaign_id=committed.campaign_id,
        )

    with postgres_engine.connect() as verify:
        campaign_wide_rows = verify.execute(
            text("""
                SELECT count(*) FROM campaign.objective_state
                WHERE quest_objective_id = :objective AND party_id IS NULL
            """),
            {"objective": committed.open_objective_id},
        ).scalar()
        assert campaign_wide_rows == 0, (
            "a rejected proposal must never create a campaign-wide objective_state row"
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
# _revalidate_advance_quest_objective: everything that can become false
# between a proposal's creation and its review, each proven to roll back the
# whole review transaction (pending status preserved, no review row, no
# event/effect, objective state untouched) — never a partial application.
# "Cross-world" specifically is not exercised as its own scenario: narrative.
# enforce_quest_participant_world() (revision 073) already makes it
# structurally impossible for the audit-chain-derived NPC to "still
# participate" in a quest belonging to a different world than its own, so
# the still_participates check below is unreachable-past for any
# quest_objective_id that isn't already same-world — get_quest_view's own
# QuestNotFoundError is genuine defense in depth for that case, not a
# reachable production path worth a dedicated (and necessarily contrived)
# test.
# ---------------------------------------------------------------------------


def _pending_advance_proposal_id(postgres_engine: Engine, committed: Fixture) -> uuid.UUID:
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


def _assert_review_rolled_back_completely(
    postgres_engine: Engine, *, proposal_id: uuid.UUID, committed: Fixture
) -> None:
    """The shared postcondition every revalidation-failure test below
    proves: the review transaction rolled back in full, not partially —
    the proposal is still exactly as it was before review was attempted."""
    with postgres_engine.connect() as verify:
        status = verify.execute(
            text("SELECT status FROM ai.proposed_changes WHERE ai_proposed_change_id = :id"),
            {"id": proposal_id},
        ).scalar()
        assert status == "pending"

        review_count = verify.execute(
            text("SELECT count(*) FROM ai.change_reviews WHERE ai_proposed_change_id = :id"),
            {"id": proposal_id},
        ).scalar()
        assert review_count == 0

    assert (
        _objective_status(
            postgres_engine,
            timeline_id=committed.timeline_id,
            objective_id=committed.open_objective_id,
        )
        is None
    )


def test_npc_participation_removed_before_approval_rolls_back(
    postgres_engine: Engine, committed: Fixture
) -> None:
    with postgres_engine.begin() as connection:
        reviewer_user_id = make_user(connection, "Reviewer")
    proposal_id = _pending_advance_proposal_id(postgres_engine, committed)

    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM narrative.quest_participants "
                "WHERE quest_id = :quest AND participant_entity_id = :npc"
            ),
            {"quest": committed.quest_id, "npc": committed.npc_id},
        )

    with pytest.raises(ValueError):
        review_proposed_change(
            postgres_engine,
            ai_proposed_change_id=proposal_id,
            campaign_id=committed.campaign_id,
            reviewer_user_id=reviewer_user_id,
            decision="approve",
        )
    _assert_review_rolled_back_completely(
        postgres_engine, proposal_id=proposal_id, committed=committed
    )

    with postgres_engine.begin() as cleanup:
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = :u"), {"u": reviewer_user_id}
        )


def test_visibility_changed_to_gm_only_before_approval_rolls_back(
    postgres_engine: Engine, committed: Fixture
) -> None:
    with postgres_engine.begin() as connection:
        reviewer_user_id = make_user(connection, "Reviewer")
    proposal_id = _pending_advance_proposal_id(postgres_engine, committed)

    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE narrative.quest_objectives SET visibility_policy = 'gm_only' "
                "WHERE quest_objective_id = :objective"
            ),
            {"objective": committed.open_objective_id},
        )

    with pytest.raises(ValueError):
        review_proposed_change(
            postgres_engine,
            ai_proposed_change_id=proposal_id,
            campaign_id=committed.campaign_id,
            reviewer_user_id=reviewer_user_id,
            decision="approve",
        )
    _assert_review_rolled_back_completely(
        postgres_engine, proposal_id=proposal_id, committed=committed
    )

    with postgres_engine.begin() as cleanup:
        connection = cleanup
        connection.execute(
            text(
                "UPDATE narrative.quest_objectives SET visibility_policy = 'visible' "
                "WHERE quest_objective_id = :objective"
            ),
            {"objective": committed.open_objective_id},
        )
        connection.execute(
            text("DELETE FROM security.users WHERE user_id = :u"), {"u": reviewer_user_id}
        )


def test_party_removed_from_campaign_before_approval_rolls_back(
    postgres_engine: Engine, committed: Fixture
) -> None:
    with postgres_engine.begin() as connection:
        reviewer_user_id = make_user(connection, "Reviewer")
    proposal_id = _pending_advance_proposal_id(postgres_engine, committed)

    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM campaign.campaign_parties "
                "WHERE campaign_id = :campaign AND party_id = :party"
            ),
            {"campaign": committed.campaign_id, "party": committed.party_id},
        )

    with pytest.raises(ValueError):
        review_proposed_change(
            postgres_engine,
            ai_proposed_change_id=proposal_id,
            campaign_id=committed.campaign_id,
            reviewer_user_id=reviewer_user_id,
            decision="approve",
        )
    _assert_review_rolled_back_completely(
        postgres_engine, proposal_id=proposal_id, committed=committed
    )

    with postgres_engine.begin() as cleanup:
        # Restore the association so `committed`'s own teardown (which
        # cascades from core.worlds) has nothing unusual to clean up.
        cleanup.execute(
            text(
                "INSERT INTO campaign.campaign_parties (campaign_id, party_id) "
                "VALUES (:campaign, :party)"
            ),
            {"campaign": committed.campaign_id, "party": committed.party_id},
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = :u"), {"u": reviewer_user_id}
        )


def test_stored_timeline_differing_from_campaigns_pinned_timeline_rolls_back(
    postgres_engine: Engine, committed: Fixture
) -> None:
    """Simulates a proposal whose stored timeline_id no longer matches the
    campaign's current pinned timeline by tampering the stored JSONB
    directly — the same "a tampered or future-buggy row" threat model
    every other adversarial test in this file uses, and a strictly simpler,
    equally valid way to prove the check than mutating campaign.campaigns.
    timeline_id itself (which risks tripping unrelated same-world/same-
    ruleset consistency triggers that have nothing to do with what this
    test is about)."""
    with postgres_engine.begin() as connection:
        reviewer_user_id = make_user(connection, "Reviewer")
        other_timeline_id = make_timeline(connection, committed.world_id, "Other Timeline")
    proposal_id = _pending_advance_proposal_id(postgres_engine, committed)

    with postgres_engine.begin() as connection:
        arguments = connection.execute(
            text(
                "SELECT proposed_arguments FROM ai.proposed_changes WHERE ai_proposed_change_id = :id"
            ),
            {"id": proposal_id},
        ).scalar_one()
        arguments["timeline_id"] = str(other_timeline_id)
        connection.execute(
            text(
                "UPDATE ai.proposed_changes SET proposed_arguments = :arguments "
                "WHERE ai_proposed_change_id = :id"
            ),
            {"arguments": json.dumps(arguments), "id": proposal_id},
        )

    with pytest.raises(ValueError):
        review_proposed_change(
            postgres_engine,
            ai_proposed_change_id=proposal_id,
            campaign_id=committed.campaign_id,
            reviewer_user_id=reviewer_user_id,
            decision="approve",
        )
    _assert_review_rolled_back_completely(
        postgres_engine, proposal_id=proposal_id, committed=committed
    )

    with postgres_engine.begin() as cleanup:
        cleanup.execute(
            text("DELETE FROM campaign.timelines WHERE timeline_id = :t"), {"t": other_timeline_id}
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = :u"), {"u": reviewer_user_id}
        )


def test_cross_quest_objective_named_in_a_tampered_proposal_is_rejected(
    postgres_engine: Engine, committed: Fixture
) -> None:
    """A tampered proposal naming an objective from a quest this NPC does
    not participate in — foreign_objective_id, exactly like the model-
    named adversarial cases above, but reached via a tampered stored row
    instead of a model naming it directly."""
    with postgres_engine.begin() as connection:
        reviewer_user_id = make_user(connection, "Reviewer")
    proposal_id = _pending_advance_proposal_id(postgres_engine, committed)

    with postgres_engine.begin() as connection:
        arguments = connection.execute(
            text(
                "SELECT proposed_arguments FROM ai.proposed_changes WHERE ai_proposed_change_id = :id"
            ),
            {"id": proposal_id},
        ).scalar_one()
        arguments["quest_objective_id"] = str(committed.foreign_objective_id)
        connection.execute(
            text(
                "UPDATE ai.proposed_changes SET proposed_arguments = :arguments "
                "WHERE ai_proposed_change_id = :id"
            ),
            {"arguments": json.dumps(arguments), "id": proposal_id},
        )

    with pytest.raises(ValueError):
        review_proposed_change(
            postgres_engine,
            ai_proposed_change_id=proposal_id,
            campaign_id=committed.campaign_id,
            reviewer_user_id=reviewer_user_id,
            decision="approve",
        )
    _assert_review_rolled_back_completely(
        postgres_engine, proposal_id=proposal_id, committed=committed
    )
    assert (
        _objective_status(
            postgres_engine,
            timeline_id=committed.timeline_id,
            objective_id=committed.foreign_objective_id,
        )
        is None
    )

    with postgres_engine.begin() as cleanup:
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = :u"), {"u": reviewer_user_id}
        )


_CONCURRENT_RACE_DEADLINE_SECONDS = 60


def _run_concurrent_race(
    label_a: str,
    action_a: Callable[[], object],
    label_b: str,
    action_b: Callable[[], object],
) -> tuple[dict[str, object], dict[str, BaseException], dict[str, str]]:
    """Runs two actions as real, concurrent threads synchronized on a
    `threading.Barrier` — the same idiom `test_concurrent_reviews_
    serialize_and_apply_exactly_once` established first — and returns
    whatever each captured: `results[label]` for a return value,
    `errors[label]`/`tracebacks[label]` for a raised exception. One
    bounded overall deadline covers both joins (never two independent
    30s waits that could sum to double the budget); both workers are
    ordinary non-daemon threads, and this function asserts neither is
    still alive before returning, so a genuinely stuck worker fails the
    calling test loudly and immediately rather than being silently
    abandoned for a later test's fixture teardown to trip over."""
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    errors: dict[str, BaseException] = {}
    tracebacks: dict[str, str] = {}

    def _run(label: str, action: Callable[[], object]) -> None:
        barrier.wait(timeout=_CONCURRENT_RACE_DEADLINE_SECONDS)
        try:
            results[label] = action()
        except BaseException as exc:  # noqa: BLE001 - captured for the caller's own assertions
            errors[label] = exc
            tracebacks[label] = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )

    thread_a = threading.Thread(target=_run, args=(label_a, action_a))
    thread_b = threading.Thread(target=_run, args=(label_b, action_b))
    thread_a.start()
    thread_b.start()

    deadline = time.monotonic() + _CONCURRENT_RACE_DEADLINE_SECONDS
    thread_a.join(timeout=max(0.0, deadline - time.monotonic()))
    thread_b.join(timeout=max(0.0, deadline - time.monotonic()))

    assert not thread_a.is_alive(), (
        f"the {label_a!r} worker is still running after "
        f"{_CONCURRENT_RACE_DEADLINE_SECONDS}s — likely blocked or deadlocked, not merely slow"
    )
    assert not thread_b.is_alive(), (
        f"the {label_b!r} worker is still running after "
        f"{_CONCURRENT_RACE_DEADLINE_SECONDS}s — likely blocked or deadlocked, not merely slow"
    )
    return results, errors, tracebacks


def _approve(
    postgres_engine: Engine, *, proposal_id: uuid.UUID, committed: Fixture
) -> tuple[Callable[[], ReviewProposedChangeResult], uuid.UUID]:
    """Creates a reviewer and returns (a zero-argument approve callable
    suitable for `_run_concurrent_race`, that reviewer's user_id — the
    caller owns deleting it in its own cleanup)."""
    with postgres_engine.begin() as connection:
        reviewer_user_id = make_user(connection, "Reviewer")

    def _do() -> ReviewProposedChangeResult:
        return review_proposed_change(
            postgres_engine,
            ai_proposed_change_id=proposal_id,
            campaign_id=committed.campaign_id,
            reviewer_user_id=reviewer_user_id,
            decision="approve",
        )

    return _do, reviewer_user_id


def test_a_concurrent_visibility_change_during_approval_is_always_safe(
    postgres_engine: Engine, committed: Fixture
) -> None:
    """A real race, via `_run_concurrent_race`, between
    `review_proposed_change(approve)` and an independent direct UPDATE
    narrowing the objective's own `visibility_policy` to `gm_only`.
    Deliberately does not try to choreograph which side "wins": under
    PostgreSQL's own READ COMMITTED semantics, `_revalidate_advance_quest_
    objective`'s `FOR UPDATE OF qo` either observes the visibility change
    (if the writer's UPDATE committed first) or blocks until the writer's
    transaction ends and then observes it (if the writer started after) —
    there is no third, inconsistent outcome. This proves exactly that: no
    matter which side the database schedules first, the result is always
    one of two safe, mutually exclusive outcomes, never a partial or
    inconsistent one.

    An earlier version of this test tried to independently prove genuine
    lock contention by holding a manual SELECT ... FOR UPDATE on a second
    connection (built on SQLAlchemy Core's own `Connection.begin()`) and
    polling `pg_stat_activity` for a blocked backend before releasing it.
    That specific mechanism proved unreliable in this environment; a raw
    psycopg-based version of the same idea, used as a one-off manual
    verification before this session's locking changes were finalized
    (not shipped here), did correctly and repeatably show the intended
    blocking relationship. Rather than ship the unreliable mechanism, this
    test verifies the invariant that actually matters — the outcome is
    always safe — using the same barrier-based real-concurrency idiom
    already proven reliable by this file's own sibling tests."""
    proposal_id = _pending_advance_proposal_id(postgres_engine, committed)
    approve, reviewer_user_id = _approve(
        postgres_engine, proposal_id=proposal_id, committed=committed
    )

    def _narrow_visibility() -> None:
        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE narrative.quest_objectives SET visibility_policy = 'gm_only' "
                    "WHERE quest_objective_id = :objective"
                ),
                {"objective": committed.open_objective_id},
            )

    results, errors, tracebacks = _run_concurrent_race(
        "review", approve, "visibility", _narrow_visibility
    )
    assert "visibility" not in errors, f"the visibility UPDATE itself failed: {tracebacks}"

    objective_status = _objective_status(
        postgres_engine, timeline_id=committed.timeline_id, objective_id=committed.open_objective_id
    )
    if "review" in results:
        # The review won: it observed the objective still 'visible' and
        # applied cleanly, before (or concurrently-but-ordered-before) the
        # visibility narrowing committed.
        assert objective_status == "completed", (
            f"review reported success but the objective was not actually advanced: {results!r}"
        )
        with postgres_engine.connect() as verify:
            review_count = verify.execute(
                text("SELECT count(*) FROM ai.change_reviews WHERE ai_proposed_change_id = :id"),
                {"id": proposal_id},
            ).scalar()
            assert review_count == 1
    else:
        # The visibility change won: review's own revalidation observed
        # the now-gm_only objective and rejected the whole thing, cleanly.
        assert "review" in errors, "expected the review to fail, got neither result nor error"
        _assert_review_rolled_back_completely(
            postgres_engine, proposal_id=proposal_id, committed=committed
        )
        assert objective_status is None

    with postgres_engine.begin() as cleanup:
        cleanup.execute(
            text(
                "UPDATE narrative.quest_objectives SET visibility_policy = 'visible' "
                "WHERE quest_objective_id = :objective"
            ),
            {"objective": committed.open_objective_id},
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = :u"), {"u": reviewer_user_id}
        )


def test_a_concurrent_participant_removal_during_approval_is_always_safe(
    postgres_engine: Engine, committed: Fixture
) -> None:
    """The NPC's own `narrative.quest_participants` row is removed
    concurrently with approval. `_revalidate_advance_quest_objective` now
    locks that association row (`FOR UPDATE`) before trusting it, so the
    DELETE and the review's own check genuinely serialize: whichever
    commits first determines the (still safe) outcome for the other."""
    proposal_id = _pending_advance_proposal_id(postgres_engine, committed)
    approve, reviewer_user_id = _approve(
        postgres_engine, proposal_id=proposal_id, committed=committed
    )

    def _remove_participation() -> None:
        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM narrative.quest_participants "
                    "WHERE quest_id = :quest AND participant_entity_id = :npc"
                ),
                {"quest": committed.quest_id, "npc": committed.npc_id},
            )

    results, errors, tracebacks = _run_concurrent_race(
        "review", approve, "remove_participant", _remove_participation
    )
    assert "remove_participant" not in errors, (
        f"the participant removal itself failed: {tracebacks}"
    )

    objective_status = _objective_status(
        postgres_engine, timeline_id=committed.timeline_id, objective_id=committed.open_objective_id
    )
    with postgres_engine.connect() as verify:
        still_participates = verify.execute(
            text(
                "SELECT 1 FROM narrative.quest_participants "
                "WHERE quest_id = :quest AND participant_entity_id = :npc"
            ),
            {"quest": committed.quest_id, "npc": committed.npc_id},
        ).scalar()
    assert still_participates is None, "the participant removal must always end up committed"

    if "review" in results:
        assert objective_status == "completed", (
            f"review reported success but the objective was not actually advanced: {results!r}"
        )
        with postgres_engine.connect() as verify:
            review_count = verify.execute(
                text("SELECT count(*) FROM ai.change_reviews WHERE ai_proposed_change_id = :id"),
                {"id": proposal_id},
            ).scalar()
            assert review_count == 1
    else:
        assert "review" in errors, "expected the review to fail, got neither result nor error"
        _assert_review_rolled_back_completely(
            postgres_engine, proposal_id=proposal_id, committed=committed
        )
        assert objective_status is None

    with postgres_engine.begin() as cleanup:
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = :u"), {"u": reviewer_user_id}
        )


def test_a_concurrent_party_removal_during_approval_is_always_safe(
    postgres_engine: Engine, committed: Fixture
) -> None:
    """The party's `campaign.campaign_parties` association is removed
    concurrently with approval. `_revalidate_advance_quest_objective` now
    calls `_validate_campaign_party(..., lock=True)`, locking that
    association row before trusting it, so the DELETE and the review's
    own check genuinely serialize."""
    proposal_id = _pending_advance_proposal_id(postgres_engine, committed)
    approve, reviewer_user_id = _approve(
        postgres_engine, proposal_id=proposal_id, committed=committed
    )

    def _remove_party() -> None:
        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM campaign.campaign_parties "
                    "WHERE campaign_id = :campaign AND party_id = :party"
                ),
                {"campaign": committed.campaign_id, "party": committed.party_id},
            )

    results, errors, tracebacks = _run_concurrent_race(
        "review", approve, "remove_party", _remove_party
    )
    assert "remove_party" not in errors, f"the party removal itself failed: {tracebacks}"

    objective_status = _objective_status(
        postgres_engine, timeline_id=committed.timeline_id, objective_id=committed.open_objective_id
    )
    if "review" in results:
        assert objective_status == "completed", (
            f"review reported success but the objective was not actually advanced: {results!r}"
        )
        with postgres_engine.connect() as verify:
            review_count = verify.execute(
                text("SELECT count(*) FROM ai.change_reviews WHERE ai_proposed_change_id = :id"),
                {"id": proposal_id},
            ).scalar()
            assert review_count == 1
    else:
        assert "review" in errors, "expected the review to fail, got neither result nor error"
        _assert_review_rolled_back_completely(
            postgres_engine, proposal_id=proposal_id, committed=committed
        )
        assert objective_status is None

    with postgres_engine.begin() as cleanup:
        # The removal always ends up committed regardless of which side
        # won the race — restore it so committed's own teardown has
        # nothing unusual (a campaign/party pair that no longer
        # associates) to cascade through.
        cleanup.execute(
            text(
                "INSERT INTO campaign.campaign_parties (campaign_id, party_id) "
                "VALUES (:campaign, :party) ON CONFLICT DO NOTHING"
            ),
            {"campaign": committed.campaign_id, "party": committed.party_id},
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = :u"), {"u": reviewer_user_id}
        )


def test_a_concurrent_independent_advance_during_approval_is_always_safe(
    postgres_engine: Engine, committed: Fixture
) -> None:
    """The same objective is independently advanced to 'failed' (a real,
    unrelated `advance_objective()` call — a GM acting directly, not
    through this proposal) concurrently with the proposal's own approval
    targeting 'completed'. Both ultimately compete for `narrative.quest_
    objectives`'s row lock (`_lock_quest_objective`, taken by both
    `_revalidate_advance_quest_objective` and `_advance_objective_impl`
    itself) — exactly one side's status change may commit; the other,
    once unblocked, observes an already-terminal objective and fails
    (`_advance_objective_impl`'s own terminal guard for a direct call, or
    `_revalidate_advance_quest_objective`'s `get_quest_view` recheck for
    the proposal side)."""
    proposal_id = _pending_advance_proposal_id(postgres_engine, committed)
    approve, reviewer_user_id = _approve(
        postgres_engine, proposal_id=proposal_id, committed=committed
    )

    def _independent_fail() -> None:
        advance_objective(
            postgres_engine,
            quest_objective_id=committed.open_objective_id,
            timeline_id=committed.timeline_id,
            world_time_id=committed.world_time_id,
            new_status_code="failed",
            party_id=committed.party_id,
            campaign_id=committed.campaign_id,
        )

    results, errors, tracebacks = _run_concurrent_race(
        "review", approve, "independent_fail", _independent_fail
    )

    objective_status = _objective_status(
        postgres_engine, timeline_id=committed.timeline_id, objective_id=committed.open_objective_id
    )
    review_won = "review" in results
    independent_won = "independent_fail" in results
    assert review_won != independent_won, (
        f"expected exactly one side to succeed, got results={results!r} errors={tracebacks!r}"
    )

    if review_won:
        assert objective_status == "completed"
        assert "independent_fail" in errors, (
            f"the independent advance should have observed an already-terminal objective: "
            f"{tracebacks}"
        )
        with postgres_engine.connect() as verify:
            review_count = verify.execute(
                text("SELECT count(*) FROM ai.change_reviews WHERE ai_proposed_change_id = :id"),
                {"id": proposal_id},
            ).scalar()
            assert review_count == 1
    else:
        # The independent, unrelated advance() won: the objective is
        # legitimately 'failed' (that call's own doing, nothing to do
        # with this proposal), and review must have observed that
        # already-terminal state and failed cleanly. Deliberately does
        # NOT call _assert_review_rolled_back_completely here — that
        # helper additionally asserts the objective's own status is
        # still None, which is correct for every *other* revalidation-
        # failure scenario in this file (nothing else touches the
        # objective's status when review fails) but wrong here, where a
        # *different*, legitimate winner is exactly why review failed.
        assert objective_status == "failed"
        assert "review" in errors, f"the review should have failed: {tracebacks}"
        with postgres_engine.connect() as verify:
            status = verify.execute(
                text("SELECT status FROM ai.proposed_changes WHERE ai_proposed_change_id = :id"),
                {"id": proposal_id},
            ).scalar()
            assert status == "pending"
            review_count = verify.execute(
                text("SELECT count(*) FROM ai.change_reviews WHERE ai_proposed_change_id = :id"),
                {"id": proposal_id},
            ).scalar()
            assert review_count == 0

    with postgres_engine.begin() as cleanup:
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = :u"), {"u": reviewer_user_id}
        )


def test_campaign_pinned_timeline_is_immutable_so_no_concurrent_change_race_exists(
    postgres_engine: Engine, committed: Fixture
) -> None:
    """A concurrent "campaign pinned-timeline change" race (requested
    alongside the other revalidation races) has no counterpart to test:
    `campaign.campaigns.timeline_id` is protected by `tr_campaigns_
    enforce_immutable` (revision 030_parent_scope_immutability) — no
    UPDATE can ever change it, concurrent or otherwise. This test proves
    that premise directly, so the absence of a race test for this case is
    a verified fact rather than an unstated assumption. `_revalidate_
    advance_quest_objective` still locks and rechecks this row (see its
    own docstring) as defense in depth in case that trigger is ever
    relaxed, but no test can race against a mutation the database itself
    refuses to perform."""
    with postgres_engine.begin() as connection:
        other_timeline_id = make_timeline(connection, committed.world_id, "Other Timeline")

    with (
        pytest.raises(IntegrityError, match="immutable"),
        postgres_engine.begin() as connection,
    ):
        connection.execute(
            text("UPDATE campaign.campaigns SET timeline_id = :t WHERE campaign_id = :c"),
            {"t": other_timeline_id, "c": committed.campaign_id},
        )

    with postgres_engine.begin() as cleanup:
        cleanup.execute(
            text("DELETE FROM campaign.timelines WHERE timeline_id = :t"), {"t": other_timeline_id}
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


_CONCURRENT_REVIEW_DEADLINE_SECONDS = 60


def test_concurrent_reviews_serialize_and_apply_exactly_once(
    postgres_engine: Engine, committed: Fixture
) -> None:
    """Two reviewers racing to decide the same pending proposal must
    serialize on _lock_pending_proposal's own SELECT ... FOR UPDATE —
    exactly one succeeds, the other observes a no-longer-pending proposal,
    and the objective is advanced exactly once (never duplicated).

    Both workers share one bounded overall deadline (not two independent
    30s joins, which could sum to double the wait before this test itself
    gives up) and are ordinary, non-daemon threads: a worker that is
    genuinely still blocked when the deadline expires must fail this test
    loudly, not be silently abandoned running in the background where a
    later test's own fixture teardown could be the first thing to notice
    it (still holding a lock) — daemon threads would hide exactly that
    failure mode instead of surfacing it."""
    with postgres_engine.begin() as connection:
        reviewer_a = make_user(connection, "Reviewer A")
        reviewer_b = make_user(connection, "Reviewer B")
    proposal_id = _pending_advance_proposal(postgres_engine, committed)

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    errors: dict[str, BaseException] = {}
    tracebacks: dict[str, str] = {}

    def _review(label: str, reviewer_user_id: uuid.UUID) -> None:
        barrier.wait(timeout=_CONCURRENT_REVIEW_DEADLINE_SECONDS)
        try:
            results[label] = review_proposed_change(
                postgres_engine,
                ai_proposed_change_id=proposal_id,
                campaign_id=committed.campaign_id,
                reviewer_user_id=reviewer_user_id,
                decision="approve",
            )
        except BaseException as exc:  # noqa: BLE001 - captured for the assertion below
            errors[label] = exc
            tracebacks[label] = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )

    thread_a = threading.Thread(target=_review, args=("a", reviewer_a))
    thread_b = threading.Thread(target=_review, args=("b", reviewer_b))
    thread_a.start()
    thread_b.start()

    deadline = time.monotonic() + _CONCURRENT_REVIEW_DEADLINE_SECONDS
    thread_a.join(timeout=max(0.0, deadline - time.monotonic()))
    thread_b.join(timeout=max(0.0, deadline - time.monotonic()))

    assert not thread_a.is_alive(), (
        f"reviewer a is still running after {_CONCURRENT_REVIEW_DEADLINE_SECONDS}s "
        "— likely blocked or deadlocked, not merely slow"
    )
    assert not thread_b.is_alive(), (
        f"reviewer b is still running after {_CONCURRENT_REVIEW_DEADLINE_SECONDS}s "
        "— likely blocked or deadlocked, not merely slow"
    )

    assert len(results) == 1, (
        f"expected exactly one success, got results={results!r} errors={errors!r} "
        f"tracebacks={tracebacks!r}"
    )
    assert len(errors) == 1, f"expected exactly one failure, got {tracebacks!r}"
    (failed_label,) = errors
    assert isinstance(errors[failed_label], ProposedChangeNotPendingError), tracebacks[failed_label]

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
