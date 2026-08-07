"""narrative.story_arcs/.quests/.quest_stages/.quest_objectives/
.objective_dependencies/.quest_participants/.quest_outcomes/.quest_rewards
and campaign.quest_state/.objective_state (revision 073).

Covers: quest entity CTI, story-arc/target/participant/reward world
agreement, the at-most-one-target rule on quest_objectives, the no-self rule
on objective_dependencies, one-current-row-per-(timeline, quest[, party]) on
campaign.quest_state and campaign.objective_state, and last_event_id
timeline safety (reusing campaign.enforce_state_event_timeline(),
revision 066).
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_area_connection,
    make_character,
    make_dungeon,
    make_dungeon_area,
    make_event,
    make_objective_dependency,
    make_objective_state,
    make_party,
    make_quest,
    make_quest_objective,
    make_quest_outcome,
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
        self.dungeon_id = make_dungeon(connection, self.world_id)
        self.area_a = make_dungeon_area(connection, self.dungeon_id, name="Entry Hall")
        self.area_b = make_dungeon_area(connection, self.dungeon_id, name="Vault")
        self.connection_id = make_area_connection(connection, self.area_a, self.area_b)
        self.party_id = make_party(connection, self.world_id)
        self.quest_id = make_quest(connection, self.world_id)
        self.stage_id = make_quest_stage(connection, self.quest_id)


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "quest-domain-world")


# ---------------------------------------------------------------------------
# narrative.story_arcs / narrative.quests
# ---------------------------------------------------------------------------


def test_a_quest_can_belong_to_a_story_arc(db_connection: Connection, f: Fixture) -> None:
    arc_id = make_story_arc(db_connection, f.world_id)
    quest_id = make_quest(db_connection, f.world_id, story_arc_id=arc_id)
    assert quest_id is not None


def test_a_quest_needs_no_story_arc(db_connection: Connection, f: Fixture) -> None:
    make_quest(db_connection, f.world_id)


def test_a_quests_story_arc_must_share_its_world(db_connection: Connection, f: Fixture) -> None:
    other_world = make_world(db_connection, slug="quest-other-world")
    foreign_arc = make_story_arc(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_quest(db_connection, f.world_id, story_arc_id=foreign_arc)
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# narrative.quest_objectives
# ---------------------------------------------------------------------------


def test_an_objective_can_target_an_entity(db_connection: Connection, f: Fixture) -> None:
    npc_id = make_character(db_connection, f.world_id, entity_type_code="npc")
    make_quest_objective(
        db_connection, f.stage_id, objective_type_code="persuade_npc", target_entity_id=npc_id
    )


def test_an_objective_can_target_a_connection(db_connection: Connection, f: Fixture) -> None:
    make_quest_objective(
        db_connection,
        f.stage_id,
        objective_type_code="reach_location",
        target_area_connection_id=f.connection_id,
    )


def test_an_objective_cannot_have_two_targets(db_connection: Connection, f: Fixture) -> None:
    npc_id = make_character(db_connection, f.world_id, entity_type_code="npc")

    with pytest.raises(IntegrityError) as exc:
        make_quest_objective(
            db_connection,
            f.stage_id,
            target_entity_id=npc_id,
            target_area_connection_id=f.connection_id,
        )
    assert "ck_quest_objectives_at_most_one_target" in str(exc.value)


def test_an_objectives_target_must_share_its_world(db_connection: Connection, f: Fixture) -> None:
    other_world = make_world(db_connection, slug="quest-objective-other-world")
    foreign_npc = make_character(db_connection, other_world, entity_type_code="npc")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_quest_objective(db_connection, f.stage_id, target_entity_id=foreign_npc)
    assert "belongs to world" in str(exc.value)


def test_quantity_required_must_be_positive(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("""
                INSERT INTO narrative.quest_objectives
                    (quest_stage_id, objective_type_id, name, quantity_required)
                VALUES (
                    :stage, (SELECT objective_type_id FROM narrative.objective_types WHERE code = 'other'),
                    'Bad quantity', 0
                )
            """),
            {"stage": f.stage_id},
        )
    assert "ck_quest_objectives_quantity_required_positive" in str(exc.value)


# ---------------------------------------------------------------------------
# narrative.objective_dependencies
# ---------------------------------------------------------------------------


def test_an_objective_can_depend_on_another(db_connection: Connection, f: Fixture) -> None:
    first = make_quest_objective(db_connection, f.stage_id, name="First")
    second = make_quest_objective(db_connection, f.stage_id, name="Second")
    make_objective_dependency(db_connection, second, first, dependency_type="prerequisite")


def test_an_objective_cannot_depend_on_itself(db_connection: Connection, f: Fixture) -> None:
    objective = make_quest_objective(db_connection, f.stage_id)

    with pytest.raises(IntegrityError) as exc:
        make_objective_dependency(db_connection, objective, objective)
    assert "ck_objective_dependencies_no_self" in str(exc.value)


def test_a_dependency_must_share_its_world(db_connection: Connection, f: Fixture) -> None:
    objective = make_quest_objective(db_connection, f.stage_id)

    other_world = make_world(db_connection, slug="objective-dependency-other-world")
    other_quest = make_quest(db_connection, other_world)
    other_stage = make_quest_stage(db_connection, other_quest)
    foreign_objective = make_quest_objective(db_connection, other_stage)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_objective_dependency(db_connection, objective, foreign_objective)
    assert "world" in str(exc.value)


# ---------------------------------------------------------------------------
# campaign.quest_state
# ---------------------------------------------------------------------------


def test_only_one_current_quest_state_per_timeline_without_a_party(
    db_connection: Connection, f: Fixture
) -> None:
    make_quest_state(db_connection, f.timeline_id, f.quest_id)
    with pytest.raises(IntegrityError):
        make_quest_state(db_connection, f.timeline_id, f.quest_id)


def test_a_second_party_can_track_the_same_quest_independently(
    db_connection: Connection, f: Fixture
) -> None:
    other_party = make_party(db_connection, f.world_id)
    make_quest_state(db_connection, f.timeline_id, f.quest_id, party_id=f.party_id)
    make_quest_state(db_connection, f.timeline_id, f.quest_id, party_id=other_party)


def test_only_one_current_quest_state_per_timeline_quest_and_party(
    db_connection: Connection, f: Fixture
) -> None:
    make_quest_state(db_connection, f.timeline_id, f.quest_id, party_id=f.party_id)
    with pytest.raises(IntegrityError):
        make_quest_state(db_connection, f.timeline_id, f.quest_id, party_id=f.party_id)


def test_quest_state_party_must_share_its_world(db_connection: Connection, f: Fixture) -> None:
    other_world = make_world(db_connection, slug="quest-state-other-world")
    foreign_party = make_party(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_quest_state(db_connection, f.timeline_id, f.quest_id, party_id=foreign_party)
    assert "does not match" in str(exc.value)


def test_quest_state_last_event_must_share_its_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    other_timeline = make_timeline(db_connection, f.world_id)
    other_world_time = make_world_time(db_connection, f.world_id, 200)
    foreign_event = make_event(db_connection, f.world_id, other_timeline, other_world_time)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_quest_state(db_connection, f.timeline_id, f.quest_id, last_event_id=foreign_event)
    assert "same timeline" in str(exc.value)


# ---------------------------------------------------------------------------
# campaign.objective_state
# ---------------------------------------------------------------------------


def test_only_one_current_objective_state_per_timeline_without_a_party(
    db_connection: Connection, f: Fixture
) -> None:
    objective = make_quest_objective(db_connection, f.stage_id)
    make_objective_state(db_connection, f.timeline_id, objective)
    with pytest.raises(IntegrityError):
        make_objective_state(db_connection, f.timeline_id, objective)


def test_objective_state_party_must_share_its_world(db_connection: Connection, f: Fixture) -> None:
    objective = make_quest_objective(db_connection, f.stage_id)
    other_world = make_world(db_connection, slug="objective-state-other-world")
    foreign_party = make_party(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_objective_state(db_connection, f.timeline_id, objective, party_id=foreign_party)
    assert "does not match" in str(exc.value)


# ---------------------------------------------------------------------------
# narrative.quest_outcomes / narrative.quest_rewards
# ---------------------------------------------------------------------------


def test_an_outcomes_code_is_unique_per_quest(db_connection: Connection, f: Fixture) -> None:
    make_quest_outcome(db_connection, f.quest_id, code="saved_the_village")
    with pytest.raises(IntegrityError):
        make_quest_outcome(db_connection, f.quest_id, code="saved_the_village")


def test_two_quests_can_reuse_the_same_outcome_code(db_connection: Connection, f: Fixture) -> None:
    other_quest = make_quest(db_connection, f.world_id)
    make_quest_outcome(db_connection, f.quest_id, code="success")
    make_quest_outcome(db_connection, other_quest, code="success")


def test_a_reward_can_grant_a_knowledge_item(db_connection: Connection, f: Fixture) -> None:
    from tests.factories import make_knowledge_item

    outcome_id = make_quest_outcome(db_connection, f.quest_id)
    knowledge_item_id = make_knowledge_item(db_connection, f.world_id)
    db_connection.execute(
        text("""
            INSERT INTO narrative.quest_rewards
                (quest_outcome_id, reward_type, description, reward_knowledge_item_id)
            VALUES (:outcome, 'knowledge', 'Learns the truth', :item)
        """),
        {"outcome": outcome_id, "item": knowledge_item_id},
    )


def test_a_rewards_knowledge_item_must_share_its_world(
    db_connection: Connection, f: Fixture
) -> None:
    from tests.factories import make_knowledge_item

    outcome_id = make_quest_outcome(db_connection, f.quest_id)
    other_world = make_world(db_connection, slug="quest-reward-other-world")
    foreign_item = make_knowledge_item(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("""
                INSERT INTO narrative.quest_rewards
                    (quest_outcome_id, reward_type, description, reward_knowledge_item_id)
                VALUES (:outcome, 'knowledge', 'Learns the truth', :item)
            """),
            {"outcome": outcome_id, "item": foreign_item},
        )
    assert "belongs to world" in str(exc.value)
