"""Party knowledge differs from canonical truth (docs/PLAN.md Phase 7 exit
criterion). knowledge.knowledge_items.truth_status_id is the canonical
answer; knowledge.entity_knowledge/.party_discoveries record what a knower
or party actually believes, which may — and, per docs/DATABASE_CONVENTIONS.md
§15.2, must be allowed to — disagree. This was already representable since
Phase 5 (revision 041); this test is the first to prove the divergence
itself, and to exercise it alongside Phase 7's own additions
(knowledge_versions, information_transfers).
"""

import pytest
from sqlalchemy import Connection, text

from tests.factories import (
    make_character,
    make_knowledge_item,
    make_party,
    make_timeline,
    make_world,
)

pytestmark = pytest.mark.database


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.party_id = make_party(connection, self.world_id)
        # Canonical truth: the merchant is NOT the thief.
        self.knowledge_item_id = make_knowledge_item(
            connection,
            self.world_id,
            knowledge_type_code="secret",
            truth_status_code="false",
            statement="The merchant Delwyn stole the crown jewels.",
        )


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "party-knowledge-divergence-world")


def test_a_party_can_believe_a_claim_the_canonical_truth_contradicts(
    db_connection: Connection, f: Fixture
) -> None:
    """The knowledge item is canonically false, but the party fully believes
    it — a false belief is valid game data (conventions §15.2) and must not
    be silently corrected."""
    truth_status = db_connection.execute(
        text("""
            SELECT ts.code FROM knowledge.knowledge_items ki
            JOIN knowledge.truth_statuses ts ON ts.truth_status_id = ki.truth_status_id
            WHERE ki.knowledge_item_id = :i
        """),
        {"i": f.knowledge_item_id},
    ).scalar()
    assert truth_status == "false"

    npc_id = make_character(db_connection, f.world_id, entity_type_code="npc")
    db_connection.execute(
        text("""
            INSERT INTO knowledge.entity_knowledge
                (timeline_id, knowledge_item_id, knower_entity_id, awareness_level, confidence,
                 interpretation)
            VALUES (:tl, :item, :knower, 'aware', 95, 'Delwyn is definitely the thief.')
        """),
        {"tl": f.timeline_id, "item": f.knowledge_item_id, "knower": npc_id},
    )

    belief = db_connection.execute(
        text("""
            SELECT awareness_level, confidence, interpretation
            FROM knowledge.entity_knowledge
            WHERE timeline_id = :tl AND knowledge_item_id = :item AND knower_entity_id = :knower
        """),
        {"tl": f.timeline_id, "item": f.knowledge_item_id, "knower": npc_id},
    ).one()

    assert belief.awareness_level == "aware"
    assert belief.confidence == 95
    assert "definitely" in belief.interpretation
    # The party's belief is recorded independently of, and in direct
    # contradiction to, the item's own canonical truth_status ('false').


def test_a_transferred_rumor_can_distort_the_partys_belief_further(
    db_connection: Connection, f: Fixture
) -> None:
    """A source knower's own (already-false) belief can be distorted again
    on the way to a party member, via knowledge.information_transfers'
    modified_interpretation — this is what supports rumor propagation and
    misinformation (docs/DOMAIN_MODEL.md §15.6)."""
    source_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    recipient_npc = make_character(db_connection, f.world_id, entity_type_code="npc")

    source_entity_knowledge_id = db_connection.execute(
        text("""
            INSERT INTO knowledge.entity_knowledge
                (timeline_id, knowledge_item_id, knower_entity_id, interpretation)
            VALUES (:tl, :item, :knower, 'Delwyn might be involved.')
            RETURNING entity_knowledge_id
        """),
        {"tl": f.timeline_id, "item": f.knowledge_item_id, "knower": source_npc},
    ).scalar()

    db_connection.execute(
        text("""
            INSERT INTO knowledge.information_transfers
                (timeline_id, source_entity_knowledge_id, recipient_entity_id,
                 modified_interpretation, transfer_method)
            VALUES (:tl, :source, :recipient, 'Delwyn confessed to the theft himself!', 'rumor')
        """),
        {
            "tl": f.timeline_id,
            "source": source_entity_knowledge_id,
            "recipient": recipient_npc,
        },
    )

    transfer = db_connection.execute(
        text("""
            SELECT it.modified_interpretation, ek.interpretation AS source_interpretation
            FROM knowledge.information_transfers it
            JOIN knowledge.entity_knowledge ek
                ON ek.entity_knowledge_id = it.source_entity_knowledge_id
            WHERE it.source_entity_knowledge_id = :source
        """),
        {"source": source_entity_knowledge_id},
    ).one()

    assert transfer.modified_interpretation != transfer.source_interpretation
    assert "confessed" in transfer.modified_interpretation
    assert "might be involved" in transfer.source_interpretation


def test_a_party_discovery_can_disagree_with_canonical_truth_too(
    db_connection: Connection, f: Fixture
) -> None:
    db_connection.execute(
        text("""
            INSERT INTO knowledge.party_discoveries (timeline_id, knowledge_item_id, party_id)
            VALUES (:tl, :item, :party)
        """),
        {"tl": f.timeline_id, "item": f.knowledge_item_id, "party": f.party_id},
    )

    discovered = db_connection.execute(
        text("""
            SELECT 1 FROM knowledge.party_discoveries
            WHERE timeline_id = :tl AND knowledge_item_id = :item AND party_id = :party
        """),
        {"tl": f.timeline_id, "item": f.knowledge_item_id, "party": f.party_id},
    ).scalar()
    assert discovered == 1
    # The party has discovered (and, per the entity_knowledge test above, may
    # fully believe) a claim the world itself records as false.
