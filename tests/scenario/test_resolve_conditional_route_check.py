"""perform_interaction + resolve_check: a player action resolves into an
event and an atomic state change (Phase 6 exit criteria).

docs/PLAN.md's Phase 6 exit criteria require: "A player action can resolve
into an event and atomic state changes," "current state and event history
remain consistent," and "a failure partway through a multi-domain command
leaves no partial write — proven by a test that forces the failure, not by
inspecting the transaction boundary." Increment 1 proved the schema supports
atomicity with hand-written SQL (tests/database/test_event_state_atomicity.py);
this is the first time it is proven through actual application code
(dnd_ai.commands.interactions), against the concrete scenario Phase 6's
"wire up conditional-route evaluation" obligation names: a party member picks
a lock, the check succeeds, the door opens.

The forced-failure test injects a fault via monkeypatch rather than a
naturally arising constraint violation. A genuinely reachable third-step
failure was considered (mismatched-world target, duplicate check submission)
and rejected: interaction.enforce_target_world() already guarantees a
target's area_connection is same-world as the check by the time resolve_check
runs, and a duplicate check_result submission fails at step one, before any
event/state work happens, proving nothing about a later-step rollback. The
injected fault stands in for any real downstream failure (a constraint this
schema doesn't yet enforce, a future validation step) while exercising the
real engine.begin() rollback path around real, unmodified production code.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.interactions import (
    CheckRequestSpec,
    PerformInteractionResult,
    TargetSpec,
    perform_interaction,
    resolve_check,
)
from tests.factories import (
    make_ability,
    make_area_connection,
    make_character,
    make_dungeon,
    make_dungeon_area,
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
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        self.dungeon_id = make_dungeon(connection, self.world_id)
        self.area_a = make_dungeon_area(connection, self.dungeon_id, name="Entry Hall")
        self.area_b = make_dungeon_area(connection, self.dungeon_id, name="Vault")
        self.connection_id = make_area_connection(connection, self.area_a, self.area_b)
        self.actor_id = make_character(connection, self.world_id, name="Rin")
        ruleset_version_id = make_ruleset_version_for_world(connection, self.world_id)
        self.ability_id = make_ability(connection, ruleset_version_id)
        self.skill_id = make_skill(connection, ruleset_version_id, self.ability_id)
        connection.execute(
            text(
                "UPDATE world.area_connections SET is_conditional = true, "
                "condition_description = 'locked until picked', required_check_kind = 'skill_check', "
                "required_skill_id = :s, required_difficulty = 15 WHERE area_connection_id = :c"
            ),
            {"s": self.skill_id, "c": self.connection_id},
        )


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"resolve-check-scenario-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        # campaign.area_connection_state.last_event_id (ON DELETE SET NULL
        # from narrative.events) and .area_connection_id (ON DELETE CASCADE
        # from world.area_connections, itself cascaded from the entities
        # delete below via dungeon_areas) both converge on this table from
        # the same entities-cascade sweep — deleting it explicitly first
        # avoids depending on which cascade path Postgres processes first.
        cleanup.execute(
            text("""
                DELETE FROM campaign.area_connection_state WHERE timeline_id = :t
            """),
            {"t": fixture.timeline_id},
        )
        # Entities next: cascades away narrative.events (and event_causes,
        # which must be gone before interactions are deleted below, since
        # event_causes.cause_interaction_id is ON DELETE SET NULL and would
        # otherwise violate ck_event_causes_has_cause on a cause-only row).
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        # interaction.interactions.world_time_id is ON DELETE RESTRICT, and
        # core.worlds cascades to core.world_times independently of the
        # timeline_id cascade path that would otherwise remove interactions
        # first — delete interactions explicitly so the two cascade paths
        # can't race.
        cleanup.execute(
            text("""
                DELETE FROM interaction.interactions
                WHERE timeline_id IN (SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)
            """),
            {"w": fixture.world_id},
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )


def _perform_pick_lock(postgres_engine: Engine, f: Fixture) -> PerformInteractionResult:
    return perform_interaction(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        actor_entity_id=f.actor_id,
        interaction_type_code="pick_lock",
        action_description="Rin picks the vault door's lock.",
        targets=(TargetSpec(target_area_connection_id=f.connection_id),),
        check_requests=(
            CheckRequestSpec(
                check_kind="skill_check",
                difficulty=15,
                skill_id=f.skill_id,
                target_index=0,
            ),
        ),
    )


def _connection_state(postgres_engine: Engine, f: Fixture) -> tuple[str, uuid.UUID] | None:
    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT cs.code, acs.last_event_id
                FROM campaign.area_connection_state acs
                JOIN campaign.connection_statuses cs
                    ON cs.connection_status_id = acs.connection_status_id
                WHERE acs.timeline_id = :t AND acs.area_connection_id = :c
            """),
            {"t": f.timeline_id, "c": f.connection_id},
        ).one_or_none()
    return (row.code, row.last_event_id) if row is not None else None


def test_a_successful_lockpick_check_opens_the_route_and_records_an_event(
    postgres_engine: Engine, f: Fixture
) -> None:
    interaction_result = _perform_pick_lock(postgres_engine, f)

    resolve_result = resolve_check(
        postgres_engine,
        check_request_id=interaction_result.check_request_ids[0],
        roll=18,
        total_modifier=2,
        total=20,
        degree_of_success="success",
    )

    assert resolve_result.event_id is not None
    assert resolve_result.area_connection_opened is True

    with postgres_engine.connect() as verify:
        event_row = verify.execute(
            text("""
                SELECT et.code AS type_code
                FROM narrative.events ev
                JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id
                WHERE ev.event_id = :e
            """),
            {"e": resolve_result.event_id},
        ).one()
        assert event_row.type_code == "mechanism_activated"

        cause_interaction = verify.execute(
            text("SELECT cause_interaction_id FROM narrative.event_causes WHERE event_id = :e"),
            {"e": resolve_result.event_id},
        ).scalar()
        assert cause_interaction == interaction_result.interaction_id

        participant = verify.execute(
            text(
                "SELECT participant_entity_id FROM narrative.event_participants WHERE event_id = :e"
            ),
            {"e": resolve_result.event_id},
        ).scalar()
        assert participant == f.actor_id

        effect = verify.execute(
            text("""
                SELECT target_component, previous_value, new_value
                FROM narrative.event_effects WHERE event_id = :e
            """),
            {"e": resolve_result.event_id},
        ).one()
        assert effect.target_component == "connection_status_id"
        assert effect.previous_value is None
        assert effect.new_value == "open"

    state = _connection_state(postgres_engine, f)
    assert state is not None
    status_code, last_event_id = state
    assert status_code == "open"
    assert last_event_id == resolve_result.event_id


def test_a_failed_lockpick_check_does_not_open_the_route_or_record_an_event(
    postgres_engine: Engine, f: Fixture
) -> None:
    interaction_result = _perform_pick_lock(postgres_engine, f)

    resolve_result = resolve_check(
        postgres_engine,
        check_request_id=interaction_result.check_request_ids[0],
        roll=3,
        total_modifier=2,
        total=5,
        degree_of_success="failure",
    )

    assert resolve_result.event_id is None
    assert resolve_result.area_connection_opened is False
    assert _connection_state(postgres_engine, f) is None


def test_a_failure_partway_through_resolve_check_leaves_no_partial_write(
    postgres_engine: Engine, f: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    interaction_result = _perform_pick_lock(postgres_engine, f)
    check_request_id = interaction_result.check_request_ids[0]

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated downstream failure")

    monkeypatch.setattr("dnd_ai.commands.interactions._open_area_connection", _boom)

    with pytest.raises(RuntimeError, match="simulated downstream failure"):
        resolve_check(
            postgres_engine,
            check_request_id=check_request_id,
            roll=18,
            total_modifier=2,
            total=20,
            degree_of_success="success",
        )

    with postgres_engine.connect() as verify:
        check_result_count = verify.execute(
            text("SELECT count(*) FROM interaction.check_results WHERE check_request_id = :r"),
            {"r": check_request_id},
        ).scalar()
        assert check_result_count == 0, "check_results survived a rolled-back resolve_check"

        event_count = verify.execute(
            text("SELECT count(*) FROM narrative.events WHERE timeline_id = :t"),
            {"t": f.timeline_id},
        ).scalar()
        assert event_count == 0, "an event survived a rolled-back resolve_check"

    assert _connection_state(postgres_engine, f) is None, (
        "area_connection_state survived a rolled-back resolve_check"
    )
