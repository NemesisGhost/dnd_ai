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

Also covers the idempotency/concurrency/failure-bookkeeping correction
pass recorded in docs/PHASE9_VERIFICATION.md: replaying the same
external_operation_id, two genuinely concurrent submissions of the same
operation, a conflicting-payload replay, and a failed combat sync leaving
domain state untouched while still recording the failure.

A second correction pass (docs/PHASE9_VERIFICATION.md's "atomic completion"
note) closed a gap the first pass left: apply_foundry_combat_sync() used
to commit the domain mutation and _complete_sync_job() as two separate
transactions, so a failure completing the sync job left the mutation
committed anyway. test_a_completion_failure_rolls_back_the_domain_mutation
proves the fix — a failure injected into _complete_sync_job() (via
monkeypatch, the same fault-injection idiom
test_resolve_conditional_route_check.py already established for this
project) after the combat statements have executed rolls back the turn,
action, event, effect, and HP change together with it.
test_two_different_operations_for_the_same_encounter_complete_independently
proves the atomic sync_state upsert this same pass introduced: two
genuinely concurrent operations racing for the same encounter's sync_state
row do not fail spuriously or produce two current rows.

A third correction pass (docs/PHASE9_VERIFICATION.md's "single-connection"
note) closed a connection-pool deadlock the second pass introduced: the
claim/work/fail transactions each opened their own pooled connection via
engine.begin() while the advisory-lock connection sat idle, so a caller
waiting on the lock could exhaust a small pool and leave the lock holder
unable to obtain a connection for its own steps.
test_a_small_pool_does_not_deadlock_a_single_call and
test_two_operations_on_the_same_target_do_not_starve_a_small_pool prove
the fix (everything now runs on the one lock-holding connection) against
an engine with pool_size=1. That pass also hardened advisory-lock release:
if the unlock cannot be confirmed, the connection is invalidated rather
than returned to the pool, so a still-held session-scoped lock can never
be silently inherited by a future caller —
test_an_unlock_failure_invalidates_the_connection_and_a_later_call_does_not_block
proves both halves of that.

A fourth correction pass closed a leftover half-step in that same cleanup
path: invalidate() discards the underlying DBAPI connection but doesn't
itself finalize the SQLAlchemy Connection wrapper, so the unconfirmed-
unlock branch now calls close() immediately afterward too.
test_an_unlock_failure_invalidates_the_connection_and_a_later_call_does_not_block
was extended with a second spy proving close() is called exactly once, on
the same connection object invalidate() was called on.

A fifth correction pass made cleanup exception-safe on every remaining
branch and extracted the whole thing into _release_lock_connection() (see
its own docstring for the full state machine). Two gaps remained: (1) the
confirmed-unlock path's close() ran unguarded, so a close() failure could
replace an exception already propagating from claim/work/failure
processing — test_a_close_failure_after_confirmed_unlock_does_not_mask_a_domain_exception
proves it no longer can, by injecting both a real domain failure and a
close() failure simultaneously and asserting only the domain exception
surfaces; (2) a failed invalidate() fell through to an ordinary close(),
which — since invalidate() never got to discard the DBAPI connection —
would return a possibly still lock-owning physical session straight back
to the pool. detach() (the documented SQLAlchemy mechanism for severing a
Connection from its pool's rotation) is now tried as a fallback so the
close() that follows physically closes the connection instead of
recycling it —
test_an_invalidate_failure_falls_back_to_detach_and_a_later_call_does_not_block
proves the fallback fires, confirms via a direct pg_try_advisory_lock
probe that the lock is genuinely free at the PostgreSQL level afterward
(not just that spied methods were called), and proves a same-operation-id
replay completes rather than blocking.

A sixth correction pass closed the final edge in that same fallback: if
detach() *also* raised (not just invalidate()), the connection was still
attached to the pool, so the unconditional close() that followed could
still return a possibly lock-owning session back into rotation — the
exact outcome the whole state machine exists to prevent, this time via
the fallback's own fallback. _release_lock_connection() now tracks
whether detach() actually succeeded and only calls close() when it did;
if both invalidate() and detach() raise, no close() is called at all.

A seventh correction pass found that merely not calling close() is not,
by itself, a guarantee: once apply_foundry_combat_sync() returns and its
local lock_connection reference goes out of scope, an unreferenced
Connection becomes eligible for garbage collection, and SQLAlchemy's
pooled-connection wrapper can implement a finalizer that returns a
never-explicitly-closed connection to the pool anyway — reaching the
exact outcome this state machine exists to prevent via Python's own
memory management rather than an explicit close() call.
_quarantine_lock_connection() (see its own docstring in
dnd_ai/commands/integration.py) closes this: the double-invalidate/detach
failure branch now hands the connection to a private, thread-safe,
process-lifetime quarantine list that holds a strong reference to it, so
it can never be garbage-collected, logging at CRITICAL so the resulting
leaked pool capacity is operationally visible rather than a silent,
slow leak. test_a_double_failure_after_invalidate_and_detach_fail_quarantines_the_connection
proves the full guarantee, not just the absence of a close() call:
close() is never invoked; the exact connection object is present by
identity in the quarantine list after the call returns; and — after
dropping the test's own reference and running gc.collect() — a weakref
to the connection is still alive, proving the quarantine itself, not an
incidental leftover reference, is what keeps it alive. The test restores
the real SQLAlchemy methods and genuinely disposes of the connection in a
`finally` block, so it leaves no quarantined connection, leaked pool
slot, or held advisory lock behind for any other test.
"""

import contextlib
import gc
import threading
import time
import uuid
import weakref
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, create_engine, text

from dnd_ai.commands import integration as integration_module
from dnd_ai.commands.encounters import start_encounter
from dnd_ai.commands.integration import (
    ApplyFoundryCombatSyncResult,
    ConflictingSyncPayloadError,
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
        external_operation_id="foundry-combat-1-turn-1",
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

    assert result.replayed is False
    assert result.combat_result.new_hit_points == 9
    assert result.combat_result.event_id is not None

    with postgres_engine.connect() as verify:
        job_row = verify.execute(
            text("""
                SELECT status, resulting_event_id, resulting_encounter_turn_id,
                       target_encounter_id, payload_jsonb
                FROM integration.sync_jobs WHERE sync_job_id = :j
            """),
            {"j": result.sync_job_id},
        ).one()
        assert job_row.status == "completed"
        assert job_row.resulting_event_id == result.combat_result.event_id
        assert job_row.resulting_encounter_turn_id == result.combat_result.encounter_turn_id
        assert job_row.target_encounter_id == start.encounter_id
        assert job_row.payload_jsonb["raw_payload"] == {
            "foundry_combat_id": "combat-1",
            "damage": 6,
        }

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


def _row_counts(postgres_engine: Engine, timeline_id: uuid.UUID, sync_job_id: uuid.UUID) -> dict:
    with postgres_engine.connect() as verify:
        return {
            "encounter_turns": verify.execute(
                text("""
                    SELECT count(*) FROM narrative.encounter_turns et
                    JOIN narrative.encounter_rounds er ON er.encounter_round_id = et.encounter_round_id
                    JOIN narrative.encounters e ON e.encounter_id = er.encounter_id
                    WHERE e.timeline_id = :t
                """),
                {"t": timeline_id},
            ).scalar(),
            "combat_damage_events": verify.execute(
                text("""
                    SELECT count(*) FROM narrative.events ev
                    JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id
                    WHERE et.code = 'combat_damage_dealt' AND ev.timeline_id = :t
                """),
                {"t": timeline_id},
            ).scalar(),
            "sync_jobs": verify.execute(
                text("SELECT count(*) FROM integration.sync_jobs WHERE sync_job_id = :j"),
                {"j": sync_job_id},
            ).scalar(),
            "delivery_attempts": verify.execute(
                text("SELECT count(*) FROM integration.delivery_attempts WHERE sync_job_id = :j"),
                {"j": sync_job_id},
            ).scalar(),
        }


def test_replaying_the_same_operation_returns_the_original_result_without_duplicating_work(
    postgres_engine: Engine, f: Fixture
) -> None:
    system = register_external_system(
        postgres_engine, world_id=f.world_id, system_type="foundry", display_name="Test Foundry"
    )
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    kwargs = {
        "external_system_id": system.external_system_id,
        "external_operation_id": "replay-op-1",
        "encounter_id": start.encounter_id,
        "round_number": 1,
        "turn_order": 0,
        "actor_entity_id": f.attacker_id,
        "world_time_id": f.world_time_id,
        "target_entity_id": f.defender_id,
        "hit": True,
        "damage_amount": 6,
    }

    first = apply_foundry_combat_sync(postgres_engine, **kwargs)
    second = apply_foundry_combat_sync(postgres_engine, **kwargs)

    assert first.replayed is False
    assert second.replayed is True
    assert second.sync_job_id == first.sync_job_id
    assert second.combat_result == first.combat_result
    assert _character_hit_points(postgres_engine, f.timeline_id, f.defender_id) == 9

    counts = _row_counts(postgres_engine, f.timeline_id, first.sync_job_id)
    assert counts["encounter_turns"] == 1
    assert counts["combat_damage_events"] == 1
    assert counts["sync_jobs"] == 1
    assert counts["delivery_attempts"] == 1


def test_concurrent_submissions_of_the_same_operation_apply_damage_exactly_once(
    postgres_engine: Engine, f: Fixture
) -> None:
    """The advisory-lock concurrency guarantee: two genuinely concurrent
    calls with the same external_operation_id must not both execute
    resolve_combat_turn() — exactly one HP mutation, one encounter_turn,
    one event, one sync job, one delivery attempt."""
    system = register_external_system(
        postgres_engine, world_id=f.world_id, system_type="foundry", display_name="Test Foundry"
    )
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    barrier = threading.Barrier(2)
    results: dict[str, ApplyFoundryCombatSyncResult] = {}
    errors: dict[str, Exception] = {}

    def _submit(label: str) -> None:
        barrier.wait(timeout=30)
        try:
            results[label] = apply_foundry_combat_sync(
                postgres_engine,
                external_system_id=system.external_system_id,
                external_operation_id="concurrent-op-1",
                encounter_id=start.encounter_id,
                round_number=1,
                turn_order=0,
                actor_entity_id=f.attacker_id,
                world_time_id=f.world_time_id,
                target_entity_id=f.defender_id,
                hit=True,
                damage_amount=6,
            )
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            errors[label] = exc

    thread_a = threading.Thread(target=_submit, args=("a",))
    thread_b = threading.Thread(target=_submit, args=("b",))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=30)
    thread_b.join(timeout=30)
    assert not thread_a.is_alive(), "apply_foundry_combat_sync for thread a did not finish"
    assert not thread_b.is_alive(), "apply_foundry_combat_sync for thread b did not finish"

    assert not errors, f"expected both calls to serialize cleanly, got errors: {errors}"
    assert len(results) == 2

    sync_job_ids = {r.sync_job_id for r in results.values()}
    assert len(sync_job_ids) == 1, "both callers must resolve to the same sync job"

    replayed_flags = sorted(r.replayed for r in results.values())
    assert replayed_flags == [False, True], "exactly one caller should have done the real work"

    assert _character_hit_points(postgres_engine, f.timeline_id, f.defender_id) == 9

    counts = _row_counts(postgres_engine, f.timeline_id, next(iter(sync_job_ids)))
    assert counts["encounter_turns"] == 1
    assert counts["combat_damage_events"] == 1
    assert counts["sync_jobs"] == 1
    assert counts["delivery_attempts"] == 1


def test_reusing_an_operation_id_with_a_conflicting_payload_raises(
    postgres_engine: Engine, f: Fixture
) -> None:
    system = register_external_system(
        postgres_engine, world_id=f.world_id, system_type="foundry", display_name="Test Foundry"
    )
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    first = apply_foundry_combat_sync(
        postgres_engine,
        external_system_id=system.external_system_id,
        external_operation_id="conflict-op-1",
        encounter_id=start.encounter_id,
        round_number=1,
        turn_order=0,
        actor_entity_id=f.attacker_id,
        world_time_id=f.world_time_id,
        target_entity_id=f.defender_id,
        hit=True,
        damage_amount=6,
    )
    assert first.combat_result.new_hit_points == 9

    with pytest.raises(ConflictingSyncPayloadError):
        apply_foundry_combat_sync(
            postgres_engine,
            external_system_id=system.external_system_id,
            external_operation_id="conflict-op-1",
            encounter_id=start.encounter_id,
            round_number=1,
            turn_order=0,
            actor_entity_id=f.attacker_id,
            world_time_id=f.world_time_id,
            target_entity_id=f.defender_id,
            hit=True,
            damage_amount=9,  # different from the original — this is the conflict
        )

    # The conflicting replay must not have mutated anything.
    assert _character_hit_points(postgres_engine, f.timeline_id, f.defender_id) == 9
    counts = _row_counts(postgres_engine, f.timeline_id, first.sync_job_id)
    assert counts["encounter_turns"] == 1
    assert counts["combat_damage_events"] == 1


def test_a_failed_combat_sync_records_the_failure_and_leaves_domain_state_unchanged(
    postgres_engine: Engine, f: Fixture
) -> None:
    """Item 3's core claim: resolve_combat_turn() raising after the sync
    job was claimed must mark the job failed with a useful error message,
    log a failed delivery attempt, create no sync_state row, and re-raise
    the original exception — while domain state (HP, encounter rows)
    stays untouched, since resolve_combat_turn()'s own transaction rolled
    back."""
    system = register_external_system(
        postgres_engine, world_id=f.world_id, system_type="foundry", display_name="Test Foundry"
    )
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        # Only the attacker joins — the defender is deliberately NOT a
        # participant, so resolve_combat_turn()'s _participant_id() lookup
        # raises ValueError.
        participant_entity_ids=(f.attacker_id,),
    )

    with postgres_engine.connect() as verify:
        events_before = verify.execute(
            text("SELECT count(*) FROM narrative.events WHERE timeline_id = :t"),
            {"t": f.timeline_id},
        ).scalar()

    with pytest.raises(ValueError, match="is not a participant"):
        apply_foundry_combat_sync(
            postgres_engine,
            external_system_id=system.external_system_id,
            external_operation_id="failing-op-1",
            encounter_id=start.encounter_id,
            round_number=1,
            turn_order=0,
            actor_entity_id=f.defender_id,  # not a participant
            world_time_id=f.world_time_id,
            target_entity_id=f.attacker_id,
            hit=True,
            damage_amount=5,
        )

    assert _character_hit_points(postgres_engine, f.timeline_id, f.defender_id) == 15

    with postgres_engine.connect() as verify:
        events_after = verify.execute(
            text("SELECT count(*) FROM narrative.events WHERE timeline_id = :t"),
            {"t": f.timeline_id},
        ).scalar()
        assert events_after == events_before, "no event should survive the failed sync"

        job_row = verify.execute(
            text("""
                SELECT status, error_message, resulting_event_id FROM integration.sync_jobs
                WHERE external_system_id = :s AND external_operation_id = 'failing-op-1'
            """),
            {"s": system.external_system_id},
        ).one()
        assert job_row.status == "failed"
        assert job_row.error_message is not None
        assert "is not a participant" in job_row.error_message
        assert job_row.resulting_event_id is None

        attempt_row = verify.execute(
            text("""
                SELECT succeeded, response_summary FROM integration.delivery_attempts
                WHERE sync_job_id = (
                    SELECT sync_job_id FROM integration.sync_jobs
                    WHERE external_system_id = :s AND external_operation_id = 'failing-op-1'
                )
            """),
            {"s": system.external_system_id},
        ).one()
        assert attempt_row.succeeded is False

        state_count = verify.execute(
            text("""
                SELECT count(*) FROM integration.sync_state
                WHERE external_system_id = :s AND target_encounter_id = :e
            """),
            {"s": system.external_system_id, "e": start.encounter_id},
        ).scalar()
        assert state_count == 0, "a failed sync must not create sync_state"


def test_retrying_a_failed_operation_id_succeeds_and_adds_a_second_delivery_attempt(
    postgres_engine: Engine, f: Fixture
) -> None:
    """A failed job is not a permanent dead end: resubmitting the same
    operation id, once the underlying problem is fixed, retries under the
    same sync_jobs row rather than erroring as a conflict."""
    system = register_external_system(
        postgres_engine, world_id=f.world_id, system_type="foundry", display_name="Test Foundry"
    )
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        # Only the defender joins — the attacker (the intended actor below)
        # is deliberately NOT a participant yet, so the first call fails.
        participant_entity_ids=(f.defender_id,),
    )

    kwargs = {
        "external_system_id": system.external_system_id,
        "external_operation_id": "retry-op-1",
        "encounter_id": start.encounter_id,
        "round_number": 1,
        "turn_order": 0,
        "actor_entity_id": f.attacker_id,
        "world_time_id": f.world_time_id,
        "target_entity_id": f.defender_id,
        "hit": True,
        "damage_amount": 5,
    }

    with pytest.raises(ValueError, match="is not a participant"):
        apply_foundry_combat_sync(postgres_engine, **kwargs)

    # Fix the problem (add the attacker as a participant) and retry the
    # exact same operation id.
    with postgres_engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO narrative.encounter_participants (encounter_id, participant_entity_id)
                VALUES (:encounter, :entity)
            """),
            {"encounter": start.encounter_id, "entity": f.attacker_id},
        )

    result = apply_foundry_combat_sync(postgres_engine, **kwargs)
    assert result.replayed is False
    assert result.combat_result.new_hit_points == 10

    with postgres_engine.connect() as verify:
        job_row = verify.execute(
            text("""
                SELECT status FROM integration.sync_jobs
                WHERE external_system_id = :s AND external_operation_id = 'retry-op-1'
            """),
            {"s": system.external_system_id},
        ).one()
        assert job_row.status == "completed"

        attempt_count = verify.execute(
            text("""
                SELECT count(*) FROM integration.delivery_attempts
                WHERE sync_job_id = :j
            """),
            {"j": result.sync_job_id},
        ).scalar()
        assert attempt_count == 2, (
            "the failed attempt and the successful retry should both be logged"
        )


def test_reusing_a_failed_operations_id_with_a_different_payload_raises_conflict(
    postgres_engine: Engine, f: Fixture
) -> None:
    """Item 4's clarified contract: the payload check runs before status is
    ever consulted, so a failed (not just a completed) prior attempt still
    rejects a differently-shaped resubmission under the same operation id
    rather than silently retrying with new arguments."""
    system = register_external_system(
        postgres_engine, world_id=f.world_id, system_type="foundry", display_name="Test Foundry"
    )
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id,),
    )

    with pytest.raises(ValueError, match="is not a participant"):
        apply_foundry_combat_sync(
            postgres_engine,
            external_system_id=system.external_system_id,
            external_operation_id="failed-then-conflicting-op-1",
            encounter_id=start.encounter_id,
            round_number=1,
            turn_order=0,
            actor_entity_id=f.defender_id,  # not a participant — this fails
            world_time_id=f.world_time_id,
            target_entity_id=f.attacker_id,
            hit=True,
            damage_amount=5,
        )

    with pytest.raises(ConflictingSyncPayloadError):
        apply_foundry_combat_sync(
            postgres_engine,
            external_system_id=system.external_system_id,
            external_operation_id="failed-then-conflicting-op-1",
            encounter_id=start.encounter_id,
            round_number=1,
            turn_order=0,
            actor_entity_id=f.defender_id,
            world_time_id=f.world_time_id,
            target_entity_id=f.attacker_id,
            hit=True,
            damage_amount=9,  # different from the original failed attempt's payload
        )

    with postgres_engine.connect() as verify:
        job_row = verify.execute(
            text("""
                SELECT status FROM integration.sync_jobs
                WHERE external_system_id = :s AND external_operation_id = 'failed-then-conflicting-op-1'
            """),
            {"s": system.external_system_id},
        ).one()
        assert job_row.status == "failed", "the conflicting replay must not have retried"


def test_a_completion_failure_rolls_back_the_domain_mutation(
    postgres_engine: Engine, f: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The atomic-completion guarantee: a failure in _complete_sync_job()
    (injected here, after the combat statements in the same "work"
    transaction have already executed) must roll back the combat turn,
    combat action, event, event effect, and HP change together with it —
    not leave the domain mutation committed against a job that never
    finished. The sync job is still recorded as failed via the separate
    step-3 transaction, and retrying the same operation once the injected
    failure is removed succeeds exactly once."""
    system = register_external_system(
        postgres_engine, world_id=f.world_id, system_type="foundry", display_name="Test Foundry"
    )
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated completion-bookkeeping failure")

    monkeypatch.setattr("dnd_ai.commands.integration._complete_sync_job", _boom)

    kwargs = {
        "external_system_id": system.external_system_id,
        "external_operation_id": "completion-failure-op-1",
        "encounter_id": start.encounter_id,
        "round_number": 1,
        "turn_order": 0,
        "actor_entity_id": f.attacker_id,
        "world_time_id": f.world_time_id,
        "target_entity_id": f.defender_id,
        "hit": True,
        "damage_amount": 6,
    }

    with pytest.raises(RuntimeError, match="simulated completion-bookkeeping failure"):
        apply_foundry_combat_sync(postgres_engine, **kwargs)

    # The domain mutation must have rolled back completely, even though
    # resolve_combat_turn()'s own statements executed without error.
    assert _character_hit_points(postgres_engine, f.timeline_id, f.defender_id) == 15
    with postgres_engine.connect() as verify:
        turn_count = verify.execute(
            text("""
                SELECT count(*) FROM narrative.encounter_turns et
                JOIN narrative.encounter_rounds er ON er.encounter_round_id = et.encounter_round_id
                WHERE er.encounter_id = :e
            """),
            {"e": start.encounter_id},
        ).scalar()
        assert turn_count == 0, "the combat turn must not survive the rolled-back transaction"

        event_count = verify.execute(
            text("""
                SELECT count(*) FROM narrative.events ev
                JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id
                WHERE et.code = 'combat_damage_dealt' AND ev.timeline_id = :t
            """),
            {"t": f.timeline_id},
        ).scalar()
        assert event_count == 0, "the combat event must not survive the rolled-back transaction"

        job_row = verify.execute(
            text("""
                SELECT status, error_message, resulting_event_id FROM integration.sync_jobs
                WHERE external_system_id = :s AND external_operation_id = 'completion-failure-op-1'
            """),
            {"s": system.external_system_id},
        ).one()
        assert job_row.status == "failed"
        assert job_row.error_message is not None
        assert "simulated completion-bookkeeping failure" in job_row.error_message
        assert job_row.resulting_event_id is None

        state_count = verify.execute(
            text("""
                SELECT count(*) FROM integration.sync_state
                WHERE external_system_id = :s AND target_encounter_id = :e
            """),
            {"s": system.external_system_id, "e": start.encounter_id},
        ).scalar()
        assert state_count == 0, "a rolled-back completion must not leave a sync_state row"

    # Remove the injected failure and retry the exact same operation.
    monkeypatch.undo()
    result = apply_foundry_combat_sync(postgres_engine, **kwargs)
    assert result.replayed is False
    assert result.combat_result.new_hit_points == 9
    assert _character_hit_points(postgres_engine, f.timeline_id, f.defender_id) == 9

    with postgres_engine.connect() as verify:
        turn_count = verify.execute(
            text("""
                SELECT count(*) FROM narrative.encounter_turns et
                JOIN narrative.encounter_rounds er ON er.encounter_round_id = et.encounter_round_id
                WHERE er.encounter_id = :e
            """),
            {"e": start.encounter_id},
        ).scalar()
        assert turn_count == 1, "the retry must produce exactly one turn, not a duplicate"

        job_row = verify.execute(
            text("""
                SELECT status FROM integration.sync_jobs
                WHERE external_system_id = :s AND external_operation_id = 'completion-failure-op-1'
            """),
            {"s": system.external_system_id},
        ).one()
        assert job_row.status == "completed"

        attempt_count = verify.execute(
            text("SELECT count(*) FROM integration.delivery_attempts WHERE sync_job_id = :j"),
            {"j": result.sync_job_id},
        ).scalar()
        assert attempt_count == 2, (
            "the failed attempt and the successful retry should both be logged"
        )


def test_two_different_operations_for_the_same_encounter_complete_independently(
    postgres_engine: Engine, f: Fixture
) -> None:
    """Genuine concurrency, different operation ids, same target: two
    distinct Foundry combat turns in the same encounter — different
    actors, so no interaction.encounter_turns collision of their own —
    submitted concurrently, must both complete successfully, each apply
    its own HP change exactly once, and leave exactly one
    integration.sync_state row for (system, encounter), not a spurious
    unique-violation or a duplicate."""
    system = register_external_system(
        postgres_engine, world_id=f.world_id, system_type="foundry", display_name="Test Foundry"
    )
    with postgres_engine.begin() as connection:
        make_character_state(
            connection, f.timeline_id, f.attacker_id, current_hit_points=12, maximum_hit_points=12
        )
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    barrier = threading.Barrier(2)
    results: dict[str, ApplyFoundryCombatSyncResult] = {}
    errors: dict[str, Exception] = {}

    def _submit(label: str, operation_id: str, actor: uuid.UUID, target: uuid.UUID) -> None:
        barrier.wait(timeout=30)
        try:
            results[label] = apply_foundry_combat_sync(
                postgres_engine,
                external_system_id=system.external_system_id,
                external_operation_id=operation_id,
                encounter_id=start.encounter_id,
                round_number=1,
                turn_order=0,
                actor_entity_id=actor,
                world_time_id=f.world_time_id,
                target_entity_id=target,
                hit=True,
                damage_amount=6,
            )
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            errors[label] = exc

    thread_a = threading.Thread(
        target=_submit, args=("a", "distinct-op-a", f.attacker_id, f.defender_id)
    )
    thread_b = threading.Thread(
        target=_submit, args=("b", "distinct-op-b", f.defender_id, f.attacker_id)
    )
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=30)
    thread_b.join(timeout=30)
    assert not thread_a.is_alive(), "apply_foundry_combat_sync for thread a did not finish"
    assert not thread_b.is_alive(), "apply_foundry_combat_sync for thread b did not finish"

    assert not errors, (
        f"expected both distinct operations to complete cleanly, got errors: {errors}"
    )
    assert len(results) == 2
    assert results["a"].replayed is False
    assert results["b"].replayed is False
    assert results["a"].sync_job_id != results["b"].sync_job_id

    # Each domain mutation applied exactly once.
    assert _character_hit_points(postgres_engine, f.timeline_id, f.defender_id) == 9
    assert _character_hit_points(postgres_engine, f.timeline_id, f.attacker_id) == 6

    with postgres_engine.connect() as verify:
        turn_count = verify.execute(
            text("""
                SELECT count(*) FROM narrative.encounter_turns et
                JOIN narrative.encounter_rounds er ON er.encounter_round_id = et.encounter_round_id
                WHERE er.encounter_id = :e
            """),
            {"e": start.encounter_id},
        ).scalar()
        assert turn_count == 2, "each operation should have produced exactly one turn"

        job_rows = verify.execute(
            text("""
                SELECT sync_job_id, status FROM integration.sync_jobs
                WHERE sync_job_id = ANY(:jobs)
            """),
            {"jobs": [results["a"].sync_job_id, results["b"].sync_job_id]},
        ).all()
        assert len(job_rows) == 2
        assert {row.status for row in job_rows} == {"completed"}, "no job should remain in_progress"

        state_rows = verify.execute(
            text("""
                SELECT sync_state_id, last_sync_job_id FROM integration.sync_state
                WHERE external_system_id = :s AND target_encounter_id = :e
            """),
            {"s": system.external_system_id, "e": start.encounter_id},
        ).all()
        assert len(state_rows) == 1, "exactly one current sync_state row must exist, not two"
        assert state_rows[0].last_sync_job_id in {
            results["a"].sync_job_id,
            results["b"].sync_job_id,
        }


def test_a_small_pool_does_not_deadlock_a_single_call(postgres_engine: Engine, f: Fixture) -> None:
    """Connection-budget regression for the third correction pass: the
    earlier design opened a second, independent pooled connection for each
    of the claim/work/fail steps while the advisory-lock connection sat
    idle. Under a pool with only one connection to give out, that second
    connection request would block forever behind the lock holder's own
    idle connection — a self-deadlock with no other caller involved at
    all. An engine with pool_size=1, max_overflow=0, and a short
    pool_timeout proves a single call never needs more than one pooled
    connection for its entire duration."""
    system = register_external_system(
        postgres_engine, world_id=f.world_id, system_type="foundry", display_name="Test Foundry"
    )
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    small_pool_engine = create_engine(
        postgres_engine.url, pool_size=1, max_overflow=0, pool_timeout=5
    )
    try:
        result = apply_foundry_combat_sync(
            small_pool_engine,
            external_system_id=system.external_system_id,
            external_operation_id="small-pool-single-op-1",
            encounter_id=start.encounter_id,
            round_number=1,
            turn_order=0,
            actor_entity_id=f.attacker_id,
            world_time_id=f.world_time_id,
            target_entity_id=f.defender_id,
            hit=True,
            damage_amount=6,
        )
    finally:
        small_pool_engine.dispose()

    assert result.replayed is False
    assert result.combat_result.new_hit_points == 9


def test_two_operations_on_the_same_target_do_not_starve_a_small_pool(
    postgres_engine: Engine, f: Fixture
) -> None:
    """Two genuinely concurrent, distinct operation ids targeting the same
    encounter, run against an engine with only one pooled connection.
    Since each call now needs at most one connection for its whole
    duration, the pool simply serializes the two callers — the second
    blocks briefly waiting for a connection, then proceeds normally —
    rather than either deadlocking or timing out from starvation."""
    system = register_external_system(
        postgres_engine, world_id=f.world_id, system_type="foundry", display_name="Test Foundry"
    )
    with postgres_engine.begin() as connection:
        make_character_state(
            connection, f.timeline_id, f.attacker_id, current_hit_points=12, maximum_hit_points=12
        )
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    small_pool_engine = create_engine(
        postgres_engine.url, pool_size=1, max_overflow=0, pool_timeout=15
    )

    barrier = threading.Barrier(2)
    results: dict[str, ApplyFoundryCombatSyncResult] = {}
    errors: dict[str, Exception] = {}

    def _submit(label: str, operation_id: str, actor: uuid.UUID, target: uuid.UUID) -> None:
        barrier.wait(timeout=30)
        try:
            results[label] = apply_foundry_combat_sync(
                small_pool_engine,
                external_system_id=system.external_system_id,
                external_operation_id=operation_id,
                encounter_id=start.encounter_id,
                round_number=1,
                turn_order=0,
                actor_entity_id=actor,
                world_time_id=f.world_time_id,
                target_entity_id=target,
                hit=True,
                damage_amount=6,
            )
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            errors[label] = exc

    thread_a = threading.Thread(
        target=_submit, args=("a", "small-pool-op-a", f.attacker_id, f.defender_id)
    )
    thread_b = threading.Thread(
        target=_submit, args=("b", "small-pool-op-b", f.defender_id, f.attacker_id)
    )
    try:
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=30)
        thread_b.join(timeout=30)
    finally:
        small_pool_engine.dispose()

    assert not thread_a.is_alive(), "thread a did not finish — likely pool starvation/deadlock"
    assert not thread_b.is_alive(), "thread b did not finish — likely pool starvation/deadlock"
    assert not errors, (
        f"expected both distinct operations to complete cleanly, got errors: {errors}"
    )
    assert len(results) == 2
    assert results["a"].replayed is False
    assert results["b"].replayed is False
    assert _character_hit_points(postgres_engine, f.timeline_id, f.defender_id) == 9
    assert _character_hit_points(postgres_engine, f.timeline_id, f.attacker_id) == 6


def test_an_unlock_failure_invalidates_the_connection_and_a_later_call_does_not_block(
    postgres_engine: Engine, f: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cleanup-hardening regression: if releasing the advisory lock cannot
    be confirmed, the connection that held it must be invalidated rather
    than returned to the pool — otherwise a future caller reusing that same
    physical backend session would silently inherit a still-held
    session-scoped advisory lock, and a later call for the same operation
    id could block forever trying to reacquire it. Injects a failure into
    _unlock_advisory_lock() (the same monkeypatch fault-injection idiom
    used elsewhere in this file), confirms Connection.invalidate() was
    actually called *and* that the same connection wrapper is
    subsequently closed deterministically (invalidate() alone discards
    the underlying DBAPI connection but does not itself finalize the
    SQLAlchemy Connection object), then removes the injected failure and
    proves a replay of the same operation id completes promptly rather
    than hanging on an orphaned lock."""
    system = register_external_system(
        postgres_engine, world_id=f.world_id, system_type="foundry", display_name="Test Foundry"
    )
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    invalidate_calls: list[Connection] = []
    close_calls: list[Connection] = []
    original_invalidate = Connection.invalidate
    original_close = Connection.close

    def _spy_invalidate(self: Connection, *args: object, **kwargs: object) -> None:
        invalidate_calls.append(self)
        original_invalidate(self, *args, **kwargs)

    def _spy_close(self: Connection, *args: object, **kwargs: object) -> None:
        close_calls.append(self)
        original_close(self, *args, **kwargs)

    def _raise_unlock_failure(*args: object, **kwargs: object) -> bool:
        raise RuntimeError("simulated unlock failure")

    monkeypatch.setattr(Connection, "invalidate", _spy_invalidate)
    monkeypatch.setattr(Connection, "close", _spy_close)
    monkeypatch.setattr("dnd_ai.commands.integration._unlock_advisory_lock", _raise_unlock_failure)

    kwargs = {
        "external_system_id": system.external_system_id,
        "external_operation_id": "unlock-failure-op-1",
        "encounter_id": start.encounter_id,
        "round_number": 1,
        "turn_order": 0,
        "actor_entity_id": f.attacker_id,
        "world_time_id": f.world_time_id,
        "target_entity_id": f.defender_id,
        "hit": True,
        "damage_amount": 6,
    }

    result = apply_foundry_combat_sync(postgres_engine, **kwargs)
    assert result.replayed is False
    assert len(invalidate_calls) == 1, "the unlock failure must invalidate the lock connection"
    assert len(close_calls) == 1, (
        "the invalidated connection must still be closed deterministically, not just invalidated"
    )
    assert close_calls[0] is invalidate_calls[0], (
        "close() must finalize the same connection wrapper that was invalidated"
    )

    # Remove both injected patches — the connection that held the lock was
    # invalidated (its underlying DBAPI connection discarded), so a fresh
    # physical connection from the pool must not still be holding the
    # session-scoped lock the invalidated one held.
    monkeypatch.undo()

    replay_results: list[ApplyFoundryCombatSyncResult] = []

    def _replay() -> None:
        replay_results.append(apply_foundry_combat_sync(postgres_engine, **kwargs))

    thread = threading.Thread(target=_replay)
    thread.start()
    thread.join(timeout=15)
    assert not thread.is_alive(), (
        "a later call for the same operation id must not block on an orphaned advisory lock"
    )
    assert len(replay_results) == 1
    assert replay_results[0].replayed is True


def test_a_close_failure_after_confirmed_unlock_does_not_mask_a_domain_exception(
    postgres_engine: Engine, f: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exception-safety regression: the confirmed-unlock cleanup path's
    close() must never be allowed to replace an exception already
    propagating from claim/work/failure processing. Forces a real domain
    failure (a non-participant actor, exactly like
    test_a_failed_combat_sync_records_the_failure_and_leaves_domain_state_unchanged)
    together with a close() that always raises a *different* exception —
    the unlock itself is genuine and succeeds (this is the confirmed-
    unlock path), so close() runs, raises, and must be swallowed rather
    than surfacing in place of the original domain error."""
    system = register_external_system(
        postgres_engine, world_id=f.world_id, system_type="foundry", display_name="Test Foundry"
    )
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        # Only the attacker joins — the defender (used as actor below) is
        # deliberately not a participant, so resolve_combat_turn()'s own
        # ValueError is the exception this cleanup must not mask.
        participant_entity_ids=(f.attacker_id,),
    )

    def _boom_close(self: Connection, *args: object, **kwargs: object) -> None:
        raise ValueError("simulated close failure — must never surface")

    monkeypatch.setattr(Connection, "close", _boom_close)

    with pytest.raises(ValueError, match="is not a participant"):
        apply_foundry_combat_sync(
            postgres_engine,
            external_system_id=system.external_system_id,
            external_operation_id="close-failure-op-1",
            encounter_id=start.encounter_id,
            round_number=1,
            turn_order=0,
            actor_entity_id=f.defender_id,  # not a participant — triggers the real domain error
            world_time_id=f.world_time_id,
            target_entity_id=f.attacker_id,
            hit=True,
            damage_amount=5,
        )

    monkeypatch.undo()

    with postgres_engine.connect() as verify:
        job_row = verify.execute(
            text("""
                SELECT status, error_message FROM integration.sync_jobs
                WHERE external_system_id = :s AND external_operation_id = 'close-failure-op-1'
            """),
            {"s": system.external_system_id},
        ).one()
        assert job_row.status == "failed"
        assert job_row.error_message is not None
        assert "is not a participant" in job_row.error_message


def test_an_invalidate_failure_falls_back_to_detach_and_a_later_call_does_not_block(
    postgres_engine: Engine, f: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exception-safety regression for the unconfirmed-unlock path's own
    failure mode: if invalidate() itself raises, cleanup must not fall
    through to an ordinary close() — that would return an untouched,
    possibly still lock-owning physical session straight back to the
    pool. Forces both _unlock_advisory_lock() and Connection.invalidate()
    to raise, so _release_lock_connection() must reach its detach()
    fallback. Verifies the fallback fires (spies on detach()/close()),
    then verifies the *observable* outcome at the PostgreSQL level
    directly — a fresh pg_try_advisory_lock() on the same key must
    succeed, proving the backend session that held the lock was actually
    torn down rather than merely believed to be — and separately proves a
    same-operation-id replay completes rather than blocking."""
    system = register_external_system(
        postgres_engine, world_id=f.world_id, system_type="foundry", display_name="Test Foundry"
    )
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    detach_calls: list[Connection] = []
    close_calls: list[Connection] = []
    original_detach = Connection.detach
    original_close = Connection.close

    def _spy_detach(self: Connection, *args: object, **kwargs: object) -> None:
        detach_calls.append(self)
        original_detach(self, *args, **kwargs)

    def _spy_close(self: Connection, *args: object, **kwargs: object) -> None:
        close_calls.append(self)
        original_close(self, *args, **kwargs)

    def _raise_unlock_failure(*args: object, **kwargs: object) -> bool:
        raise RuntimeError("simulated unlock failure")

    def _raise_invalidate_failure(self: Connection, *args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated invalidate failure")

    monkeypatch.setattr(Connection, "invalidate", _raise_invalidate_failure)
    monkeypatch.setattr(Connection, "detach", _spy_detach)
    monkeypatch.setattr(Connection, "close", _spy_close)
    monkeypatch.setattr("dnd_ai.commands.integration._unlock_advisory_lock", _raise_unlock_failure)

    kwargs = {
        "external_system_id": system.external_system_id,
        "external_operation_id": "invalidate-failure-op-1",
        "encounter_id": start.encounter_id,
        "round_number": 1,
        "turn_order": 0,
        "actor_entity_id": f.attacker_id,
        "world_time_id": f.world_time_id,
        "target_entity_id": f.defender_id,
        "hit": True,
        "damage_amount": 6,
    }

    result = apply_foundry_combat_sync(postgres_engine, **kwargs)
    assert result.replayed is False
    assert len(detach_calls) == 1, "a failed invalidate() must fall back to detach()"
    assert len(close_calls) == 1, "the connection must still be closed after the detach fallback"
    assert detach_calls[0] is close_calls[0], (
        "detach() and close() must finalize the same connection wrapper"
    )

    # Direct, observable proof at the PostgreSQL level — not just that the
    # spied methods were invoked — that the backend session which held the
    # lock is actually gone: a fresh session can acquire the same key.
    # detach()+close() physically closes the socket, but the server-side
    # termination isn't guaranteed instantaneous, so poll briefly rather
    # than asserting on the very first attempt — bounded to 2 seconds
    # total, never an unbounded wait.
    lock_probe_params = {"a": str(system.external_system_id), "b": "invalidate-failure-op-1"}
    acquired = False
    for _ in range(20):
        with postgres_engine.connect() as probe:
            acquired = bool(
                probe.execute(
                    text("SELECT pg_try_advisory_lock(hashtext(:a), hashtext(:b))"),
                    lock_probe_params,
                ).scalar()
            )
            if acquired:
                probe.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:a), hashtext(:b))"),
                    lock_probe_params,
                )
                probe.commit()
                break
        time.sleep(0.1)
    assert acquired, (
        "the advisory lock must be free after the detach/close fallback — a still-held "
        "lock here would mean the possibly lock-owning session was recycled into the pool"
    )

    monkeypatch.undo()

    replay_results: list[ApplyFoundryCombatSyncResult] = []

    def _replay() -> None:
        replay_results.append(apply_foundry_combat_sync(postgres_engine, **kwargs))

    thread = threading.Thread(target=_replay)
    thread.start()
    thread.join(timeout=15)
    assert not thread.is_alive(), (
        "a later call for the same operation id must not block on an orphaned advisory lock"
    )
    assert len(replay_results) == 1
    assert replay_results[0].replayed is True


def test_a_double_failure_after_invalidate_and_detach_fail_quarantines_the_connection(
    postgres_engine: Engine, f: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The final cleanup edge, per _release_lock_connection()'s own
    docstring (step 3c) and _quarantine_lock_connection()'s: if both
    invalidate() and detach() raise, an ordinary close() must never be
    reached — but merely *not* calling close() is not, by itself, a
    guarantee the connection can never return to the pool: once
    unreferenced, it becomes eligible for garbage collection, and
    SQLAlchemy's pooled-connection wrapper can finalize a
    never-explicitly-closed connection by returning it to the pool
    itself. This test forces the unlock, invalidate(), and detach() to
    all fail, then proves the *full* guarantee, not just the absence of
    a close() call:

    1. close() is never invoked (a spy records zero calls).
    2. the exact connection object is retained by identity in
       integration._QUARANTINED_LOCK_CONNECTIONS after
       apply_foundry_combat_sync() returns.
    3. that retention is real, not incidental: this test's own strong
       reference to the connection is dropped and gc.collect() is run —
       a weakref to the connection surviving that collection proves the
       quarantine list itself, not a leftover test-local reference, is
       what keeps it alive.

    Cleanup runs in `finally` (so it still runs if any assertion above
    fails): it restores the real SQLAlchemy methods, removes the
    connection from the module-level quarantine list, then genuinely
    invalidates and closes it — releasing the real, still-held
    session-scoped advisory lock and returning postgres_engine's shared
    pool to its original capacity, so this test leaves no quarantined
    connection, leaked pool slot, or held lock behind for any other
    test."""
    system = register_external_system(
        postgres_engine, world_id=f.world_id, system_type="foundry", display_name="Test Foundry"
    )
    start = start_encounter(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        participant_entity_ids=(f.attacker_id, f.defender_id),
    )

    close_calls: list[Connection] = []
    captured_connections: list[Connection] = []

    def _spy_close(self: Connection, *args: object, **kwargs: object) -> None:
        close_calls.append(self)

    def _raise_unlock_failure(*args: object, **kwargs: object) -> bool:
        raise RuntimeError("simulated unlock failure")

    def _raise_invalidate_failure(self: Connection, *args: object, **kwargs: object) -> None:
        captured_connections.append(self)
        raise RuntimeError("simulated invalidate failure")

    def _raise_detach_failure(self: Connection, *args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated detach failure")

    monkeypatch.setattr(Connection, "invalidate", _raise_invalidate_failure)
    monkeypatch.setattr(Connection, "detach", _raise_detach_failure)
    monkeypatch.setattr(Connection, "close", _spy_close)
    monkeypatch.setattr("dnd_ai.commands.integration._unlock_advisory_lock", _raise_unlock_failure)

    weak_connection: weakref.ReferenceType[Connection] | None = None
    try:
        result = apply_foundry_combat_sync(
            postgres_engine,
            external_system_id=system.external_system_id,
            external_operation_id="double-failure-op-1",
            encounter_id=start.encounter_id,
            round_number=1,
            turn_order=0,
            actor_entity_id=f.attacker_id,
            world_time_id=f.world_time_id,
            target_entity_id=f.defender_id,
            hit=True,
            damage_amount=6,
        )

        assert result.replayed is False, "the domain operation itself must still have succeeded"
        assert close_calls == [], (
            "close() must never be called on a wrapper whose invalidate() and detach() both failed"
        )
        assert len(captured_connections) == 1
        target_id = id(captured_connections[0])
        weak_connection = weakref.ref(captured_connections[0])

        with integration_module._QUARANTINED_LOCK_CONNECTIONS_LOCK:
            assert any(
                id(c) == target_id for c in integration_module._QUARANTINED_LOCK_CONNECTIONS
            ), "the exact connection object must be retained in the quarantine list"

        # Drop every strong reference this test holds before checking
        # whether the object is still alive — otherwise a surviving
        # weakref would prove nothing about the quarantine itself.
        captured_connections.clear()

        gc.collect()

        assert weak_connection() is not None, (
            "the connection must still be alive after gc.collect() — only the quarantine "
            "list's own strong reference can be keeping it alive at this point"
        )
    finally:
        monkeypatch.undo()

        # Recover the object (still alive per the assertion above — or,
        # if that very assertion is what failed, whatever the quarantine
        # list still holds) and genuinely dispose of it now that the real
        # SQLAlchemy methods are restored, so this test leaves nothing
        # quarantined, no leaked pool slot, and no held advisory lock
        # behind for any other test.
        surviving: list[Connection] = []
        with integration_module._QUARANTINED_LOCK_CONNECTIONS_LOCK:
            live_connection = weak_connection() if weak_connection is not None else None
            if live_connection is not None:
                surviving = [
                    c
                    for c in integration_module._QUARANTINED_LOCK_CONNECTIONS
                    if c is live_connection
                ]
                for c in surviving:
                    integration_module._QUARANTINED_LOCK_CONNECTIONS.remove(c)

        for c in surviving:
            with contextlib.suppress(Exception):
                c.invalidate()
            with contextlib.suppress(Exception):
                c.close()
