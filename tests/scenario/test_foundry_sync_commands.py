"""apply_foundry_combat_sync(): an inbound Foundry-style combat payload
updates persistent character state entirely through the command layer —
never a direct table write (rule 3) — with integration.sync_jobs/.
sync_state/.delivery_attempts recording the adapter-facing bookkeeping
around it (docs/PLAN.md Phase 9's replanned exit criteria). Required
scenario test per docs/DATABASE_CONVENTIONS.md §32.2.

Mirrors dnd_ai.commands.encounters' own scenario test: build a concrete
scenario, drive it through the real command, and verify the recorded
event/state change plus the sync bookkeeping — not by inspecting the
transaction boundary.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.encounters import start_encounter
from dnd_ai.commands.integration import (
    apply_foundry_combat_sync,
    map_external_identifier,
    register_external_system,
)
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
            current_hit_points=15,
            maximum_hit_points=15,
        )


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"foundry-sync-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )


def test_an_inbound_foundry_combat_payload_updates_persistent_state(
    postgres_engine: Engine, f: Fixture
) -> None:
    """The exit criterion's core claim, short of a live deployment: an
    adapter-facing command routes a combat payload through the real
    resolve_combat_turn(), never a raw write, and the sync job/state
    bookkeeping reflects it."""
    system = register_external_system(
        postgres_engine, world_id=f.world_id, system_type="foundry", display_name="Test Foundry"
    )
    map_external_identifier(
        postgres_engine,
        external_system_id=system.external_system_id,
        entity_id=f.attacker_id,
        external_kind="actor",
        external_id="foundry-actor-1",
    )

    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    result = apply_foundry_combat_sync(
        postgres_engine,
        external_system_id=system.external_system_id,
        encounter_id=start.encounter_id,
        round_number=1,
        turn_order=0,
        actor_entity_id=f.attacker_id,
        world_time_id=f.world_time_id,
        target_entity_id=f.defender_id,
        hit=True,
        damage_amount=6,
        raw_payload={"foundry_combat_id": "combat-1", "damage": 6},
    )

    assert result.combat_result.new_hit_points == 9
    assert result.combat_result.event_id is not None

    with postgres_engine.connect() as verify:
        job_row = verify.execute(
            text("""
                SELECT status, resulting_event_id, target_encounter_id, payload_jsonb
                FROM integration.sync_jobs WHERE sync_job_id = :j
            """),
            {"j": result.sync_job_id},
        ).one()
        assert job_row.status == "completed"
        assert job_row.resulting_event_id == result.combat_result.event_id
        assert job_row.target_encounter_id == start.encounter_id
        assert job_row.payload_jsonb == {"foundry_combat_id": "combat-1", "damage": 6}

        attempt_row = verify.execute(
            text("""
                SELECT succeeded FROM integration.delivery_attempts
                WHERE sync_job_id = :j AND attempt_number = 1
            """),
            {"j": result.sync_job_id},
        ).one()
        assert attempt_row.succeeded is True

        state_row = verify.execute(
            text("""
                SELECT sync_status, last_sync_job_id FROM integration.sync_state
                WHERE external_system_id = :s AND target_encounter_id = :e
            """),
            {"s": system.external_system_id, "e": start.encounter_id},
        ).one()
        assert state_row.sync_status == "synced"
        assert state_row.last_sync_job_id == result.sync_job_id

        hp_row = verify.execute(
            text("""
                SELECT current_hit_points FROM campaign.character_state
                WHERE timeline_id = :t AND character_id = :c
            """),
            {"t": f.timeline_id, "c": f.defender_id},
        ).one()
        assert hp_row.current_hit_points == 9

        cause_row = verify.execute(
            text("SELECT cause_encounter_id FROM narrative.event_causes WHERE event_id = :e"),
            {"e": result.combat_result.event_id},
        ).one()
        assert cause_row.cause_encounter_id == start.encounter_id


def test_re_registering_the_same_external_actor_is_idempotent(
    postgres_engine: Engine, f: Fixture
) -> None:
    system = register_external_system(
        postgres_engine, world_id=f.world_id, system_type="foundry", display_name="Test Foundry"
    )

    first = map_external_identifier(
        postgres_engine,
        external_system_id=system.external_system_id,
        entity_id=f.attacker_id,
        external_kind="actor",
        external_id="foundry-actor-1",
    )
    second = map_external_identifier(
        postgres_engine,
        external_system_id=system.external_system_id,
        entity_id=f.attacker_id,
        external_kind="actor",
        external_id="foundry-actor-1",
    )

    assert first.external_identifier_id == second.external_identifier_id

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text(
                "SELECT count(*) FROM integration.external_identifiers "
                "WHERE external_system_id = :s"
            ),
            {"s": system.external_system_id},
        ).scalar()
        assert count == 1
