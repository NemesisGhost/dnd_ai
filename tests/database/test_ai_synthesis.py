"""dnd_ai.domain.context_assembly.assemble_campaign_synthesis_context and
dnd_ai.commands.ai_synthesis.request_campaign_synthesis — the audience-aware
GM-brief/player-summary/observer-summary use case (docs/PLAN.md Phase 12).
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.ai_synthesis import request_campaign_synthesis
from dnd_ai.domain.ai_provider import FakeAiProvider
from dnd_ai.domain.context_assembly import (
    GM_BRIEF,
    OBSERVER_SUMMARY,
    PLAYER_SUMMARY,
    assemble_campaign_synthesis_context,
)
from tests.factories import (
    make_agent,
    make_agent_assignment,
    make_campaign,
    make_campaign_party,
    make_event,
    make_knowledge_item,
    make_party,
    make_party_knowledge,
    make_timeline,
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
        self.party_id = make_party(connection, self.world_id)
        make_campaign_party(connection, self.campaign_id, self.party_id)

        self.recorded_event_id = make_event(
            connection,
            self.world_id,
            self.timeline_id,
            self.world_time_id,
            campaign_id=self.campaign_id,
            event_status_code="recorded",
            name="The party defeated the bandits",
        )
        self.draft_event_id = make_event(
            connection,
            self.world_id,
            self.timeline_id,
            self.world_time_id,
            campaign_id=self.campaign_id,
            event_status_code="draft",
            name="GM-only: the bandit leader is actually a doppelganger",
        )

        self.secret_item_id = make_knowledge_item(
            connection, self.world_id, statement="The old mill is haunted."
        )
        make_party_knowledge(connection, self.timeline_id, self.party_id, self.secret_item_id)


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, f"synth-{uuid.uuid4().hex[:8]}")


def test_gm_brief_includes_draft_events(db_connection: Connection, f: Fixture) -> None:
    context = assemble_campaign_synthesis_context(
        db_connection, campaign_id=f.campaign_id, audience_tier=GM_BRIEF
    )
    joined = " ".join(context.recent_event_summaries)
    assert "bandits" in joined
    assert "doppelganger" in joined


def test_observer_summary_excludes_drafts_and_party_knowledge(
    db_connection: Connection, f: Fixture
) -> None:
    context = assemble_campaign_synthesis_context(
        db_connection,
        campaign_id=f.campaign_id,
        audience_tier=OBSERVER_SUMMARY,
        timeline_id=f.timeline_id,
        requesting_party_id=f.party_id,
    )
    joined = " ".join(context.recent_event_summaries)
    assert "bandits" in joined
    assert "doppelganger" not in joined
    assert context.party_known_facts == ()


def test_player_summary_excludes_drafts_but_includes_party_knowledge(
    db_connection: Connection, f: Fixture
) -> None:
    context = assemble_campaign_synthesis_context(
        db_connection,
        campaign_id=f.campaign_id,
        audience_tier=PLAYER_SUMMARY,
        timeline_id=f.timeline_id,
        requesting_party_id=f.party_id,
    )
    joined = " ".join(context.recent_event_summaries)
    assert "bandits" in joined
    assert "doppelganger" not in joined
    assert any("haunted" in fact for fact in context.party_known_facts)


@pytest.fixture
def committed(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"synth-commit-{uuid.uuid4().hex[:8]}")
        fixture.agent_id = make_agent(connection, agent_role_code="session_summarizer")
        fixture.assignment_id = make_agent_assignment(
            connection, fixture.agent_id, fixture.campaign_id, None
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


def test_request_campaign_synthesis_records_output(
    postgres_engine: Engine, committed: Fixture
) -> None:
    result = request_campaign_synthesis(
        postgres_engine,
        agent_assignment_id=committed.assignment_id,
        campaign_id=committed.campaign_id,
        audience_tier=OBSERVER_SUMMARY,
        requesting_user_id=None,
        question_text="What happened recently?",
        provider=FakeAiProvider(dialogue="The party fought bandits."),
    )

    assert result.answer is not None
    assert "The party fought bandits." in result.answer
    assert result.error_message is None

    with postgres_engine.connect() as verify:
        request_kind = verify.execute(
            text("SELECT request_kind FROM ai.context_requests WHERE context_request_id = :id"),
            {"id": result.context_request_id},
        ).scalar()
        assert request_kind == OBSERVER_SUMMARY

        output_count = verify.execute(
            text("SELECT count(*) FROM ai.generated_outputs WHERE generated_output_id = :id"),
            {"id": result.generated_output_id},
        ).scalar()
        assert output_count == 1
