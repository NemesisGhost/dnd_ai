"""campaign.party_knowledge (revision 074) — the party's own current
effective belief about a knowledge item, distinct from knowledge.
party_discoveries (an acquisition record with no belief columns of its
own). See tests/database/test_party_knowledge_divergence.py for the
Phase 7 exit-criterion proof; this file covers the table's constraints.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_event,
    make_knowledge_item,
    make_knowledge_version,
    make_party,
    make_party_knowledge,
    make_timeline,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        self.party_id = make_party(connection, self.world_id)
        self.knowledge_item_id = make_knowledge_item(connection, self.world_id)


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "party-knowledge-world")


def test_a_party_can_record_belief_in_a_knowledge_item(
    db_connection: Connection, f: Fixture
) -> None:
    make_party_knowledge(db_connection, f.timeline_id, f.party_id, f.knowledge_item_id)


def test_only_one_current_belief_per_timeline_party_and_item(
    db_connection: Connection, f: Fixture
) -> None:
    make_party_knowledge(db_connection, f.timeline_id, f.party_id, f.knowledge_item_id)
    with pytest.raises(IntegrityError):
        make_party_knowledge(db_connection, f.timeline_id, f.party_id, f.knowledge_item_id)


def test_party_knowledge_requires_a_valid_awareness_level(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("""
                INSERT INTO campaign.party_knowledge
                    (timeline_id, party_id, knowledge_item_id, awareness_level)
                VALUES (:tl, :party, :item, 'certain')
            """),
            {"tl": f.timeline_id, "party": f.party_id, "item": f.knowledge_item_id},
        )
    assert "ck_party_knowledge_awareness_level" in str(exc.value)


def test_party_knowledge_party_must_share_its_world(db_connection: Connection, f: Fixture) -> None:
    other_world = make_world(db_connection, slug="party-knowledge-other-world")
    foreign_party = make_party(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_party_knowledge(db_connection, f.timeline_id, foreign_party, f.knowledge_item_id)
    assert "mixes worlds" in str(exc.value)


def test_party_knowledge_item_must_share_its_world(db_connection: Connection, f: Fixture) -> None:
    other_world = make_world(db_connection, slug="party-knowledge-item-other-world")
    foreign_item = make_knowledge_item(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_party_knowledge(db_connection, f.timeline_id, f.party_id, foreign_item)
    assert "mixes worlds" in str(exc.value)


def test_party_knowledge_can_cite_a_version_of_its_own_item(
    db_connection: Connection, f: Fixture
) -> None:
    version_id = make_knowledge_version(db_connection, f.knowledge_item_id)
    make_party_knowledge(
        db_connection,
        f.timeline_id,
        f.party_id,
        f.knowledge_item_id,
        knowledge_version_id=version_id,
    )


def test_party_knowledge_cannot_cite_a_version_of_a_different_item(
    db_connection: Connection, f: Fixture
) -> None:
    other_item_id = make_knowledge_item(db_connection, f.world_id, statement="A different claim.")
    version_of_other_item = make_knowledge_version(db_connection, other_item_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_party_knowledge(
            db_connection,
            f.timeline_id,
            f.party_id,
            f.knowledge_item_id,
            knowledge_version_id=version_of_other_item,
        )
    assert "belongs to knowledge item" in str(exc.value)


def test_party_knowledge_last_event_must_share_its_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    other_timeline = make_timeline(db_connection, f.world_id)
    other_world_time = make_world_time(db_connection, f.world_id, 200)
    foreign_event = make_event(db_connection, f.world_id, other_timeline, other_world_time)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_party_knowledge(
            db_connection,
            f.timeline_id,
            f.party_id,
            f.knowledge_item_id,
            last_event_id=foreign_event,
        )
    assert "same timeline" in str(exc.value)
