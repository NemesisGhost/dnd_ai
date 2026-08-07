"""Phase 7's knowledge-domain expansion (revision 073): temporal validity on
knowledge.knowledge_items, knowledge.knowledge_versions,
knowledge.entity_knowledge.knowledge_version_id, knowledge.character_expertise,
knowledge.information_transfers, and knowledge.public_knowledge.

docs/architecture/DATABASE_MODEL.md §15's "Explicit Phase 5 / Phase 7
boundary" note names exactly these five gaps; each gets at least one positive
and one negative test here, per docs/DATABASE_CONVENTIONS.md §32.1.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_character,
    make_event,
    make_interaction,
    make_knowledge_item,
    make_location,
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
        self.t100 = make_world_time(connection, self.world_id, 100)
        self.t200 = make_world_time(connection, self.world_id, 200)
        self.knowledge_item_id = make_knowledge_item(connection, self.world_id)


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "knowledge-expansion-world")


# ---------------------------------------------------------------------------
# knowledge.knowledge_items temporal validity
# ---------------------------------------------------------------------------


def test_a_knowledge_item_with_no_validity_window_is_unaffected(
    db_connection: Connection, f: Fixture
) -> None:
    row = db_connection.execute(
        text("SELECT validity_period FROM knowledge.knowledge_items WHERE knowledge_item_id = :i"),
        {"i": f.knowledge_item_id},
    ).one()
    assert row.validity_period is None


def test_an_open_ended_validity_window_derives_an_unbounded_upper_range(
    db_connection: Connection, f: Fixture
) -> None:
    db_connection.execute(
        text("""
            UPDATE knowledge.knowledge_items SET effective_from_world_time_id = :from
            WHERE knowledge_item_id = :i
        """),
        {"from": f.t100, "i": f.knowledge_item_id},
    )
    row = db_connection.execute(
        text("SELECT validity_period FROM knowledge.knowledge_items WHERE knowledge_item_id = :i"),
        {"i": f.knowledge_item_id},
    ).one()
    assert row.validity_period.lower == 100
    assert row.validity_period.upper is None


def test_a_closed_validity_window_derives_a_half_open_range(
    db_connection: Connection, f: Fixture
) -> None:
    db_connection.execute(
        text("""
            UPDATE knowledge.knowledge_items
            SET effective_from_world_time_id = :from, effective_to_world_time_id = :to
            WHERE knowledge_item_id = :i
        """),
        {"from": f.t100, "to": f.t200, "i": f.knowledge_item_id},
    )
    row = db_connection.execute(
        text("SELECT validity_period FROM knowledge.knowledge_items WHERE knowledge_item_id = :i"),
        {"i": f.knowledge_item_id},
    ).one()
    assert row.validity_period.lower == 100
    assert row.validity_period.upper == 200


def test_validity_end_must_be_finite_only_with_a_start(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("""
                UPDATE knowledge.knowledge_items SET effective_to_world_time_id = :to
                WHERE knowledge_item_id = :i
            """),
            {"to": f.t200, "i": f.knowledge_item_id},
        )
    assert "ck_knowledge_items_validity_requires_start" in str(exc.value)


def test_validity_end_must_be_strictly_after_start(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                UPDATE knowledge.knowledge_items
                SET effective_from_world_time_id = :from, effective_to_world_time_id = :to
                WHERE knowledge_item_id = :i
            """),
            {"from": f.t200, "to": f.t100, "i": f.knowledge_item_id},
        )
    assert "strictly after" in str(exc.value)


def test_validity_endpoints_must_share_the_items_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="knowledge-validity-other-world")
    foreign_time = make_world_time(db_connection, other_world, 100)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                UPDATE knowledge.knowledge_items SET effective_from_world_time_id = :from
                WHERE knowledge_item_id = :i
            """),
            {"from": foreign_time, "i": f.knowledge_item_id},
        )
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# knowledge.knowledge_versions / knowledge.entity_knowledge.knowledge_version_id
# ---------------------------------------------------------------------------


def _make_version(
    connection: Connection, knowledge_item_id, statement: str = "A distorted retelling."
):
    return connection.execute(
        text("""
            INSERT INTO knowledge.knowledge_versions (knowledge_item_id, version_statement)
            VALUES (:item, :statement)
            RETURNING knowledge_version_id
        """),
        {"item": knowledge_item_id, "statement": statement},
    ).scalar()


def test_a_knowledge_item_can_have_a_distorted_version(
    db_connection: Connection, f: Fixture
) -> None:
    version_id = _make_version(db_connection, f.knowledge_item_id)
    assert version_id is not None


def test_an_entity_knowledge_row_can_cite_a_version_of_its_own_item(
    db_connection: Connection, f: Fixture
) -> None:
    version_id = _make_version(db_connection, f.knowledge_item_id)
    npc_id = make_character(db_connection, f.world_id, entity_type_code="npc")
    db_connection.execute(
        text("""
            INSERT INTO knowledge.entity_knowledge
                (timeline_id, knowledge_item_id, knower_entity_id, knowledge_version_id)
            VALUES (:tl, :item, :knower, :version)
        """),
        {
            "tl": f.timeline_id,
            "item": f.knowledge_item_id,
            "knower": npc_id,
            "version": version_id,
        },
    )


def test_an_entity_knowledge_row_cannot_cite_a_version_of_a_different_item(
    db_connection: Connection, f: Fixture
) -> None:
    other_item_id = make_knowledge_item(db_connection, f.world_id, statement="A different claim.")
    version_of_other_item = _make_version(db_connection, other_item_id)
    npc_id = make_character(db_connection, f.world_id, entity_type_code="npc")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                INSERT INTO knowledge.entity_knowledge
                    (timeline_id, knowledge_item_id, knower_entity_id, knowledge_version_id)
                VALUES (:tl, :item, :knower, :version)
            """),
            {
                "tl": f.timeline_id,
                "item": f.knowledge_item_id,
                "knower": npc_id,
                "version": version_of_other_item,
            },
        )
    assert "belongs to knowledge item" in str(exc.value)


# ---------------------------------------------------------------------------
# knowledge.character_expertise
# ---------------------------------------------------------------------------


def test_a_character_can_have_expertise(db_connection: Connection, f: Fixture) -> None:
    character_id = make_character(db_connection, f.world_id)
    db_connection.execute(
        text("""
            INSERT INTO knowledge.character_expertise (character_id, expertise_domain_id)
            VALUES (
                :c, (SELECT expertise_domain_id FROM knowledge.expertise_domains WHERE code = 'arcana')
            )
        """),
        {"c": character_id},
    )


def test_a_character_cannot_have_the_same_expertise_domain_twice(
    db_connection: Connection, f: Fixture
) -> None:
    character_id = make_character(db_connection, f.world_id)
    stmt = text("""
        INSERT INTO knowledge.character_expertise (character_id, expertise_domain_id)
        VALUES (
            :c, (SELECT expertise_domain_id FROM knowledge.expertise_domains WHERE code = 'arcana')
        )
    """)
    db_connection.execute(stmt, {"c": character_id})
    with pytest.raises(IntegrityError):
        db_connection.execute(stmt, {"c": character_id})


# ---------------------------------------------------------------------------
# knowledge.information_transfers
# ---------------------------------------------------------------------------


def _make_entity_knowledge(connection: Connection, f: Fixture, knower_entity_id) -> object:
    return connection.execute(
        text("""
            INSERT INTO knowledge.entity_knowledge (timeline_id, knowledge_item_id, knower_entity_id)
            VALUES (:tl, :item, :knower)
            RETURNING entity_knowledge_id
        """),
        {"tl": f.timeline_id, "item": f.knowledge_item_id, "knower": knower_entity_id},
    ).scalar()


def test_information_can_transfer_between_two_knowers(
    db_connection: Connection, f: Fixture
) -> None:
    source_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    recipient_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    source_ek = _make_entity_knowledge(db_connection, f, source_npc)

    db_connection.execute(
        text("""
            INSERT INTO knowledge.information_transfers
                (timeline_id, source_entity_knowledge_id, recipient_entity_id,
                 modified_interpretation, transfer_method)
            VALUES (:tl, :source, :recipient, 'A wildly exaggerated version.', 'rumor')
        """),
        {"tl": f.timeline_id, "source": source_ek, "recipient": recipient_npc},
    )


def test_a_transfer_can_have_at_most_one_cause(db_connection: Connection, f: Fixture) -> None:
    source_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    recipient_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    source_ek = _make_entity_knowledge(db_connection, f, source_npc)
    event_id = make_event(db_connection, f.world_id, f.timeline_id, f.t100)
    interaction_id = make_interaction(db_connection, f.timeline_id, f.t100)

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("""
                INSERT INTO knowledge.information_transfers
                    (timeline_id, source_entity_knowledge_id, recipient_entity_id,
                     caused_by_event_id, caused_by_interaction_id)
                VALUES (:tl, :source, :recipient, :event, :interaction)
            """),
            {
                "tl": f.timeline_id,
                "source": source_ek,
                "recipient": recipient_npc,
                "event": event_id,
                "interaction": interaction_id,
            },
        )
    assert "ck_information_transfers_at_most_one_cause" in str(exc.value)


def test_a_transfer_must_share_its_world(db_connection: Connection, f: Fixture) -> None:
    source_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    source_ek = _make_entity_knowledge(db_connection, f, source_npc)

    other_world = make_world(db_connection, slug="transfer-other-world")
    foreign_npc = make_character(db_connection, other_world, entity_type_code="npc")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                INSERT INTO knowledge.information_transfers
                    (timeline_id, source_entity_knowledge_id, recipient_entity_id)
                VALUES (:tl, :source, :recipient)
            """),
            {"tl": f.timeline_id, "source": source_ek, "recipient": foreign_npc},
        )
    assert "mixes worlds" in str(exc.value)


# ---------------------------------------------------------------------------
# knowledge.public_knowledge
# ---------------------------------------------------------------------------


def test_knowledge_can_be_public_within_a_location(db_connection: Connection, f: Fixture) -> None:
    location_id = make_location(db_connection, f.world_id)
    db_connection.execute(
        text("""
            INSERT INTO knowledge.public_knowledge (timeline_id, knowledge_item_id, location_id)
            VALUES (:tl, :item, :location)
        """),
        {"tl": f.timeline_id, "item": f.knowledge_item_id, "location": location_id},
    )


def test_public_knowledge_is_unique_per_timeline_item_and_location(
    db_connection: Connection, f: Fixture
) -> None:
    location_id = make_location(db_connection, f.world_id)
    stmt = text("""
        INSERT INTO knowledge.public_knowledge (timeline_id, knowledge_item_id, location_id)
        VALUES (:tl, :item, :location)
    """)
    db_connection.execute(
        stmt, {"tl": f.timeline_id, "item": f.knowledge_item_id, "location": location_id}
    )
    with pytest.raises(IntegrityError):
        db_connection.execute(
            stmt, {"tl": f.timeline_id, "item": f.knowledge_item_id, "location": location_id}
        )


def test_public_knowledge_must_share_its_world(db_connection: Connection, f: Fixture) -> None:
    other_world = make_world(db_connection, slug="public-knowledge-other-world")
    foreign_location = make_location(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                INSERT INTO knowledge.public_knowledge (timeline_id, knowledge_item_id, location_id)
                VALUES (:tl, :item, :location)
            """),
            {"tl": f.timeline_id, "item": f.knowledge_item_id, "location": foreign_location},
        )
    assert "mixes worlds" in str(exc.value)


def test_public_knowledge_known_since_can_be_set(db_connection: Connection, f: Fixture) -> None:
    location_id = make_location(db_connection, f.world_id)
    db_connection.execute(
        text("""
            INSERT INTO knowledge.public_knowledge
                (timeline_id, knowledge_item_id, location_id, known_since_world_time_id)
            VALUES (:tl, :item, :location, :known_since)
        """),
        {
            "tl": f.timeline_id,
            "item": f.knowledge_item_id,
            "location": location_id,
            "known_since": f.t100,
        },
    )


def test_public_knowledge_known_since_must_share_the_timelines_world(
    db_connection: Connection, f: Fixture
) -> None:
    location_id = make_location(db_connection, f.world_id)
    other_world = make_world(db_connection, slug="public-knowledge-known-since-other-world")
    foreign_world_time = make_world_time(db_connection, other_world, 100)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                INSERT INTO knowledge.public_knowledge
                    (timeline_id, knowledge_item_id, location_id, known_since_world_time_id)
                VALUES (:tl, :item, :location, :known_since)
            """),
            {
                "tl": f.timeline_id,
                "item": f.knowledge_item_id,
                "location": location_id,
                "known_since": foreign_world_time,
            },
        )
    assert "known_since_world_time_id" in str(exc.value)


# ---------------------------------------------------------------------------
# knowledge.information_transfers: timeline-scope guards (revision 074)
# ---------------------------------------------------------------------------


def test_a_transfers_source_must_share_its_own_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    """The source entity_knowledge row shares the transfer's *world* (an
    existing check) but belongs to a *different* timeline within it —
    revision 074's addition, not caught by the world-only check."""
    other_timeline = make_timeline(db_connection, f.world_id)
    source_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    recipient_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    source_ek = db_connection.execute(
        text("""
            INSERT INTO knowledge.entity_knowledge (timeline_id, knowledge_item_id, knower_entity_id)
            VALUES (:tl, :item, :knower)
            RETURNING entity_knowledge_id
        """),
        {"tl": other_timeline, "item": f.knowledge_item_id, "knower": source_npc},
    ).scalar()

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                INSERT INTO knowledge.information_transfers
                    (timeline_id, source_entity_knowledge_id, recipient_entity_id)
                VALUES (:tl, :source, :recipient)
            """),
            {"tl": f.timeline_id, "source": source_ek, "recipient": recipient_npc},
        )
    assert "source_entity_knowledge_id" in str(exc.value)
    assert "belongs to timeline" in str(exc.value)


def test_a_transfers_caused_by_interaction_must_share_its_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    other_timeline = make_timeline(db_connection, f.world_id)
    source_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    recipient_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    source_ek = _make_entity_knowledge(db_connection, f, source_npc)
    foreign_interaction = make_interaction(db_connection, other_timeline, f.t100)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                INSERT INTO knowledge.information_transfers
                    (timeline_id, source_entity_knowledge_id, recipient_entity_id,
                     caused_by_interaction_id)
                VALUES (:tl, :source, :recipient, :interaction)
            """),
            {
                "tl": f.timeline_id,
                "source": source_ek,
                "recipient": recipient_npc,
                "interaction": foreign_interaction,
            },
        )
    assert "caused_by_interaction_id" in str(exc.value)
    assert "belongs to timeline" in str(exc.value)


def test_a_transfers_caused_by_event_must_share_its_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    other_timeline = make_timeline(db_connection, f.world_id)
    other_world_time = make_world_time(db_connection, f.world_id, 300)
    source_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    recipient_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    source_ek = _make_entity_knowledge(db_connection, f, source_npc)
    foreign_event = make_event(db_connection, f.world_id, other_timeline, other_world_time)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                INSERT INTO knowledge.information_transfers
                    (timeline_id, source_entity_knowledge_id, recipient_entity_id,
                     caused_by_event_id)
                VALUES (:tl, :source, :recipient, :event)
            """),
            {
                "tl": f.timeline_id,
                "source": source_ek,
                "recipient": recipient_npc,
                "event": foreign_event,
            },
        )
    assert "caused_by_event_id" in str(exc.value)
    assert "belongs to timeline" in str(exc.value)


def test_a_transfers_occurred_at_world_time_must_share_the_timelines_world(
    db_connection: Connection, f: Fixture
) -> None:
    source_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    recipient_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    source_ek = _make_entity_knowledge(db_connection, f, source_npc)

    other_world = make_world(db_connection, slug="transfer-occurred-at-other-world")
    foreign_world_time = make_world_time(db_connection, other_world, 100)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                INSERT INTO knowledge.information_transfers
                    (timeline_id, source_entity_knowledge_id, recipient_entity_id,
                     occurred_at_world_time_id)
                VALUES (:tl, :source, :recipient, :world_time)
            """),
            {
                "tl": f.timeline_id,
                "source": source_ek,
                "recipient": recipient_npc,
                "world_time": foreign_world_time,
            },
        )
    assert "occurred_at_world_time_id" in str(exc.value)


def test_a_transfers_existing_source_and_recipient_world_checks_still_work(
    db_connection: Connection, f: Fixture
) -> None:
    """Regression guard: revision 074 rewrote this function's body — the
    original world-agreement behaviour must survive unchanged."""
    source_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    source_ek = _make_entity_knowledge(db_connection, f, source_npc)

    other_world = make_world(db_connection, slug="transfer-recipient-other-world")
    foreign_recipient = make_character(db_connection, other_world, entity_type_code="npc")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                INSERT INTO knowledge.information_transfers
                    (timeline_id, source_entity_knowledge_id, recipient_entity_id)
                VALUES (:tl, :source, :recipient)
            """),
            {"tl": f.timeline_id, "source": source_ek, "recipient": foreign_recipient},
        )
    assert "mixes worlds" in str(exc.value)


def test_a_transfers_caused_by_interaction_on_its_own_timeline_is_accepted(
    db_connection: Connection, f: Fixture
) -> None:
    source_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    recipient_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    source_ek = _make_entity_knowledge(db_connection, f, source_npc)
    interaction_id = make_interaction(db_connection, f.timeline_id, f.t100)

    transfer_id = db_connection.execute(
        text("""
            INSERT INTO knowledge.information_transfers
                (timeline_id, source_entity_knowledge_id, recipient_entity_id,
                 caused_by_interaction_id)
            VALUES (:tl, :source, :recipient, :interaction)
            RETURNING information_transfer_id
        """),
        {
            "tl": f.timeline_id,
            "source": source_ek,
            "recipient": recipient_npc,
            "interaction": interaction_id,
        },
    ).scalar()

    row = db_connection.execute(
        text(
            "SELECT caused_by_interaction_id FROM knowledge.information_transfers "
            "WHERE information_transfer_id = :t"
        ),
        {"t": transfer_id},
    ).one()
    assert row.caused_by_interaction_id == interaction_id


def test_a_transfers_caused_by_event_on_its_own_timeline_is_accepted(
    db_connection: Connection, f: Fixture
) -> None:
    source_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    recipient_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    source_ek = _make_entity_knowledge(db_connection, f, source_npc)
    event_id = make_event(db_connection, f.world_id, f.timeline_id, f.t100)

    transfer_id = db_connection.execute(
        text("""
            INSERT INTO knowledge.information_transfers
                (timeline_id, source_entity_knowledge_id, recipient_entity_id,
                 caused_by_event_id)
            VALUES (:tl, :source, :recipient, :event)
            RETURNING information_transfer_id
        """),
        {
            "tl": f.timeline_id,
            "source": source_ek,
            "recipient": recipient_npc,
            "event": event_id,
        },
    ).scalar()

    row = db_connection.execute(
        text(
            "SELECT caused_by_event_id FROM knowledge.information_transfers "
            "WHERE information_transfer_id = :t"
        ),
        {"t": transfer_id},
    ).one()
    assert row.caused_by_event_id == event_id


def test_a_transfers_occurred_at_world_time_in_the_timelines_world_is_accepted(
    db_connection: Connection, f: Fixture
) -> None:
    source_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    recipient_npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    source_ek = _make_entity_knowledge(db_connection, f, source_npc)

    transfer_id = db_connection.execute(
        text("""
            INSERT INTO knowledge.information_transfers
                (timeline_id, source_entity_knowledge_id, recipient_entity_id,
                 occurred_at_world_time_id)
            VALUES (:tl, :source, :recipient, :world_time)
            RETURNING information_transfer_id
        """),
        {
            "tl": f.timeline_id,
            "source": source_ek,
            "recipient": recipient_npc,
            "world_time": f.t100,
        },
    ).scalar()

    row = db_connection.execute(
        text(
            "SELECT occurred_at_world_time_id FROM knowledge.information_transfers "
            "WHERE information_transfer_id = :t"
        ),
        {"t": transfer_id},
    ).one()
    assert row.occurred_at_world_time_id == f.t100


# ---------------------------------------------------------------------------
# knowledge.knowledge_versions: append-only enforcement (revision 074)
# ---------------------------------------------------------------------------


def test_a_knowledge_version_cannot_be_rewritten(db_connection: Connection, f: Fixture) -> None:
    version_id = _make_version(db_connection, f.knowledge_item_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE knowledge.knowledge_versions SET version_statement = 'Edited.' "
                "WHERE knowledge_version_id = :v"
            ),
            {"v": version_id},
        )
    assert "append-only" in str(exc.value)


def test_a_knowledge_version_cannot_be_reparented(db_connection: Connection, f: Fixture) -> None:
    other_item_id = make_knowledge_item(db_connection, f.world_id, statement="A different claim.")
    version_id = _make_version(db_connection, f.knowledge_item_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE knowledge.knowledge_versions SET knowledge_item_id = :other "
                "WHERE knowledge_version_id = :v"
            ),
            {"other": other_item_id, "v": version_id},
        )
    assert "append-only" in str(exc.value)


def test_a_knowledge_version_cannot_be_deleted(db_connection: Connection, f: Fixture) -> None:
    version_id = _make_version(db_connection, f.knowledge_item_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("DELETE FROM knowledge.knowledge_versions WHERE knowledge_version_id = :v"),
            {"v": version_id},
        )
    assert "append-only" in str(exc.value)


def test_a_referenced_knowledge_versions_item_invariant_cannot_be_invalidated(
    db_connection: Connection, f: Fixture
) -> None:
    """An entity_knowledge row cites a version of its own item
    (enforce_entity_knowledge_version_item's invariant). Reparenting that
    version out from under it — the only way the invariant could be broken
    after the fact — is exactly what the append-only guard above blocks."""
    version_id = _make_version(db_connection, f.knowledge_item_id)
    npc_id = make_character(db_connection, f.world_id, entity_type_code="npc")
    db_connection.execute(
        text("""
            INSERT INTO knowledge.entity_knowledge
                (timeline_id, knowledge_item_id, knower_entity_id, knowledge_version_id)
            VALUES (:tl, :item, :knower, :version)
        """),
        {
            "tl": f.timeline_id,
            "item": f.knowledge_item_id,
            "knower": npc_id,
            "version": version_id,
        },
    )
    other_item_id = make_knowledge_item(db_connection, f.world_id, statement="A different claim.")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE knowledge.knowledge_versions SET knowledge_item_id = :other "
                "WHERE knowledge_version_id = :v"
            ),
            {"other": other_item_id, "v": version_id},
        )
    assert "append-only" in str(exc.value)


# ---------------------------------------------------------------------------
# knowledge.knowledge_types: required seed codes (docs/PLAN.md §15.1)
# ---------------------------------------------------------------------------


def test_knowledge_types_contains_every_required_code(db_connection: Connection) -> None:
    required = {
        "fact",
        "rumor",
        "secret",
        "belief",
        "theory",
        "prophecy",
        "misconception",
        "instruction",
        "memory",
        "doctrine",
    }
    seeded = {
        row[0] for row in db_connection.execute(text("SELECT code FROM knowledge.knowledge_types"))
    }
    missing = required - seeded
    assert not missing, f"knowledge.knowledge_types is missing required codes: {sorted(missing)}"
