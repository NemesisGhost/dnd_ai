"""dnd_ai.commands.knowledge.reveal_knowledge_to_party — the one canonical
target command Phase 12's approved `reveal_knowledge` AI proposals invoke
(docs/PLAN.md Phase 12, docs/ENTITY_LIFECYCLE.md §10)."""

import uuid

import pytest
from sqlalchemy import Connection, text

from dnd_ai.commands.knowledge import KnowledgeItemNotFoundError, _reveal_knowledge_to_party_impl
from tests.factories import (
    make_campaign,
    make_campaign_party,
    make_knowledge_item,
    make_party,
    make_timeline,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        self.campaign_id = make_campaign(connection, self.timeline_id)
        self.party_id = make_party(connection, self.world_id)
        make_campaign_party(connection, self.campaign_id, self.party_id)
        self.knowledge_item_id = make_knowledge_item(connection, self.world_id)


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, f"reveal-{uuid.uuid4().hex[:8]}")


def test_reveal_creates_a_causal_event_and_party_belief(
    db_connection: Connection, f: Fixture
) -> None:
    result = _reveal_knowledge_to_party_impl(
        db_connection,
        knowledge_item_id=f.knowledge_item_id,
        party_id=f.party_id,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        campaign_id=f.campaign_id,
    )

    assert result.already_known is False
    assert result.event_id is not None

    event_type_code = db_connection.execute(
        text("""
            SELECT et.code FROM narrative.events e
            JOIN narrative.event_types et ON et.event_type_id = e.event_type_id
            WHERE e.event_id = :event
        """),
        {"event": result.event_id},
    ).scalar()
    assert event_type_code == "knowledge_revealed"

    awareness = db_connection.execute(
        text("""
            SELECT awareness_level FROM campaign.party_knowledge
            WHERE party_knowledge_id = :id
        """),
        {"id": result.party_knowledge_id},
    ).scalar()
    assert awareness == "aware"

    discovered = db_connection.execute(
        text("""
            SELECT count(*) FROM knowledge.party_discoveries
            WHERE timeline_id = :timeline AND party_id = :party AND knowledge_item_id = :item
        """),
        {"timeline": f.timeline_id, "party": f.party_id, "item": f.knowledge_item_id},
    ).scalar()
    assert discovered == 1

    effect_count = db_connection.execute(
        text("SELECT count(*) FROM narrative.event_effects WHERE event_id = :event"),
        {"event": result.event_id},
    ).scalar()
    assert effect_count == 2


def test_revealing_an_already_known_item_is_idempotent(
    db_connection: Connection, f: Fixture
) -> None:
    first = _reveal_knowledge_to_party_impl(
        db_connection,
        knowledge_item_id=f.knowledge_item_id,
        party_id=f.party_id,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        campaign_id=f.campaign_id,
    )
    second = _reveal_knowledge_to_party_impl(
        db_connection,
        knowledge_item_id=f.knowledge_item_id,
        party_id=f.party_id,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        campaign_id=f.campaign_id,
    )

    assert second.already_known is True
    assert second.event_id is None
    assert second.party_knowledge_id == first.party_knowledge_id

    event_count = db_connection.execute(
        text("SELECT count(*) FROM narrative.events WHERE timeline_id = :timeline"),
        {"timeline": f.timeline_id},
    ).scalar()
    assert event_count == 1


def test_revealing_a_nonexistent_knowledge_item_fails(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(KnowledgeItemNotFoundError):
        _reveal_knowledge_to_party_impl(
            db_connection,
            knowledge_item_id=uuid.uuid4(),
            party_id=f.party_id,
            timeline_id=f.timeline_id,
            world_time_id=f.world_time_id,
            campaign_id=f.campaign_id,
        )
