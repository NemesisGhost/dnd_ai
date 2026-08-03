"""knowledge.knowledge_items, .entity_knowledge, .party_discoveries
(revision 041, pulled forward from Phase 7 — see that revision's docstring).

Covers: at-most-one-subject on a knowledge item, same-world enforcement
across all three tables, exactly-one-recipient on party_discoveries, and the
scenario at the heart of Phase 5's "hidden connections remain distinct from
party knowledge" exit criterion: a hidden connection's own row never reveals
whether any party has found it.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_area_connection,
    make_character,
    make_dungeon,
    make_dungeon_area,
    make_knowledge_item,
    make_party,
    make_timeline,
    make_world,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.dungeon_id = make_dungeon(connection, self.world_id)
        self.area_a = make_dungeon_area(connection, self.dungeon_id, name="Entry Hall")
        self.area_b = make_dungeon_area(connection, self.dungeon_id, name="Vault")
        self.hidden_connection_id = make_area_connection(
            connection,
            self.area_a,
            self.area_b,
            connection_type_code="secret_door",
            is_hidden=True,
        )
        self.party_id = make_party(connection, self.world_id)


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "knowledge-world")


# ---------------------------------------------------------------------------
# knowledge.knowledge_items
# ---------------------------------------------------------------------------


def test_a_knowledge_item_about_a_hidden_connection_can_be_created(
    db_connection: Connection, f: Fixture
) -> None:
    make_knowledge_item(
        db_connection,
        f.world_id,
        knowledge_type_code="secret",
        truth_status_code="true",
        statement="A secret door links the entry hall to the vault.",
        subject_area_connection_id=f.hidden_connection_id,
    )


def test_a_knowledge_item_cannot_have_two_subjects(db_connection: Connection, f: Fixture) -> None:
    other_character = make_character(db_connection, f.world_id)

    with pytest.raises(IntegrityError) as exc:
        make_knowledge_item(
            db_connection,
            f.world_id,
            subject_area_connection_id=f.hidden_connection_id,
            subject_entity_id=other_character,
        )
    assert "ck_knowledge_items_at_most_one_subject" in str(exc.value)


def test_a_knowledge_item_with_no_subject_is_valid(db_connection: Connection, f: Fixture) -> None:
    """General lore/rumor need not be about any specific structural target."""
    make_knowledge_item(db_connection, f.world_id, statement="Dragons once ruled this vale.")


def test_a_knowledge_items_subject_must_share_its_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="knowledge-other-world")
    other_dungeon = make_dungeon(db_connection, other_world)
    other_area_a = make_dungeon_area(db_connection, other_dungeon)
    other_area_b = make_dungeon_area(db_connection, other_dungeon)
    foreign_connection = make_area_connection(db_connection, other_area_a, other_area_b)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_knowledge_item(
            db_connection, f.world_id, subject_area_connection_id=foreign_connection
        )
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# knowledge.entity_knowledge
# ---------------------------------------------------------------------------


def test_an_npc_can_know_a_secret(db_connection: Connection, f: Fixture) -> None:
    item_id = make_knowledge_item(
        db_connection, f.world_id, subject_area_connection_id=f.hidden_connection_id
    )
    npc_id = make_character(db_connection, f.world_id, entity_type_code="npc")
    db_connection.execute(
        text(
            "INSERT INTO knowledge.entity_knowledge "
            "(timeline_id, knowledge_item_id, knower_entity_id) VALUES (:tl, :k, :n)"
        ),
        {"tl": f.timeline_id, "k": item_id, "n": npc_id},
    )


def test_entity_knowledge_requires_world_agreement(db_connection: Connection, f: Fixture) -> None:
    item_id = make_knowledge_item(
        db_connection, f.world_id, subject_area_connection_id=f.hidden_connection_id
    )
    other_world = make_world(db_connection, slug="knowledge-entity-other-world")
    foreign_npc = make_character(db_connection, other_world, entity_type_code="npc")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO knowledge.entity_knowledge "
                "(timeline_id, knowledge_item_id, knower_entity_id) VALUES (:tl, :k, :n)"
            ),
            {"tl": f.timeline_id, "k": item_id, "n": foreign_npc},
        )
    assert "mixes worlds" in str(exc.value)


def test_only_one_current_belief_per_timeline_item_and_knower(
    db_connection: Connection, f: Fixture
) -> None:
    item_id = make_knowledge_item(
        db_connection, f.world_id, subject_area_connection_id=f.hidden_connection_id
    )
    npc_id = make_character(db_connection, f.world_id, entity_type_code="npc")
    db_connection.execute(
        text(
            "INSERT INTO knowledge.entity_knowledge "
            "(timeline_id, knowledge_item_id, knower_entity_id) VALUES (:tl, :k, :n)"
        ),
        {"tl": f.timeline_id, "k": item_id, "n": npc_id},
    )
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text(
                "INSERT INTO knowledge.entity_knowledge "
                "(timeline_id, knowledge_item_id, knower_entity_id) VALUES (:tl, :k, :n)"
            ),
            {"tl": f.timeline_id, "k": item_id, "n": npc_id},
        )


# ---------------------------------------------------------------------------
# knowledge.party_discoveries
# ---------------------------------------------------------------------------


def test_a_party_can_discover_a_hidden_connection(db_connection: Connection, f: Fixture) -> None:
    item_id = make_knowledge_item(
        db_connection, f.world_id, subject_area_connection_id=f.hidden_connection_id
    )
    db_connection.execute(
        text(
            "INSERT INTO knowledge.party_discoveries "
            "(timeline_id, knowledge_item_id, party_id, discovery_method) "
            "VALUES (:tl, :k, :p, 'search_check')"
        ),
        {"tl": f.timeline_id, "k": item_id, "p": f.party_id},
    )


def test_a_discovery_needs_exactly_one_recipient(db_connection: Connection, f: Fixture) -> None:
    item_id = make_knowledge_item(
        db_connection, f.world_id, subject_area_connection_id=f.hidden_connection_id
    )

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO knowledge.party_discoveries (timeline_id, knowledge_item_id) "
                "VALUES (:tl, :k)"
            ),
            {"tl": f.timeline_id, "k": item_id},
        )
    assert "ck_party_discoveries_exactly_one_recipient" in str(exc.value)


def test_a_discovery_cannot_name_both_a_party_and_a_knower(
    db_connection: Connection, f: Fixture
) -> None:
    item_id = make_knowledge_item(
        db_connection, f.world_id, subject_area_connection_id=f.hidden_connection_id
    )
    npc_id = make_character(db_connection, f.world_id, entity_type_code="npc")

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO knowledge.party_discoveries "
                "(timeline_id, knowledge_item_id, party_id, knower_entity_id) "
                "VALUES (:tl, :k, :p, :n)"
            ),
            {"tl": f.timeline_id, "k": item_id, "p": f.party_id, "n": npc_id},
        )
    assert "ck_party_discoveries_exactly_one_recipient" in str(exc.value)


def test_a_party_cannot_discover_the_same_item_twice(db_connection: Connection, f: Fixture) -> None:
    item_id = make_knowledge_item(
        db_connection, f.world_id, subject_area_connection_id=f.hidden_connection_id
    )
    db_connection.execute(
        text(
            "INSERT INTO knowledge.party_discoveries (timeline_id, knowledge_item_id, party_id) "
            "VALUES (:tl, :k, :p)"
        ),
        {"tl": f.timeline_id, "k": item_id, "p": f.party_id},
    )
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text(
                "INSERT INTO knowledge.party_discoveries "
                "(timeline_id, knowledge_item_id, party_id) VALUES (:tl, :k, :p)"
            ),
            {"tl": f.timeline_id, "k": item_id, "p": f.party_id},
        )


def test_party_discoveries_requires_world_agreement(db_connection: Connection, f: Fixture) -> None:
    item_id = make_knowledge_item(
        db_connection, f.world_id, subject_area_connection_id=f.hidden_connection_id
    )
    other_world = make_world(db_connection, slug="knowledge-discovery-other-world")
    foreign_party = make_party(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO knowledge.party_discoveries "
                "(timeline_id, knowledge_item_id, party_id) VALUES (:tl, :k, :p)"
            ),
            {"tl": f.timeline_id, "k": item_id, "p": foreign_party},
        )
    assert "mixes worlds" in str(exc.value)


# ---------------------------------------------------------------------------
# Phase 5 exit criterion: hidden connections remain distinct from party
# knowledge (docs/PLAN.md Phase 5; docs/architecture/DATABASE_MODEL.md §9.3)
# ---------------------------------------------------------------------------


def test_a_hidden_connections_own_row_never_reveals_party_knowledge(
    db_connection: Connection, f: Fixture
) -> None:
    """The connection exists (and is hidden) regardless of what any party
    knows. Querying world.area_connections alone must never distinguish a
    discovered connection from an undiscovered one — that distinction lives
    only in knowledge.party_discoveries, scoped to a specific party."""
    second_party = make_party(db_connection, f.world_id, name="The Rival Company")
    item_id = make_knowledge_item(
        db_connection, f.world_id, subject_area_connection_id=f.hidden_connection_id
    )
    db_connection.execute(
        text(
            "INSERT INTO knowledge.party_discoveries (timeline_id, knowledge_item_id, party_id) "
            "VALUES (:tl, :k, :p)"
        ),
        {"tl": f.timeline_id, "k": item_id, "p": f.party_id},
    )

    # world.area_connections carries no party-specific column at all — the
    # connection row for f.party_id (who found it) and second_party (who has
    # not) is the exact same row, with the exact same columns.
    columns = set(
        db_connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'world' AND table_name = 'area_connections'"
            )
        ).scalars()
    )
    assert not any("discover" in c or "known" in c for c in columns)

    discovered_by_first_party = db_connection.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM knowledge.party_discoveries "
            "WHERE knowledge_item_id = :k AND party_id = :p)"
        ),
        {"k": item_id, "p": f.party_id},
    ).scalar()
    discovered_by_second_party = db_connection.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM knowledge.party_discoveries "
            "WHERE knowledge_item_id = :k AND party_id = :p)"
        ),
        {"k": item_id, "p": second_party},
    ).scalar()

    assert discovered_by_first_party is True
    assert discovered_by_second_party is False

    still_hidden = db_connection.execute(
        text("SELECT is_hidden FROM world.area_connections WHERE area_connection_id = :c"),
        {"c": f.hidden_connection_id},
    ).scalar()
    assert still_hidden is True
