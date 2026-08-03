"""World validation for knowledge-domain event timestamps (revision 045).

knowledge.entity_knowledge.learned_at_world_time_id and
knowledge.party_discoveries.discovered_at_world_time_id are nullable
core.world_times references that revision 041's world-agreement triggers
did not check. This file proves both are now validated on insert and
update, and that the immutability revision 030 already gives
core.world_times/core.entities means a later mutation cannot leave a
previously-valid row cross-world.
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
    make_world_time,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.dungeon_id = make_dungeon(connection, self.world_id)
        self.area_a = make_dungeon_area(connection, self.dungeon_id, name="A")
        self.area_b = make_dungeon_area(connection, self.dungeon_id, name="B")
        self.connection_id = make_area_connection(connection, self.area_a, self.area_b)
        self.item_id = make_knowledge_item(
            connection, self.world_id, subject_area_connection_id=self.connection_id
        )
        self.npc_id = make_character(connection, self.world_id, entity_type_code="npc")
        self.party_id = make_party(connection, self.world_id)
        self.world_time_id = make_world_time(connection, self.world_id, 100)


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "knowledge-timestamp-world")


# ---------------------------------------------------------------------------
# knowledge.entity_knowledge.learned_at_world_time_id
# ---------------------------------------------------------------------------


def test_learned_at_world_time_in_the_same_world_is_accepted(
    db_connection: Connection, f: Fixture
) -> None:
    db_connection.execute(
        text(
            "INSERT INTO knowledge.entity_knowledge "
            "(timeline_id, knowledge_item_id, knower_entity_id, learned_at_world_time_id) "
            "VALUES (:tl, :k, :n, :t)"
        ),
        {"tl": f.timeline_id, "k": f.item_id, "n": f.npc_id, "t": f.world_time_id},
    )


def test_learned_at_world_time_from_another_world_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="knowledge-timestamp-learned-other-world")
    foreign_time = make_world_time(db_connection, other_world, 100)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO knowledge.entity_knowledge "
                "(timeline_id, knowledge_item_id, knower_entity_id, learned_at_world_time_id) "
                "VALUES (:tl, :k, :n, :t)"
            ),
            {"tl": f.timeline_id, "k": f.item_id, "n": f.npc_id, "t": foreign_time},
        )
    assert "mixes worlds" in str(exc.value)


def test_updating_learned_at_world_time_to_another_world_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="knowledge-timestamp-learned-update-other-world")
    foreign_time = make_world_time(db_connection, other_world, 100)

    db_connection.execute(
        text(
            "INSERT INTO knowledge.entity_knowledge (timeline_id, knowledge_item_id, "
            "knower_entity_id) VALUES (:tl, :k, :n)"
        ),
        {"tl": f.timeline_id, "k": f.item_id, "n": f.npc_id},
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE knowledge.entity_knowledge SET learned_at_world_time_id = :t "
                "WHERE knowledge_item_id = :k AND knower_entity_id = :n"
            ),
            {"t": foreign_time, "k": f.item_id, "n": f.npc_id},
        )
    assert "mixes worlds" in str(exc.value)


def test_a_referenced_world_time_cannot_later_move_to_another_world(
    db_connection: Connection, f: Fixture
) -> None:
    """core.world_times.world_id is immutable since revision 030, so a
    world time already referenced by learned_at_world_time_id cannot be
    moved out from under an existing, valid row."""
    db_connection.execute(
        text(
            "INSERT INTO knowledge.entity_knowledge (timeline_id, knowledge_item_id, "
            "knower_entity_id, learned_at_world_time_id) VALUES (:tl, :k, :n, :t)"
        ),
        {"tl": f.timeline_id, "k": f.item_id, "n": f.npc_id, "t": f.world_time_id},
    )
    other_world = make_world(db_connection, slug="knowledge-timestamp-learned-immutable-world")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE core.world_times SET world_id = :w WHERE world_time_id = :t"),
            {"w": other_world, "t": f.world_time_id},
        )
    assert "immutable" in str(exc.value)


# ---------------------------------------------------------------------------
# knowledge.party_discoveries.discovered_at_world_time_id
# ---------------------------------------------------------------------------


def test_discovered_at_world_time_in_the_same_world_is_accepted(
    db_connection: Connection, f: Fixture
) -> None:
    db_connection.execute(
        text(
            "INSERT INTO knowledge.party_discoveries "
            "(timeline_id, knowledge_item_id, party_id, discovered_at_world_time_id) "
            "VALUES (:tl, :k, :p, :t)"
        ),
        {"tl": f.timeline_id, "k": f.item_id, "p": f.party_id, "t": f.world_time_id},
    )


def test_discovered_at_world_time_from_another_world_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="knowledge-timestamp-discovered-other-world")
    foreign_time = make_world_time(db_connection, other_world, 100)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO knowledge.party_discoveries "
                "(timeline_id, knowledge_item_id, party_id, discovered_at_world_time_id) "
                "VALUES (:tl, :k, :p, :t)"
            ),
            {"tl": f.timeline_id, "k": f.item_id, "p": f.party_id, "t": foreign_time},
        )
    assert "mixes worlds" in str(exc.value)


def test_updating_discovered_at_world_time_to_another_world_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(
        db_connection, slug="knowledge-timestamp-discovered-update-other-world"
    )
    foreign_time = make_world_time(db_connection, other_world, 100)

    db_connection.execute(
        text(
            "INSERT INTO knowledge.party_discoveries (timeline_id, knowledge_item_id, party_id) "
            "VALUES (:tl, :k, :p)"
        ),
        {"tl": f.timeline_id, "k": f.item_id, "p": f.party_id},
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE knowledge.party_discoveries SET discovered_at_world_time_id = :t "
                "WHERE knowledge_item_id = :k AND party_id = :p"
            ),
            {"t": foreign_time, "k": f.item_id, "p": f.party_id},
        )
    assert "mixes worlds" in str(exc.value)


def test_a_referenced_world_time_cannot_later_move_to_another_world_for_discoveries(
    db_connection: Connection, f: Fixture
) -> None:
    db_connection.execute(
        text(
            "INSERT INTO knowledge.party_discoveries (timeline_id, knowledge_item_id, party_id, "
            "discovered_at_world_time_id) VALUES (:tl, :k, :p, :t)"
        ),
        {"tl": f.timeline_id, "k": f.item_id, "p": f.party_id, "t": f.world_time_id},
    )
    other_world = make_world(db_connection, slug="knowledge-timestamp-discovered-immutable-world")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE core.world_times SET world_id = :w WHERE world_time_id = :t"),
            {"w": other_world, "t": f.world_time_id},
        )
    assert "immutable" in str(exc.value)


def test_the_exactly_one_recipient_check_still_fires_before_the_timestamp_check(
    db_connection: Connection, f: Fixture
) -> None:
    """Regression guard: the malformed-recipient early-return in
    enforce_party_discovery_world() (added to fix issue found while
    building revision 041) must still let the CHECK constraint report a
    missing recipient, even with the new timestamp check present."""
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO knowledge.party_discoveries "
                "(timeline_id, knowledge_item_id, discovered_at_world_time_id) "
                "VALUES (:tl, :k, :t)"
            ),
            {"tl": f.timeline_id, "k": f.item_id, "t": f.world_time_id},
        )
    assert "ck_party_discoveries_exactly_one_recipient" in str(exc.value)
