"""Movement, hazard trigger/disarm, mechanism activation, and discovery —
the command-layer mechanics docs/PLAN.md §25 steps 7-11 need that no
earlier phase built (`dnd_ai.commands.movement.enter_location`, and the
new consequence handlers in `dnd_ai.commands.interactions.resolve_check`).

Covers the production risk directly: state transitions, event/effect
pairing, and the discovery join's exact eligibility rule (hidden, a
matching `knowledge.knowledge_items` row, not already discovered, a
successful check, and a supplied `party_id`) — not exhaustive
combinatorics of every interaction type against every target kind.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.interactions import (
    CheckRequestSpec,
    TargetSpec,
    perform_interaction,
    resolve_check,
)
from dnd_ai.commands.movement import enter_location
from tests.factories import (
    make_ability,
    make_area_hazard,
    make_area_interactable,
    make_character,
    make_dungeon,
    make_dungeon_area,
    make_knowledge_item,
    make_party,
    make_ruleset_version_for_world,
    make_skill,
    make_timeline,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.scenario


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.world_time_1 = make_world_time(connection, self.world_id, 100)
        self.world_time_2 = make_world_time(connection, self.world_id, 200)
        self.dungeon_id = make_dungeon(connection, self.world_id)
        self.area_a = make_dungeon_area(connection, self.dungeon_id, name="Entry Hall")
        self.area_b = make_dungeon_area(connection, self.dungeon_id, name="Vault")
        self.actor_id = make_character(connection, self.world_id, name="Rin")
        self.party_id = make_party(connection, self.world_id)

        ruleset_version_id = make_ruleset_version_for_world(connection, self.world_id)
        self.ability_id = make_ability(connection, ruleset_version_id)
        self.skill_id = make_skill(connection, ruleset_version_id, self.ability_id)


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"dungeon-mechanics-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("""
                DELETE FROM knowledge.party_discoveries WHERE timeline_id = :t
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM campaign.character_location_history WHERE timeline_id = :t
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM campaign.hazard_state WHERE timeline_id = :t
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM campaign.interactable_state WHERE timeline_id = :t
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM interaction.interactions WHERE timeline_id = :t
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )


# ---------------------------------------------------------------------------
# enter_location
# ---------------------------------------------------------------------------


def test_entering_a_location_records_movement_and_is_idempotent(
    postgres_engine: Engine, f: Fixture
) -> None:
    result = enter_location(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_1,
        character_id=f.actor_id,
        location_id=f.area_a,
    )
    assert result.moved is True
    assert result.event_id is not None

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT location_id, departed_at_world_time_id
                FROM campaign.character_location_history
                WHERE character_location_history_id = :h
            """),
            {"h": result.character_location_history_id},
        ).one()
        assert row.location_id == f.area_a
        assert row.departed_at_world_time_id is None

        effect = verify.execute(
            text("""
                SELECT target_entity_id, target_component, new_value
                FROM narrative.event_effects WHERE event_id = :e
            """),
            {"e": result.event_id},
        ).one()
        assert effect.target_entity_id == f.actor_id
        assert effect.target_component == "current_location_id"

    replay = enter_location(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_1,
        character_id=f.actor_id,
        location_id=f.area_a,
    )
    assert replay.moved is False
    assert replay.event_id is None
    assert replay.character_location_history_id == result.character_location_history_id


def test_entering_a_new_location_closes_the_previous_one(
    postgres_engine: Engine, f: Fixture
) -> None:
    first = enter_location(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_1,
        character_id=f.actor_id,
        location_id=f.area_a,
    )
    second = enter_location(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_2,
        character_id=f.actor_id,
        location_id=f.area_b,
    )
    assert second.moved is True

    with postgres_engine.connect() as verify:
        first_row = verify.execute(
            text(
                "SELECT departed_at_world_time_id FROM campaign.character_location_history "
                "WHERE character_location_history_id = :h"
            ),
            {"h": first.character_location_history_id},
        ).one()
        assert first_row.departed_at_world_time_id == f.world_time_2

        second_row = verify.execute(
            text(
                "SELECT location_id, departed_at_world_time_id "
                "FROM campaign.character_location_history WHERE character_location_history_id = :h"
            ),
            {"h": second.character_location_history_id},
        ).one()
        assert second_row.location_id == f.area_b
        assert second_row.departed_at_world_time_id is None


# ---------------------------------------------------------------------------
# resolve_check — hazard trigger/disarm
# ---------------------------------------------------------------------------


def _perform_hazard_check(
    postgres_engine: Engine, f: Fixture, hazard_id: uuid.UUID, interaction_type_code: str
) -> uuid.UUID:
    result = perform_interaction(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_1,
        actor_entity_id=f.actor_id,
        interaction_type_code=interaction_type_code,
        action_description="Rin works at the trap.",
        targets=(TargetSpec(target_area_hazard_id=hazard_id),),
        check_requests=(
            CheckRequestSpec(
                check_kind="skill_check", difficulty=15, skill_id=f.skill_id, target_index=0
            ),
        ),
    )
    return result.check_request_ids[0]


def test_a_successful_disarm_disarms_the_hazard(postgres_engine: Engine, f: Fixture) -> None:
    with postgres_engine.begin() as connection:
        hazard_id = make_area_hazard(connection, f.area_a)

    check_request_id = _perform_hazard_check(postgres_engine, f, hazard_id, "disarm_trap")
    result = resolve_check(
        postgres_engine,
        check_request_id=check_request_id,
        roll=18,
        total_modifier=2,
        total=20,
        degree_of_success="success",
    )
    assert result.hazard_status_code == "disarmed"
    assert result.event_id is not None

    with postgres_engine.connect() as verify:
        status = verify.execute(
            text("""
                SELECT hs.code FROM campaign.hazard_state hst
                JOIN campaign.hazard_statuses hs ON hs.hazard_status_id = hst.hazard_status_id
                WHERE hst.timeline_id = :t AND hst.area_hazard_id = :h
            """),
            {"t": f.timeline_id, "h": hazard_id},
        ).scalar()
        assert status == "disarmed"

        event_type = verify.execute(
            text("""
                SELECT et.code FROM narrative.events ev
                JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id
                WHERE ev.event_id = :e
            """),
            {"e": result.event_id},
        ).scalar()
        assert event_type == "hazard_disarmed"


def test_a_failed_disarm_triggers_the_hazard(postgres_engine: Engine, f: Fixture) -> None:
    with postgres_engine.begin() as connection:
        hazard_id = make_area_hazard(connection, f.area_a)

    check_request_id = _perform_hazard_check(postgres_engine, f, hazard_id, "disarm_trap")
    result = resolve_check(
        postgres_engine,
        check_request_id=check_request_id,
        roll=2,
        total_modifier=2,
        total=4,
        degree_of_success="failure",
    )
    assert result.hazard_status_code == "triggered"

    with postgres_engine.connect() as verify:
        event_type = verify.execute(
            text("""
                SELECT et.code FROM narrative.events ev
                JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id
                WHERE ev.event_id = :e
            """),
            {"e": result.event_id},
        ).scalar()
        assert event_type == "hazard_triggered"


# ---------------------------------------------------------------------------
# resolve_check — mechanism activation
# ---------------------------------------------------------------------------


def test_activating_a_mechanism_succeeds(postgres_engine: Engine, f: Fixture) -> None:
    with postgres_engine.begin() as connection:
        interactable_id = make_area_interactable(connection, f.area_a)

    result_perform = perform_interaction(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_1,
        actor_entity_id=f.actor_id,
        interaction_type_code="activate_mechanism",
        targets=(TargetSpec(target_area_interactable_id=interactable_id),),
        check_requests=(
            CheckRequestSpec(
                check_kind="skill_check", difficulty=10, skill_id=f.skill_id, target_index=0
            ),
        ),
    )
    result = resolve_check(
        postgres_engine,
        check_request_id=result_perform.check_request_ids[0],
        roll=15,
        total_modifier=1,
        total=16,
        degree_of_success="success",
    )
    assert result.interactable_activated is True

    with postgres_engine.connect() as verify:
        status = verify.execute(
            text("""
                SELECT ist.code FROM campaign.interactable_state ins
                JOIN campaign.interactable_statuses ist
                    ON ist.interactable_status_id = ins.interactable_status_id
                WHERE ins.timeline_id = :t AND ins.area_interactable_id = :i
            """),
            {"t": f.timeline_id, "i": interactable_id},
        ).scalar()
        assert status == "activated"


# ---------------------------------------------------------------------------
# resolve_check — discovery
# ---------------------------------------------------------------------------


def test_a_successful_check_discovers_a_hidden_hazard_with_a_matching_knowledge_item(
    postgres_engine: Engine, f: Fixture
) -> None:
    with postgres_engine.begin() as connection:
        hazard_id = make_area_hazard(connection, f.area_a, is_hidden=True)
        knowledge_item_id = make_knowledge_item(
            connection, f.world_id, subject_area_hazard_id=hazard_id
        )

    check_request_id = _perform_hazard_check(postgres_engine, f, hazard_id, "search")
    result = resolve_check(
        postgres_engine,
        check_request_id=check_request_id,
        roll=18,
        total_modifier=2,
        total=20,
        degree_of_success="success",
        party_id=f.party_id,
    )
    assert result.discovered_knowledge_item_id == knowledge_item_id
    assert result.discovery_event_id is not None

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT party_id, discovered_via_interaction_id
                FROM knowledge.party_discoveries WHERE knowledge_item_id = :k
            """),
            {"k": knowledge_item_id},
        ).one()
        assert row.party_id == f.party_id
        assert row.discovered_via_interaction_id is not None

        event_type = verify.execute(
            text("""
                SELECT et.code FROM narrative.events ev
                JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id
                WHERE ev.event_id = :e
            """),
            {"e": result.discovery_event_id},
        ).scalar()
        assert event_type == "knowledge_revealed"


def test_discovery_requires_a_matching_knowledge_item(postgres_engine: Engine, f: Fixture) -> None:
    with postgres_engine.begin() as connection:
        hazard_id = make_area_hazard(connection, f.area_a, is_hidden=True)

    check_request_id = _perform_hazard_check(postgres_engine, f, hazard_id, "search")
    result = resolve_check(
        postgres_engine,
        check_request_id=check_request_id,
        roll=18,
        total_modifier=2,
        total=20,
        degree_of_success="success",
        party_id=f.party_id,
    )
    assert result.discovered_knowledge_item_id is None
    assert result.discovery_event_id is None


def test_discovery_requires_a_party_id(postgres_engine: Engine, f: Fixture) -> None:
    with postgres_engine.begin() as connection:
        hazard_id = make_area_hazard(connection, f.area_a, is_hidden=True)
        make_knowledge_item(connection, f.world_id, subject_area_hazard_id=hazard_id)

    check_request_id = _perform_hazard_check(postgres_engine, f, hazard_id, "search")
    result = resolve_check(
        postgres_engine,
        check_request_id=check_request_id,
        roll=18,
        total_modifier=2,
        total=20,
        degree_of_success="success",
    )
    assert result.discovered_knowledge_item_id is None


def test_discovery_is_not_recorded_twice_for_the_same_party(
    postgres_engine: Engine, f: Fixture
) -> None:
    with postgres_engine.begin() as connection:
        hazard_id = make_area_hazard(connection, f.area_a, is_hidden=True)
        make_knowledge_item(connection, f.world_id, subject_area_hazard_id=hazard_id)

    first_check = _perform_hazard_check(postgres_engine, f, hazard_id, "search")
    first = resolve_check(
        postgres_engine,
        check_request_id=first_check,
        roll=18,
        total_modifier=2,
        total=20,
        degree_of_success="success",
        party_id=f.party_id,
    )
    assert first.discovered_knowledge_item_id is not None

    second_check = _perform_hazard_check(postgres_engine, f, hazard_id, "search")
    second = resolve_check(
        postgres_engine,
        check_request_id=second_check,
        roll=18,
        total_modifier=2,
        total=20,
        degree_of_success="success",
        party_id=f.party_id,
    )
    assert second.discovered_knowledge_item_id is None
    assert second.discovery_event_id is None

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text(
                "SELECT count(*) FROM knowledge.party_discoveries "
                "WHERE timeline_id = :t AND party_id = :p"
            ),
            {"t": f.timeline_id, "p": f.party_id},
        ).scalar()
        assert count == 1


def test_a_successful_check_discovers_a_restricted_fact_about_an_entity(
    postgres_engine: Engine, f: Fixture
) -> None:
    """docs/PLAN.md §25 step 13: "talk to the NPC and receive restricted
    knowledge" — target_entity_id has no is_hidden gate (an NPC's own
    existence is never secret), unlike the four structural-child kinds."""
    with postgres_engine.begin() as connection:
        npc_id = make_character(connection, f.world_id, name="Villager")
        knowledge_item_id = make_knowledge_item(connection, f.world_id, subject_entity_id=npc_id)

    result_perform = perform_interaction(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_1,
        actor_entity_id=f.actor_id,
        interaction_type_code="converse",
        targets=(TargetSpec(target_entity_id=npc_id),),
        check_requests=(
            CheckRequestSpec(
                check_kind="skill_check", difficulty=10, skill_id=f.skill_id, target_index=0
            ),
        ),
    )
    result = resolve_check(
        postgres_engine,
        check_request_id=result_perform.check_request_ids[0],
        roll=15,
        total_modifier=1,
        total=16,
        degree_of_success="success",
        party_id=f.party_id,
    )
    assert result.discovered_knowledge_item_id == knowledge_item_id


def test_a_failed_search_does_not_discover_the_hidden_hazard(
    postgres_engine: Engine, f: Fixture
) -> None:
    with postgres_engine.begin() as connection:
        hazard_id = make_area_hazard(connection, f.area_a, is_hidden=True)
        make_knowledge_item(connection, f.world_id, subject_area_hazard_id=hazard_id)

    check_request_id = _perform_hazard_check(postgres_engine, f, hazard_id, "search")
    result = resolve_check(
        postgres_engine,
        check_request_id=check_request_id,
        roll=2,
        total_modifier=2,
        total=4,
        degree_of_success="failure",
        party_id=f.party_id,
    )
    assert result.discovered_knowledge_item_id is None
