"""RegisterExternalSystem, MapExternalIdentifier, and
ApplyFoundryCombatSync — the adapter-facing command contract an external
system (FoundryVTT, Discord, or otherwise) calls to synchronize state, per
docs/PLAN.md Phase 9's replanned scope: the database model and command
layer an adapter will call once a live API exists (Phase 10), proven here
without one.

apply_foundry_combat_sync is the concrete proof of the exit criterion this
phase can make without a deployable: an inbound sync job drives the *same*
dnd_ai.commands.encounters.resolve_combat_turn() a local caller would use —
never a raw table write — and its own sync_jobs/sync_state bookkeeping
sits in separate transactions around that domain mutation rather than
extending its transaction boundary. A sync job is a record of an
at-least-once external call, not part of the causal-event transaction
rule 6 governs; that mutation already gets its own atomicity from
resolve_combat_turn.
"""

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, Engine, text

from .encounters import ResolveCombatTurnResult, resolve_combat_turn


@dataclass(frozen=True)
class RegisterExternalSystemResult:
    external_system_id: uuid.UUID


@dataclass(frozen=True)
class MapExternalIdentifierResult:
    external_identifier_id: uuid.UUID


@dataclass(frozen=True)
class ApplyFoundryCombatSyncResult:
    sync_job_id: uuid.UUID
    combat_result: ResolveCombatTurnResult


def register_external_system(
    engine: Engine,
    *,
    world_id: uuid.UUID,
    system_type: str,
    display_name: str,
    external_reference: str | None = None,
) -> RegisterExternalSystemResult:
    with engine.begin() as connection:
        external_system_id = connection.execute(
            text("""
                INSERT INTO integration.external_systems
                    (world_id, system_type, display_name, external_reference)
                VALUES (:world, :type, :name, :reference)
                RETURNING external_system_id
            """),
            {
                "world": world_id,
                "type": system_type,
                "name": display_name,
                "reference": external_reference,
            },
        ).scalar()
        assert isinstance(external_system_id, uuid.UUID)
    return RegisterExternalSystemResult(external_system_id=external_system_id)


def map_external_identifier(
    engine: Engine,
    *,
    external_system_id: uuid.UUID,
    entity_id: uuid.UUID,
    external_kind: str,
    external_id: str,
) -> MapExternalIdentifierResult:
    """Create or refresh the mapping between an internal entity and its
    representation in an external system. Upserts on
    ux_external_identifiers_system_kind_external so re-registering the same
    external object is idempotent."""
    with engine.begin() as connection:
        value = connection.execute(
            text("""
                INSERT INTO integration.external_identifiers
                    (external_system_id, entity_id, external_kind, external_id, last_synced_at)
                VALUES (:system, :entity, :kind, :external, now())
                ON CONFLICT (external_system_id, external_kind, external_id)
                DO UPDATE SET entity_id = EXCLUDED.entity_id, last_synced_at = now(),
                              updated_at = now()
                RETURNING external_identifier_id
            """),
            {
                "system": external_system_id,
                "entity": entity_id,
                "kind": external_kind,
                "external": external_id,
            },
        ).scalar()
        assert isinstance(value, uuid.UUID)
    return MapExternalIdentifierResult(external_identifier_id=value)


def _insert_sync_job(
    connection: Connection,
    *,
    external_system_id: uuid.UUID,
    direction: str,
    job_type: str,
    target_encounter_id: uuid.UUID | None = None,
    target_entity_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> uuid.UUID:
    sync_job_id = connection.execute(
        text("""
            INSERT INTO integration.sync_jobs
                (external_system_id, direction, job_type, target_entity_id,
                 target_encounter_id, status, payload_jsonb)
            VALUES (:system, :direction, :job_type, :entity, :encounter, 'in_progress', :payload)
            RETURNING sync_job_id
        """),
        {
            "system": external_system_id,
            "direction": direction,
            "job_type": job_type,
            "entity": target_entity_id,
            "encounter": target_encounter_id,
            "payload": json.dumps(payload) if payload is not None else None,
        },
    ).scalar()
    assert isinstance(sync_job_id, uuid.UUID)
    return sync_job_id


def _complete_sync_job(
    connection: Connection,
    *,
    sync_job_id: uuid.UUID,
    external_system_id: uuid.UUID,
    target_encounter_id: uuid.UUID | None,
    target_entity_id: uuid.UUID | None,
    resulting_event_id: uuid.UUID | None,
    succeeded: bool,
    error_message: str | None = None,
) -> None:
    connection.execute(
        text("""
            UPDATE integration.sync_jobs
            SET status = :status, resulting_event_id = :event, error_message = :error,
                updated_at = now()
            WHERE sync_job_id = :job
        """),
        {
            "status": "completed" if succeeded else "failed",
            "event": resulting_event_id,
            "error": error_message,
            "job": sync_job_id,
        },
    )
    connection.execute(
        text("""
            INSERT INTO integration.delivery_attempts (sync_job_id, attempt_number, succeeded,
                                                         response_summary)
            VALUES (:job, 1, :succeeded, :summary)
        """),
        {"job": sync_job_id, "succeeded": succeeded, "summary": error_message},
    )

    if not succeeded:
        return

    existing_state_id = connection.execute(
        text("""
            SELECT sync_state_id FROM integration.sync_state
            WHERE external_system_id = :system
              AND target_entity_id IS NOT DISTINCT FROM :entity
              AND target_encounter_id IS NOT DISTINCT FROM :encounter
        """),
        {
            "system": external_system_id,
            "entity": target_entity_id,
            "encounter": target_encounter_id,
        },
    ).scalar()

    if existing_state_id is None:
        connection.execute(
            text("""
                INSERT INTO integration.sync_state
                    (external_system_id, target_entity_id, target_encounter_id, last_sync_job_id,
                     last_synced_at, sync_status)
                VALUES (:system, :entity, :encounter, :job, now(), 'synced')
            """),
            {
                "system": external_system_id,
                "entity": target_entity_id,
                "encounter": target_encounter_id,
                "job": sync_job_id,
            },
        )
    else:
        connection.execute(
            text("""
                UPDATE integration.sync_state
                SET last_sync_job_id = :job, last_synced_at = now(), sync_status = 'synced',
                    updated_at = now()
                WHERE sync_state_id = :id
            """),
            {"job": sync_job_id, "id": existing_state_id},
        )


def apply_foundry_combat_sync(
    engine: Engine,
    *,
    external_system_id: uuid.UUID,
    encounter_id: uuid.UUID,
    round_number: int,
    turn_order: int,
    actor_entity_id: uuid.UUID,
    world_time_id: uuid.UUID,
    action_kind: str = "attack",
    target_entity_id: uuid.UUID | None = None,
    hit: bool | None = None,
    damage_amount: int | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> ApplyFoundryCombatSyncResult:
    """Route an inbound Foundry combat-turn payload through the real
    resolve_combat_turn() command (never a raw write), and record the
    integration.sync_jobs/.sync_state/.delivery_attempts bookkeeping around
    it. Each of the three steps below is its own transaction — see this
    module's docstring for why sync-job bookkeeping does not extend the
    domain command's own transaction boundary."""
    with engine.begin() as connection:
        sync_job_id = _insert_sync_job(
            connection,
            external_system_id=external_system_id,
            direction="inbound",
            job_type="combat_turn",
            target_encounter_id=encounter_id,
            payload=raw_payload,
        )

    combat_result = resolve_combat_turn(
        engine,
        encounter_id=encounter_id,
        round_number=round_number,
        turn_order=turn_order,
        actor_entity_id=actor_entity_id,
        world_time_id=world_time_id,
        action_kind=action_kind,
        target_entity_id=target_entity_id,
        hit=hit,
        damage_amount=damage_amount,
    )

    with engine.begin() as connection:
        _complete_sync_job(
            connection,
            sync_job_id=sync_job_id,
            external_system_id=external_system_id,
            target_encounter_id=encounter_id,
            target_entity_id=None,
            resulting_event_id=combat_result.event_id,
            succeeded=True,
        )

    return ApplyFoundryCombatSyncResult(sync_job_id=sync_job_id, combat_result=combat_result)
