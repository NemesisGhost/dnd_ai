"""start_encounter() / resolve_combat_turn() / end_encounter(): a dungeon
(or Foundry) combat session updates persistent character and world state
(docs/PLAN.md Phase 9 exit criterion: "Foundry combat can update persistent
character and world state"). Required scenario test per
docs/DATABASE_CONVENTIONS.md §32.2.

Mirrors dnd_ai.commands.relationships' scenario test: build a concrete
scenario, drive it through the real commands, and verify the recorded
event, the updated campaign.character_state row, and the linking
narrative.event_effects/event_causes rows — not by inspecting the
transaction boundary.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.encounters import end_encounter, resolve_combat_turn, start_encounter
from tests.factories import (
    make_character,
    make_character_state,
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
        self.attacker_id = make_character(connection, self.world_id, name="Rin")
        self.defender_id = make_character(connection, self.world_id, name="Borrin")
        make_character_state(
            connection,
            self.timeline_id,
            self.defender_id,
            current_hit_points=20,
            maximum_hit_points=20,
        )


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"encounter-commands-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )


def _character_hit_points(
    postgres_engine: Engine, timeline_id: uuid.UUID, character_id: uuid.UUID
) -> int:
    with postgres_engine.connect() as verify:
        value = verify.execute(
            text("""
                SELECT current_hit_points FROM campaign.character_state
                WHERE timeline_id = :t AND character_id = :c
            """),
            {"t": timeline_id, "c": character_id},
        ).scalar()
    assert isinstance(value, int)
    return value


def test_starting_an_encounter_creates_it_with_its_participants(
    postgres_engine: Engine, f: Fixture
) -> None:
    result = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("SELECT status FROM narrative.encounters WHERE encounter_id = :e"),
            {"e": result.encounter_id},
        ).one()
        assert row.status == "active"

        participant_count = verify.execute(
            text("SELECT count(*) FROM narrative.encounter_participants WHERE encounter_id = :e"),
            {"e": result.encounter_id},
        ).scalar()
        assert participant_count == 2


def test_a_damaging_combat_turn_updates_persistent_character_state(
    postgres_engine: Engine, f: Fixture
) -> None:
    """The exit criterion's core claim: combat updates persistent
    character state, with a causal event citing the encounter."""
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    result = resolve_combat_turn(
        postgres_engine,
        encounter_id=start.encounter_id,
        round_number=1,
        turn_order=0,
        actor_entity_id=f.attacker_id,
        world_time_id=f.world_time_id,
        action_kind="attack",
        target_entity_id=f.defender_id,
        hit=True,
        damage_amount=7,
    )

    assert result.previous_hit_points == 20
    assert result.new_hit_points == 13
    assert result.event_id is not None
    assert _character_hit_points(postgres_engine, f.timeline_id, f.defender_id) == 13

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
        assert event_row.type_code == "combat_damage_dealt"

        cause_row = verify.execute(
            text("SELECT cause_encounter_id FROM narrative.event_causes WHERE event_id = :e"),
            {"e": result.event_id},
        ).one()
        assert cause_row.cause_encounter_id == start.encounter_id

        effect_row = verify.execute(
            text("""
                SELECT target_entity_id, previous_value, new_value
                FROM narrative.event_effects WHERE event_id = :e
            """),
            {"e": result.event_id},
        ).one()
        assert effect_row.target_entity_id == f.defender_id
        assert effect_row.previous_value == 20
        assert effect_row.new_value == 13

        combat_action_row = verify.execute(
            text("""
                SELECT ca.hit, ca.damage_amount
                FROM narrative.encounter_turns et
                JOIN interaction.combat_actions ca ON ca.combat_action_id = et.combat_action_id
                WHERE et.encounter_turn_id = :turn
            """),
            {"turn": result.encounter_turn_id},
        ).one()
        assert combat_action_row.hit is True
        assert combat_action_row.damage_amount == 7


def test_a_miss_leaves_character_state_and_events_untouched(
    postgres_engine: Engine, f: Fixture
) -> None:
    """Not every attack roll needs a permanent world event
    (docs/architecture/DATABASE_MODEL.md §12.3) — a miss updates only the
    turn/combat_action record."""
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    result = resolve_combat_turn(
        postgres_engine,
        encounter_id=start.encounter_id,
        round_number=1,
        turn_order=0,
        actor_entity_id=f.attacker_id,
        world_time_id=f.world_time_id,
        action_kind="attack",
        target_entity_id=f.defender_id,
        hit=False,
    )

    assert result.event_id is None
    assert result.new_hit_points is None
    assert _character_hit_points(postgres_engine, f.timeline_id, f.defender_id) == 20


def test_ending_an_encounter_records_outcomes_and_completes_it(
    postgres_engine: Engine, f: Fixture
) -> None:
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    result = end_encounter(
        postgres_engine,
        encounter_id=start.encounter_id,
        world_time_id=f.world_time_id,
        outcomes=((f.defender_id, "defeated"),),
        summary="The party prevailed.",
    )

    with postgres_engine.connect() as verify:
        encounter_row = verify.execute(
            text("""
                SELECT status, resulting_event_id, summary FROM narrative.encounters
                WHERE encounter_id = :e
            """),
            {"e": start.encounter_id},
        ).one()
        assert encounter_row.status == "completed"
        assert encounter_row.resulting_event_id == result.event_id
        assert encounter_row.summary == "The party prevailed."

        outcome_row = verify.execute(
            text("""
                SELECT outcome FROM narrative.encounter_participants
                WHERE encounter_id = :e AND participant_entity_id = :p
            """),
            {"e": start.encounter_id, "p": f.defender_id},
        ).one()
        assert outcome_row.outcome == "defeated"


def test_resolving_a_turn_for_a_non_participant_fails_cleanly(
    postgres_engine: Engine, f: Fixture
) -> None:
    """Atomicity proof: an actor who never joined the encounter fails
    _participant_id()'s lookup after the round has already been created —
    the whole transaction must roll back, leaving no round or turn behind."""
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id,),
    )

    with postgres_engine.begin() as connection:
        outsider_id = make_character(connection, f.world_id, name="Outsider")

    with pytest.raises(ValueError, match="is not a participant"):
        resolve_combat_turn(
            postgres_engine,
            encounter_id=start.encounter_id,
            round_number=1,
            turn_order=0,
            actor_entity_id=outsider_id,
            world_time_id=f.world_time_id,
        )

    with postgres_engine.connect() as verify:
        round_count = verify.execute(
            text("SELECT count(*) FROM narrative.encounter_rounds WHERE encounter_id = :e"),
            {"e": start.encounter_id},
        ).scalar()
        assert round_count == 0, "a round row survived a rolled-back resolve_combat_turn"
