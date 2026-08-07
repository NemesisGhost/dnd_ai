"""advance_objective(): a dungeon event advances or fails a quest objective
(docs/PLAN.md Phase 7 exit criterion — "Dungeon events can advance or fail
quest objectives"). Required scenario test per docs/DATABASE_CONVENTIONS.md
§32.2 ("quest advancement").

Mirrors dnd_ai.commands.interactions' resolve_check scenario test: build a
concrete dungeon scenario (a mechanism-activation objective tied to an area
interactable), drive it through the real command, and verify the recorded
event, the updated campaign.objective_state, and the linking
narrative.event_effects row — not by inspecting the transaction boundary.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.quests import advance_objective
from tests.factories import (
    make_area_interactable,
    make_character,
    make_dungeon,
    make_dungeon_area,
    make_quest,
    make_quest_objective,
    make_quest_stage,
    make_timeline,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.scenario


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        self.dungeon_id = make_dungeon(connection, self.world_id)
        self.area_id = make_dungeon_area(connection, self.dungeon_id, name="Shrine Room")
        self.interactable_id = make_area_interactable(connection, self.area_id)
        self.actor_id = make_character(connection, self.world_id, name="Rin")
        self.quest_id = make_quest(connection, self.world_id, name="Restore the Shrine")
        self.stage_id = make_quest_stage(connection, self.quest_id)
        self.objective_id = make_quest_objective(
            connection,
            self.stage_id,
            objective_type_code="activate_mechanism",
            name="Activate the pylon",
            target_area_interactable_id=self.interactable_id,
        )


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"quest-advancement-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )


def _objective_state(postgres_engine: Engine, f: Fixture) -> tuple[str, uuid.UUID] | None:
    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT os.code, ost.last_event_id
                FROM campaign.objective_state ost
                JOIN campaign.objective_statuses os ON os.objective_status_id = ost.objective_status_id
                WHERE ost.timeline_id = :t AND ost.quest_objective_id = :o
            """),
            {"t": f.timeline_id, "o": f.objective_id},
        ).one_or_none()
    return (row.code, row.last_event_id) if row is not None else None


def test_an_event_completes_a_quest_objective(postgres_engine: Engine, f: Fixture) -> None:
    result = advance_objective(
        postgres_engine,
        quest_objective_id=f.objective_id,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        new_status_code="completed",
        actor_entity_id=f.actor_id,
    )

    assert result.previous_status_code is None
    assert result.new_status_code == "completed"

    with postgres_engine.connect() as verify:
        event_row = verify.execute(
            text("""
                SELECT et.code AS type_code
                FROM narrative.events ev
                JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id
                WHERE ev.event_id = :e
            """),
            {"e": result.event_id},
        ).one()
        assert event_row.type_code == "objective_completed"

        effect_row = verify.execute(
            text("""
                SELECT target_quest_objective_id, previous_value, new_value
                FROM narrative.event_effects WHERE event_id = :e
            """),
            {"e": result.event_id},
        ).one()
        assert effect_row.target_quest_objective_id == f.objective_id
        assert effect_row.previous_value is None
        assert effect_row.new_value == "completed"

    assert _objective_state(postgres_engine, f) == ("completed", result.event_id)


def test_an_event_fails_a_quest_objective(postgres_engine: Engine, f: Fixture) -> None:
    result = advance_objective(
        postgres_engine,
        quest_objective_id=f.objective_id,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        new_status_code="failed",
        actor_entity_id=f.actor_id,
    )

    assert result.new_status_code == "failed"
    assert _objective_state(postgres_engine, f) == ("failed", result.event_id)


def test_advancing_an_already_terminal_objective_is_rejected(
    postgres_engine: Engine, f: Fixture
) -> None:
    advance_objective(
        postgres_engine,
        quest_objective_id=f.objective_id,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        new_status_code="completed",
    )

    with pytest.raises(ValueError, match="terminal"):
        advance_objective(
            postgres_engine,
            quest_objective_id=f.objective_id,
            timeline_id=f.timeline_id,
            world_time_id=f.world_time_id,
            new_status_code="failed",
        )

    # The rejected second call left the objective's terminal state untouched.
    assert _objective_state(postgres_engine, f)[0] == "completed"


def test_an_invalid_new_status_is_rejected(postgres_engine: Engine, f: Fixture) -> None:
    with pytest.raises(ValueError, match="new_status_code"):
        advance_objective(
            postgres_engine,
            quest_objective_id=f.objective_id,
            timeline_id=f.timeline_id,
            world_time_id=f.world_time_id,
            new_status_code="active",
        )
