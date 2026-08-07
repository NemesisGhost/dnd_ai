"""Immutable parent-scope identity columns for the quest and knowledge
domain (revision 075_phase7_reparent_guards).

Every same-world/same-scope trigger revision 073 built validates on INSERT
and UPDATE of the *child* row only — none of them re-run when a *parent*
row's own scope identity changes out from under already-valid dependents.
This revision closes that gap the same way revision 030 already did once
for core.world_times/.entities/campaign.timelines/.parties/.campaigns:
narrative.story_arcs.world_id, narrative.quest_stages.quest_id, narrative.
quest_objectives.quest_stage_id, narrative.quest_outcomes.quest_id,
knowledge.entity_knowledge.timeline_id, and campaign.objective_state.
timeline_id are all now immutable once set.

Each guard gets one test proving the identity column can no longer be
reparented out from under an existing dependent, and one proving a
legitimate non-identity update to the same row still works. Also adds the
narrower campaign.quest_state/.objective_state/narrative.quest_participants
world-agreement coverage docs/DATABASE_CONVENTIONS.md §32.1 calls for that
test_quest_domain.py didn't already exercise.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_character,
    make_consequence,
    make_event,
    make_interaction,
    make_objective_state,
    make_party,
    make_quest,
    make_quest_objective,
    make_quest_outcome,
    make_quest_participant,
    make_quest_stage,
    make_quest_state,
    make_story_arc,
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
        self.quest_id = make_quest(connection, self.world_id)
        self.stage_id = make_quest_stage(connection, self.quest_id)
        self.objective_id = make_quest_objective(connection, self.stage_id)


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "phase7-reparent-guards-world")


def _make_entity_knowledge(
    connection: Connection, timeline_id, knowledge_item_id, knower_entity_id
) -> object:
    return connection.execute(
        text("""
            INSERT INTO knowledge.entity_knowledge (timeline_id, knowledge_item_id, knower_entity_id)
            VALUES (:tl, :item, :knower)
            RETURNING entity_knowledge_id
        """),
        {"tl": timeline_id, "item": knowledge_item_id, "knower": knower_entity_id},
    ).scalar()


# ---------------------------------------------------------------------------
# narrative.story_arcs.world_id
# ---------------------------------------------------------------------------


def test_a_story_arcs_world_cannot_be_reparented_once_a_quest_references_it(
    db_connection: Connection, f: Fixture
) -> None:
    arc_id = make_story_arc(db_connection, f.world_id)
    make_quest(db_connection, f.world_id, story_arc_id=arc_id)
    other_world = make_world(db_connection, slug="story-arc-reparent-other-world")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE narrative.story_arcs SET world_id = :w WHERE story_arc_id = :a"),
            {"w": other_world, "a": arc_id},
        )
    assert "immutable" in str(exc.value)


def test_a_story_arcs_status_can_still_be_updated(db_connection: Connection, f: Fixture) -> None:
    arc_id = make_story_arc(db_connection, f.world_id)
    db_connection.execute(
        text("UPDATE narrative.story_arcs SET status = 'complete' WHERE story_arc_id = :a"),
        {"a": arc_id},
    )
    row = db_connection.execute(
        text("SELECT status FROM narrative.story_arcs WHERE story_arc_id = :a"), {"a": arc_id}
    ).one()
    assert row.status == "complete"


# ---------------------------------------------------------------------------
# narrative.quest_stages.quest_id
# ---------------------------------------------------------------------------


def test_a_quest_stages_quest_cannot_be_reparented_once_an_objective_references_it(
    db_connection: Connection, f: Fixture
) -> None:
    other_quest = make_quest(db_connection, f.world_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE narrative.quest_stages SET quest_id = :q WHERE quest_stage_id = :s"),
            {"q": other_quest, "s": f.stage_id},
        )
    assert "immutable" in str(exc.value)


def test_a_quest_stages_name_can_still_be_updated(db_connection: Connection, f: Fixture) -> None:
    db_connection.execute(
        text("UPDATE narrative.quest_stages SET name = 'Renamed Stage' WHERE quest_stage_id = :s"),
        {"s": f.stage_id},
    )
    row = db_connection.execute(
        text("SELECT name FROM narrative.quest_stages WHERE quest_stage_id = :s"), {"s": f.stage_id}
    ).one()
    assert row.name == "Renamed Stage"


# ---------------------------------------------------------------------------
# narrative.quest_objectives.quest_stage_id
# ---------------------------------------------------------------------------


def test_an_objectives_stage_cannot_be_reparented_once_a_dependency_references_it(
    db_connection: Connection, f: Fixture
) -> None:
    other_stage = make_quest_stage(db_connection, f.quest_id, name="Other Stage")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE narrative.quest_objectives SET quest_stage_id = :s "
                "WHERE quest_objective_id = :o"
            ),
            {"s": other_stage, "o": f.objective_id},
        )
    assert "immutable" in str(exc.value)


def test_an_objectives_name_can_still_be_updated(db_connection: Connection, f: Fixture) -> None:
    db_connection.execute(
        text(
            "UPDATE narrative.quest_objectives SET name = 'Renamed Objective' "
            "WHERE quest_objective_id = :o"
        ),
        {"o": f.objective_id},
    )
    row = db_connection.execute(
        text("SELECT name FROM narrative.quest_objectives WHERE quest_objective_id = :o"),
        {"o": f.objective_id},
    ).one()
    assert row.name == "Renamed Objective"


# ---------------------------------------------------------------------------
# narrative.quest_outcomes.quest_id
# ---------------------------------------------------------------------------


def test_a_quest_outcomes_quest_cannot_be_reparented_once_a_reward_references_it(
    db_connection: Connection, f: Fixture
) -> None:
    outcome_id = make_quest_outcome(db_connection, f.quest_id)
    other_quest = make_quest(db_connection, f.world_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE narrative.quest_outcomes SET quest_id = :q WHERE quest_outcome_id = :o"),
            {"q": other_quest, "o": outcome_id},
        )
    assert "immutable" in str(exc.value)


def test_a_quest_outcomes_description_can_still_be_updated(
    db_connection: Connection, f: Fixture
) -> None:
    outcome_id = make_quest_outcome(db_connection, f.quest_id)
    db_connection.execute(
        text(
            "UPDATE narrative.quest_outcomes SET description = 'Updated outcome text' "
            "WHERE quest_outcome_id = :o"
        ),
        {"o": outcome_id},
    )
    row = db_connection.execute(
        text("SELECT description FROM narrative.quest_outcomes WHERE quest_outcome_id = :o"),
        {"o": outcome_id},
    ).one()
    assert row.description == "Updated outcome text"


# ---------------------------------------------------------------------------
# knowledge.entity_knowledge.timeline_id
# ---------------------------------------------------------------------------


def test_entity_knowledges_timeline_cannot_be_reparented_once_a_transfer_references_it(
    db_connection: Connection, f: Fixture
) -> None:
    from tests.factories import make_knowledge_item

    knowledge_item_id = make_knowledge_item(db_connection, f.world_id)
    knower = make_character(db_connection, f.world_id, entity_type_code="npc")
    entity_knowledge_id = _make_entity_knowledge(
        db_connection, f.timeline_id, knowledge_item_id, knower
    )
    other_timeline = make_timeline(db_connection, f.world_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE knowledge.entity_knowledge SET timeline_id = :tl "
                "WHERE entity_knowledge_id = :ek"
            ),
            {"tl": other_timeline, "ek": entity_knowledge_id},
        )
    assert "immutable" in str(exc.value)


def test_an_entity_knowledges_awareness_level_can_still_be_updated(
    db_connection: Connection, f: Fixture
) -> None:
    from tests.factories import make_knowledge_item

    knowledge_item_id = make_knowledge_item(db_connection, f.world_id)
    knower = make_character(db_connection, f.world_id, entity_type_code="npc")
    entity_knowledge_id = _make_entity_knowledge(
        db_connection, f.timeline_id, knowledge_item_id, knower
    )
    db_connection.execute(
        text(
            "UPDATE knowledge.entity_knowledge SET awareness_level = 'suspected' "
            "WHERE entity_knowledge_id = :ek"
        ),
        {"ek": entity_knowledge_id},
    )
    row = db_connection.execute(
        text(
            "SELECT awareness_level FROM knowledge.entity_knowledge WHERE entity_knowledge_id = :ek"
        ),
        {"ek": entity_knowledge_id},
    ).one()
    assert row.awareness_level == "suspected"


# ---------------------------------------------------------------------------
# campaign.objective_state.timeline_id
# ---------------------------------------------------------------------------


def test_objective_states_timeline_cannot_be_reparented_once_a_consequence_references_it(
    db_connection: Connection, f: Fixture
) -> None:
    objective_state_id = make_objective_state(db_connection, f.timeline_id, f.objective_id)
    interaction_id = make_interaction(db_connection, f.timeline_id, f.world_time_id)
    make_consequence(
        db_connection,
        interaction_id,
        consequence_type="quest_change",
        resulting_quest_objective_state_id=objective_state_id,
    )
    other_timeline = make_timeline(db_connection, f.world_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE campaign.objective_state SET timeline_id = :tl "
                "WHERE objective_state_id = :os"
            ),
            {"tl": other_timeline, "os": objective_state_id},
        )
    assert "immutable" in str(exc.value)


def test_an_objective_states_status_can_still_be_updated(
    db_connection: Connection, f: Fixture
) -> None:
    """The exact non-identity update src/dnd_ai/commands/quests.py
    advance_objective() performs on an existing row: objective_status_id and
    last_event_id change, timeline_id does not."""
    objective_state_id = make_objective_state(
        db_connection, f.timeline_id, f.objective_id, status_code="active"
    )
    event_id = make_event(db_connection, f.world_id, f.timeline_id, f.world_time_id)
    db_connection.execute(
        text("""
            UPDATE campaign.objective_state
            SET objective_status_id =
                (SELECT objective_status_id FROM campaign.objective_statuses WHERE code = 'completed'),
                last_event_id = :event
            WHERE objective_state_id = :os
        """),
        {"event": event_id, "os": objective_state_id},
    )
    row = db_connection.execute(
        text("""
            SELECT (SELECT code FROM campaign.objective_statuses WHERE objective_status_id = os.objective_status_id) AS status_code
            FROM campaign.objective_state os WHERE objective_state_id = :os
        """),
        {"os": objective_state_id},
    ).one()
    assert row.status_code == "completed"


# ---------------------------------------------------------------------------
# campaign.quest_state / campaign.objective_state / narrative.quest_participants
# world-agreement coverage
# ---------------------------------------------------------------------------


def test_quest_state_rejects_a_quest_from_another_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="quest-state-foreign-quest-world")
    foreign_quest = make_quest(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_quest_state(db_connection, f.timeline_id, foreign_quest)
    assert "does not match" in str(exc.value)


def test_objective_state_rejects_an_objective_from_another_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="objective-state-foreign-objective-world")
    foreign_quest = make_quest(db_connection, other_world)
    foreign_stage = make_quest_stage(db_connection, foreign_quest)
    foreign_objective = make_quest_objective(db_connection, foreign_stage)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_objective_state(db_connection, f.timeline_id, foreign_objective)
    assert "does not match" in str(exc.value)


def test_objective_state_rejects_last_event_id_from_another_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    other_timeline = make_timeline(db_connection, f.world_id)
    other_world_time = make_world_time(db_connection, f.world_id, 200)
    foreign_event = make_event(db_connection, f.world_id, other_timeline, other_world_time)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_objective_state(
            db_connection, f.timeline_id, f.objective_id, last_event_id=foreign_event
        )
    assert "same timeline" in str(exc.value)


def test_quest_participants_accepts_a_same_world_participant(
    db_connection: Connection, f: Fixture
) -> None:
    npc = make_character(db_connection, f.world_id, entity_type_code="npc")
    make_quest_participant(db_connection, f.quest_id, npc)


def test_quest_participants_rejects_a_cross_world_participant(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="quest-participant-other-world")
    foreign_npc = make_character(db_connection, other_world, entity_type_code="npc")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_quest_participant(db_connection, f.quest_id, foreign_npc)
    assert "belongs to world" in str(exc.value)
