"""dnd_ai.domain.context_assembly, dnd_ai.commands.ai_npc, and
dnd_ai.commands.ai_proposals — Phase 12's NPC-portrayal use case and the
Generated -> Proposed -> Validated -> Approved -> Applied proposal
lifecycle (docs/PLAN.md Phase 12, docs/ENTITY_LIFECYCLE.md §10).

Context assembly is tested against the rollback-wrapped `db_connection`
fixture; the full proposal pipeline (`request_npc_conversation_turn`/
`review_proposed_change`) is engine-based and multi-transaction (see
`dnd_ai.commands.ai_npc`'s own docstring for why), so those tests use the
real, session-scoped `postgres_engine` with explicit cleanup — the same
shape `tests/database/test_api_integration.py` already established for
engine-based commands.
"""

import json
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.ai_npc import request_npc_conversation_turn
from dnd_ai.commands.ai_proposals import review_proposed_change
from dnd_ai.domain.ai_provider import FakeAiProvider
from dnd_ai.domain.context_assembly import assemble_npc_conversation_context
from tests.factories import (
    make_agent,
    make_agent_assignment,
    make_campaign,
    make_campaign_party,
    make_character,
    make_knowledge_item,
    make_party,
    make_party_knowledge,
    make_party_membership,
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
        # 'pending', not the default 'active': the committed fixture below
        # commits for real, and an active campaign must retain a qualifying
        # access.manage membership at commit time (DATABASE_MODEL.md §22
        # rule 19) — this fixture sets up no such membership, and nothing
        # under test needs campaign lifecycle status to be 'active'.
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

        # A fact about the NPC the party does not yet know — the candidate
        # `reveal_knowledge` can propose.
        self.secret_id = make_knowledge_item(
            connection,
            self.world_id,
            statement="The innkeeper is secretly a retired adventurer.",
            subject_entity_id=self.npc_id,
        )
        # A fact the party already knows — must never be re-offered.
        self.known_id = make_knowledge_item(
            connection,
            self.world_id,
            statement="The innkeeper runs the local inn.",
            subject_entity_id=self.npc_id,
        )
        make_party_knowledge(connection, self.timeline_id, self.party_id, self.known_id)


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, f"ai-npc-{uuid.uuid4().hex[:8]}")


def test_context_assembly_offers_only_unknown_facts(db_connection: Connection, f: Fixture) -> None:
    context = assemble_npc_conversation_context(
        db_connection,
        npc_entity_id=f.npc_id,
        timeline_id=f.timeline_id,
        expected_world_id=f.world_id,
        requesting_character_id=f.pc_id,
        requesting_party_id=f.party_id,
    )

    revealable_ids = {k.knowledge_item_id for k in context.revealable_knowledge}
    assert revealable_ids == {f.secret_id}
    assert "runs the local inn" in " ".join(context.known_facts_about_npc)


def test_context_payload_is_json_serializable(db_connection: Connection, f: Fixture) -> None:
    context = assemble_npc_conversation_context(
        db_connection,
        npc_entity_id=f.npc_id,
        timeline_id=f.timeline_id,
        expected_world_id=f.world_id,
        requesting_character_id=f.pc_id,
        requesting_party_id=f.party_id,
    )
    json.dumps(context.as_prompt_payload())  # must not raise


@pytest.fixture
def committed(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"ai-npc-commit-{uuid.uuid4().hex[:8]}")
        fixture.agent_id = make_agent(connection)
        fixture.assignment_id = make_agent_assignment(
            connection, fixture.agent_id, fixture.campaign_id, fixture.npc_id
        )
    yield fixture
    with postgres_engine.begin() as cleanup:
        # core.entities.world_id is ON DELETE RESTRICT (not CASCADE) — every
        # entity this fixture created must go before the world itself can.
        # session_replication_role = replica suppresses core.enforce_entity_
        # subtype() (and similar triggers) for this bulk delete, the same
        # shape tests/database/test_api_integration.py's own fixture
        # cleanup already established — a single-statement DELETE across
        # many CTI subtype rows otherwise fires that trigger mid-cascade,
        # before every sibling row is gone.
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(text("DELETE FROM ai.agents WHERE agent_id = :a"), {"a": fixture.agent_id})


def test_public_reveal_is_auto_approved_and_applied(
    postgres_engine: Engine, committed: Fixture
) -> None:
    result = request_npc_conversation_turn(
        postgres_engine,
        agent_assignment_id=committed.assignment_id,
        requesting_user_id=None,
        requesting_character_id=committed.pc_id,
        requesting_party_id=committed.party_id,
        player_message="Tell me something about yourself.",
        provider=FakeAiProvider(
            dialogue="I used to be an adventurer.", reveal_first_candidate=True
        ),
        timeline_id=committed.timeline_id,
        expected_world_id=committed.world_id,
        world_time_id=committed.world_time_id,
    )

    assert result.dialogue == "I used to be an adventurer."
    assert result.ai_proposed_change_id is not None
    assert result.proposal_status == "applied"
    assert result.applied_event_id is not None

    with postgres_engine.connect() as verify:
        aware = verify.execute(
            text("""
                SELECT count(*) FROM campaign.party_knowledge
                WHERE timeline_id = :t AND party_id = :p AND knowledge_item_id = :k
            """),
            {"t": committed.timeline_id, "p": committed.party_id, "k": committed.secret_id},
        ).scalar()
        assert aware == 1


def test_secret_reveal_requires_approval_and_review_applies_it(
    postgres_engine: Engine, committed: Fixture
) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE knowledge.knowledge_items SET sensitivity = 'secret' "
                "WHERE knowledge_item_id = :k"
            ),
            {"k": committed.secret_id},
        )
        reviewer_user_id = make_user(connection, "Reviewer")

    result = request_npc_conversation_turn(
        postgres_engine,
        agent_assignment_id=committed.assignment_id,
        requesting_user_id=None,
        requesting_character_id=committed.pc_id,
        requesting_party_id=committed.party_id,
        player_message="Tell me a secret.",
        provider=FakeAiProvider(dialogue="Perhaps another time.", reveal_first_candidate=True),
        timeline_id=committed.timeline_id,
        expected_world_id=committed.world_id,
        world_time_id=committed.world_time_id,
    )

    assert result.proposal_status == "pending"
    assert result.applied_event_id is None
    assert result.ai_proposed_change_id is not None

    with postgres_engine.connect() as verify:
        aware = verify.execute(
            text("""
                SELECT count(*) FROM campaign.party_knowledge
                WHERE timeline_id = :t AND party_id = :p AND knowledge_item_id = :k
            """),
            {"t": committed.timeline_id, "p": committed.party_id, "k": committed.secret_id},
        ).scalar()
        assert aware == 0

    review = review_proposed_change(
        postgres_engine,
        ai_proposed_change_id=result.ai_proposed_change_id,
        reviewer_user_id=reviewer_user_id,
        decision="approve",
    )
    assert review.status == "applied"
    assert review.applied_event_id is not None

    with postgres_engine.connect() as verify:
        aware = verify.execute(
            text("""
                SELECT count(*) FROM campaign.party_knowledge
                WHERE timeline_id = :t AND party_id = :p AND knowledge_item_id = :k
            """),
            {"t": committed.timeline_id, "p": committed.party_id, "k": committed.secret_id},
        ).scalar()
        assert aware == 1

    with postgres_engine.begin() as cleanup:
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = :u"), {"u": reviewer_user_id}
        )


def test_rejecting_a_proposal_leaves_canonical_state_unchanged(
    postgres_engine: Engine, committed: Fixture
) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE knowledge.knowledge_items SET sensitivity = 'secret' WHERE knowledge_item_id = :k"
            ),
            {"k": committed.secret_id},
        )
        reviewer_user_id = make_user(connection, "Reviewer")

    result = request_npc_conversation_turn(
        postgres_engine,
        agent_assignment_id=committed.assignment_id,
        requesting_user_id=None,
        requesting_character_id=committed.pc_id,
        requesting_party_id=committed.party_id,
        player_message="Tell me a secret.",
        provider=FakeAiProvider(dialogue="Perhaps another time.", reveal_first_candidate=True),
        timeline_id=committed.timeline_id,
        expected_world_id=committed.world_id,
        world_time_id=committed.world_time_id,
    )
    assert result.ai_proposed_change_id is not None

    review = review_proposed_change(
        postgres_engine,
        ai_proposed_change_id=result.ai_proposed_change_id,
        reviewer_user_id=reviewer_user_id,
        decision="reject",
    )
    assert review.status == "rejected"
    assert review.applied_event_id is None

    with postgres_engine.connect() as verify:
        aware = verify.execute(
            text("""
                SELECT count(*) FROM campaign.party_knowledge
                WHERE timeline_id = :t AND party_id = :p AND knowledge_item_id = :k
            """),
            {"t": committed.timeline_id, "p": committed.party_id, "k": committed.secret_id},
        ).scalar()
        assert aware == 0
        status = verify.execute(
            text("SELECT status FROM ai.proposed_changes WHERE ai_proposed_change_id = :id"),
            {"id": result.ai_proposed_change_id},
        ).scalar()
        assert status == "rejected"

    with postgres_engine.begin() as cleanup:
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = :u"), {"u": reviewer_user_id}
        )
