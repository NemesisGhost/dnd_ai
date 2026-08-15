"""RegisterExternalSystem, MapExternalIdentifier, and
ApplyFoundryCombatSync — the adapter-facing command contract an external
system (FoundryVTT, Discord, or otherwise) calls to synchronize state, per
docs/PLAN.md Phase 9's replanned scope: the database model and command
layer an adapter will call once a live API exists (Phase 10), proven here
without one.

apply_foundry_combat_sync is the concrete proof of the exit criterion this
phase can make without a deployable: an inbound sync job drives the *same*
combat-resolution logic dnd_ai.commands.encounters.resolve_combat_turn()
uses — never a raw table write.

Transaction design (revised twice during Phase 9 review, before this PR
merged — docs/PHASE9_VERIFICATION.md records both correction passes): the
domain mutation and its successful completion bookkeeping commit or roll
back together, via dnd_ai.commands.encounters._resolve_combat_turn_impl()
— the composable form of resolve_combat_turn() that runs on a
caller-supplied Connection instead of opening its own. This closes a gap
the first version of this module had: calling the public
resolve_combat_turn() (which commits on its own) and then
_complete_sync_job() as a second, separate transaction meant a failure
completing the sync job left the combat mutation committed while the job
stayed stuck 'in_progress' forever — silently breaking the exactly-once
contract this module exists to provide. There are exactly three
transactions per call, never two overlapping in a way that could leave
that inconsistency behind — and, since the second correction pass below,
all three run sequentially on the *same* connection that holds the
advisory lock, rather than each opening its own pooled connection:

1. Claim: read or create the sync_jobs row (its own transaction, always
   committed before any domain work starts, so a job that never gets past
   this point simply never existed rather than being left half-formed).
2. Work: the domain mutation (_resolve_combat_turn_impl) and
   _complete_sync_job() together, in one transaction. Either both commit —
   combat turn, action, event, HP change, the successful delivery attempt,
   and the sync_state upsert all become visible at once — or a raised
   exception rolls back every one of them, leaving the job exactly as the
   claim step left it (still 'in_progress').
3. Fail (only reached if step 2 raised): a separate transaction marks the
   already-persisted job 'failed' and logs a failed delivery attempt. This
   step never overlaps with step 2 — by construction, the try/except below
   only enters it once step 2 has already fully rolled back.

Idempotency and concurrency: external adapters redeliver at least once, so
external_operation_id is a required, caller-supplied idempotency key.
apply_foundry_combat_sync() holds a session-scoped Postgres advisory lock
keyed on (external_system_id, external_operation_id) for its entire
duration, across all three steps above — a genuinely concurrent second
caller for the *same* operation blocks at lock acquisition until the first
caller has reached a terminal sync_jobs.status, then observes that
terminal row and replays its result instead of doing any of the three
steps itself.

Single-connection design (added in the second correction pass, closing a
connection-pool deadlock the first version of this fix had): steps 1-3
above each open their transaction with `lock_connection.begin()` — an
explicit transaction on the *same* Connection object that holds the
advisory lock — rather than `engine.begin()`, which would check out a
second, independent connection from the pool. The earlier design held the
lock connection idle while steps 1-3 each borrowed a fresh pooled
connection to do their work; under a small pool (in the extreme,
pool_size=1), a caller waiting on the advisory lock could exhaust the
pool's remaining connections, leaving the lock holder itself unable to
obtain a connection for its own steps 1-3 and deadlocking permanently.
Because everything now runs on lock_connection, one call to
apply_foundry_combat_sync() never needs more than a single pooled
connection for its entire duration, no matter how many callers are
waiting on the same or different operation ids — see
test_a_small_pool_does_not_deadlock_a_single_call and
test_two_operations_on_the_same_target_do_not_starve_a_small_pool in
tests/scenario/test_foundry_sync_commands.py.

Two *different* operation ids racing for the *same* target (e.g. two
Foundry combat turns in the same encounter, submitted back to back) are
not serialized by the advisory lock — each acquires its own lock key and
runs step 2 concurrently with the other. What must not race is their
shared integration.sync_state row: _complete_sync_job() upserts it with a
single atomic `INSERT ... ON CONFLICT ... DO UPDATE` against whichever of
sync_state's two partial unique indexes matches the target actually set,
so Postgres itself serializes the two writers at the row level (the second
blocks on the first's row lock until it commits, then applies its own
update) — see _complete_sync_job()'s own docstring. The prior
SELECT-then-INSERT shape raced exactly here: both writers could observe no
existing row and both attempt an INSERT, the loser violating the unique
index *after* its own domain mutation had already committed in the old
two-transaction design — a problem this revision closes from both sides
(atomic upsert, and the mutation/completion no longer split across
transactions in the first place).

Replay, conflict, and retry: the check comparing a replay's payload
against the payload originally recorded for that external_operation_id
always runs first, before anything else — a reused operation id with a
*different* canonical payload is a ConflictingSyncPayloadError regardless
of whether the original attempt completed, failed, or crashed
mid-flight; there is no path that silently retries with new arguments
under an old operation id. Only once the payload matches does status
decide what happens next: 'completed' reconstructs and returns the
original ResolveCombatTurnResult without re-executing anything; 'failed'
or a crash-orphaned 'in_progress' (the advisory lock does not survive a
session dying before it releases) retries under the same sync_jobs row,
logging an additional integration.delivery_attempts row rather than a new
job.

HTTP exposure (docs/PLAN.md Phase 10, `dnd_ai.api.integration`):
register_external_system and map_external_identifier are reachable over
HTTP as of Phase 10 workstream 10 — both split into a connection-taking
`_..._impl` plus a public engine-based wrapper below, the same composition
every other command module in this package uses, so the API layer's
per-request transaction can run either directly. apply_foundry_combat_sync
deliberately has no HTTP endpoint yet: its own reasoning above already
explains why it runs with no authoritative campaign_id to assert against
("Phase 11 (Foundry MVP) is where Foundry users get mapped to
authenticated platform users and campaign membership, at which point this
function's caller ... would be the place to resolve and pass an
authoritative campaign_id to assert against") — and separately, its
three-transaction, session-scoped-advisory-lock design (this module's own
docstring above) is deliberately incompatible with the one-transaction-
per-request model every other API command endpoint relies on for atomic
auditing, so giving it an endpoint now would mean either breaking that
design or writing its audit.change_log row in a second, non-atomic
transaction after the fact. Both are left for Phase 11, when a real
Foundry-adapter caller and its own authorization/transaction shape are
designed together rather than retrofitted here.
"""

import contextlib
import json
import logging
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, Engine, text

from dnd_ai.domain.errors import DomainAuthorizationError

from .encounters import ResolveCombatTurnResult, _resolve_combat_turn_impl

logger = logging.getLogger(__name__)

# Process-lifetime quarantine for advisory-lock connections that could be
# neither invalidated nor detached — see _quarantine_lock_connection()'s
# docstring. A private module-level list, not a class attribute or
# instance state, because the whole point is a strong reference that
# outlives any particular apply_foundry_combat_sync() call's stack frame;
# guarded by its own lock since apply_foundry_combat_sync() supports
# concurrent callers, any of which could reach this branch independently.
_QUARANTINED_LOCK_CONNECTIONS_LOCK = threading.Lock()
_QUARANTINED_LOCK_CONNECTIONS: list[Connection] = []


class ConflictingSyncPayloadError(ValueError):
    """Raised when external_operation_id is reused with a payload that does
    not match the payload originally recorded for it — checked first,
    before status, so this can happen regardless of whether the original
    attempt completed, failed, or crashed mid-flight."""


class ExternalSystemNotFoundError(DomainAuthorizationError):
    """Raised by `_map_external_identifier_impl()` when `expected_world_id`
    is supplied and `external_system_id` either does not exist or belongs
    to a different world. `integration.enforce_external_identifier_world()`
    (revision 079) only guarantees `external_system_id` and `entity_id`
    agree with *each other* — it says nothing about whether either belongs
    to the *caller's own* authorized world, so an API caller authorized
    only for one campaign/world could otherwise target an
    `external_system_id` belonging to an entirely different world it has no
    access to. Mirrors `dnd_ai.commands.encounters.EncounterNotFoundError`'s
    reasoning: confirming a resource exists but belongs to a different
    world would itself be a disclosure to a caller only authorized for the
    world it expected, so both cases raise this identical, fixed 404."""


@dataclass(frozen=True)
class RegisterExternalSystemResult:
    external_system_id: uuid.UUID


@dataclass(frozen=True)
class MapExternalIdentifierResult:
    external_identifier_id: uuid.UUID
    world_id: uuid.UUID


@dataclass(frozen=True)
class ApplyFoundryCombatSyncResult:
    sync_job_id: uuid.UUID
    combat_result: ResolveCombatTurnResult
    replayed: bool


def _register_external_system_impl(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    system_type: str,
    display_name: str,
    external_reference: str | None = None,
) -> RegisterExternalSystemResult:
    """The actual work of register_external_system(), on a connection the
    caller already has open — see dnd_ai.commands.encounters.
    _resolve_combat_turn_impl's docstring for the composable-
    implementation/public-wrapper pattern this mirrors. A caller that owns
    the surrounding transaction itself (e.g. the API layer's per-request
    connection) calls this directly."""
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


def register_external_system(
    engine: Engine,
    *,
    world_id: uuid.UUID,
    system_type: str,
    display_name: str,
    external_reference: str | None = None,
) -> RegisterExternalSystemResult:
    """Register an external system (e.g. a Foundry world, a Discord guild)
    for a world. Public convenience API: opens and commits its own
    transaction. See _register_external_system_impl() for the composable
    form a caller with its own transaction (e.g. an API command endpoint)
    uses instead."""
    with engine.begin() as connection:
        return _register_external_system_impl(
            connection,
            world_id=world_id,
            system_type=system_type,
            display_name=display_name,
            external_reference=external_reference,
        )


def _external_system_world(connection: Connection, external_system_id: uuid.UUID) -> uuid.UUID:
    value = connection.execute(
        text("SELECT world_id FROM integration.external_systems WHERE external_system_id = :s"),
        {"s": external_system_id},
    ).scalar()
    if value is None:
        raise ExternalSystemNotFoundError(f"external system {external_system_id} does not exist")
    assert isinstance(value, uuid.UUID)
    return value


def _map_external_identifier_impl(
    connection: Connection,
    *,
    external_system_id: uuid.UUID,
    entity_id: uuid.UUID,
    external_kind: str,
    external_id: str,
    expected_world_id: uuid.UUID | None = None,
) -> MapExternalIdentifierResult:
    """The actual work of map_external_identifier(), on a connection the
    caller already has open — see dnd_ai.commands.encounters.
    _resolve_combat_turn_impl's docstring for the composable-
    implementation/public-wrapper pattern this mirrors. A caller that owns
    the surrounding transaction itself (e.g. the API layer's per-request
    connection) calls this directly.

    Create or refresh the mapping between an internal entity and its
    representation in an external system. Upserts on
    ux_external_identifiers_system_kind_external so re-registering the same
    external object is idempotent.

    expected_world_id, when supplied, asserts external_system_id belongs to
    that world before writing anything (_external_system_world, raising
    ExternalSystemNotFoundError otherwise) — external_system_id's own
    world_id is immutable once created (no command in this codebase ever
    reparents an integration.external_systems row to a different world), so
    a plain SELECT suffices here; unlike dnd_ai.commands.encounters.
    _lock_encounter, there is no concurrent-mutation race this check needs
    a row lock to close. expected_world_id=None (every direct/
    administrative caller today) skips only this assertion, the same
    "unscoped mode" dnd_ai.commands.encounters._lock_encounter's own
    expected_campaign_id=None already establishes."""
    world_id: uuid.UUID | None = None
    if expected_world_id is not None:
        world_id = _external_system_world(connection, external_system_id)
        if world_id != expected_world_id:
            raise ExternalSystemNotFoundError(
                f"external system {external_system_id} belongs to world {world_id!r}, "
                f"not {expected_world_id!r}"
            )

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

    if world_id is None:
        world_id = _external_system_world(connection, external_system_id)

    return MapExternalIdentifierResult(external_identifier_id=value, world_id=world_id)


def map_external_identifier(
    engine: Engine,
    *,
    external_system_id: uuid.UUID,
    entity_id: uuid.UUID,
    external_kind: str,
    external_id: str,
    expected_world_id: uuid.UUID | None = None,
) -> MapExternalIdentifierResult:
    """Create or refresh the mapping between an internal entity and its
    representation in an external system. Public convenience API: opens and
    commits its own transaction. See _map_external_identifier_impl() for
    the composable form a caller with its own transaction (e.g. an API
    command endpoint) uses instead."""
    with engine.begin() as connection:
        return _map_external_identifier_impl(
            connection,
            external_system_id=external_system_id,
            entity_id=entity_id,
            external_kind=external_kind,
            external_id=external_id,
            expected_world_id=expected_world_id,
        )


def _canonical_payload(
    *,
    encounter_id: uuid.UUID,
    round_number: int,
    turn_order: int,
    actor_entity_id: uuid.UUID,
    world_time_id: uuid.UUID,
    action_kind: str,
    target_entity_id: uuid.UUID | None,
    hit: bool | None,
    damage_amount: int | None,
    raw_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """The full set of arguments that determine a combat-sync operation's
    meaning — persisted as sync_jobs.payload_jsonb and used to detect a
    conflicting replay under the same external_operation_id."""
    return {
        "encounter_id": str(encounter_id),
        "round_number": round_number,
        "turn_order": turn_order,
        "actor_entity_id": str(actor_entity_id),
        "world_time_id": str(world_time_id),
        "action_kind": action_kind,
        "target_entity_id": str(target_entity_id) if target_entity_id is not None else None,
        "hit": hit,
        "damage_amount": damage_amount,
        "raw_payload": raw_payload,
    }


def _find_existing_sync_job(
    connection: Connection, *, external_system_id: uuid.UUID, external_operation_id: str
) -> Any:
    return connection.execute(
        text("""
            SELECT sync_job_id, status, payload_jsonb, resulting_event_id,
                   resulting_encounter_turn_id
            FROM integration.sync_jobs
            WHERE external_system_id = :system AND external_operation_id = :operation
            FOR UPDATE
        """),
        {"system": external_system_id, "operation": external_operation_id},
    ).one_or_none()


def _reconstruct_combat_result(
    connection: Connection,
    *,
    resulting_event_id: uuid.UUID | None,
    resulting_encounter_turn_id: uuid.UUID,
) -> ResolveCombatTurnResult:
    combat_action_id = connection.execute(
        text(
            "SELECT combat_action_id FROM narrative.encounter_turns WHERE encounter_turn_id = :turn"
        ),
        {"turn": resulting_encounter_turn_id},
    ).scalar()
    assert isinstance(combat_action_id, uuid.UUID)

    previous_hit_points: int | None = None
    new_hit_points: int | None = None
    if resulting_event_id is not None:
        row = connection.execute(
            text("""
                SELECT previous_value, new_value FROM narrative.event_effects
                WHERE event_id = :event AND target_component = 'current_hit_points'
            """),
            {"event": resulting_event_id},
        ).one_or_none()
        if row is not None:
            previous_hit_points, new_hit_points = row.previous_value, row.new_value

    return ResolveCombatTurnResult(
        encounter_turn_id=resulting_encounter_turn_id,
        combat_action_id=combat_action_id,
        event_id=resulting_event_id,
        previous_hit_points=previous_hit_points,
        new_hit_points=new_hit_points,
    )


def _insert_sync_job(
    connection: Connection,
    *,
    external_system_id: uuid.UUID,
    direction: str,
    job_type: str,
    target_encounter_id: uuid.UUID | None = None,
    target_entity_id: uuid.UUID | None = None,
    external_operation_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> uuid.UUID:
    sync_job_id = connection.execute(
        text("""
            INSERT INTO integration.sync_jobs
                (external_system_id, direction, job_type, target_entity_id,
                 target_encounter_id, status, payload_jsonb, external_operation_id)
            VALUES (:system, :direction, :job_type, :entity, :encounter, 'in_progress', :payload,
                    :operation)
            RETURNING sync_job_id
        """),
        {
            "system": external_system_id,
            "direction": direction,
            "job_type": job_type,
            "entity": target_entity_id,
            "encounter": target_encounter_id,
            "payload": json.dumps(payload) if payload is not None else None,
            "operation": external_operation_id,
        },
    ).scalar()
    assert isinstance(sync_job_id, uuid.UUID)
    return sync_job_id


def _next_attempt_number(connection: Connection, sync_job_id: uuid.UUID) -> int:
    value = connection.execute(
        text(
            "SELECT COALESCE(MAX(attempt_number), 0) + 1 FROM integration.delivery_attempts "
            "WHERE sync_job_id = :job"
        ),
        {"job": sync_job_id},
    ).scalar()
    assert isinstance(value, int)
    return value


def _unlock_advisory_lock(connection: Connection, lock_params: dict[str, str]) -> bool:
    """Release the session-scoped advisory lock held by connection, and
    report whether PostgreSQL confirms this session actually held (and
    released) it — pg_advisory_unlock() returns false rather than raising
    when the session doesn't hold the lock, so the caller must check the
    return value, not just catch exceptions. Raises if the unlock
    statement or its commit itself fails (e.g. the connection is already
    broken). Factored out of apply_foundry_combat_sync()'s cleanup so the
    unlock-failure path is directly testable via monkeypatch."""
    released = connection.execute(
        text("SELECT pg_advisory_unlock(hashtext(:a), hashtext(:b))"), lock_params
    ).scalar()
    connection.commit()
    return released is True


def _quarantine_lock_connection(connection: Connection, lock_params: dict[str, str]) -> None:
    """Retain a strong, process-lifetime reference to connection, called
    only from _release_lock_connection()'s double-failure branch (both
    invalidate() and detach() raised, so the lock's status and the
    connection's own state are both unknown).

    Merely *not* calling close() on connection is not sufficient by
    itself: once apply_foundry_combat_sync() returns, its local
    `lock_connection` reference goes out of scope, and if nothing else
    references the object it becomes eligible for garbage collection.
    SQLAlchemy's pooled-connection wrapper can implement a finalizer
    (`__del__`) that, for a connection never explicitly closed, attempts
    to return it to the pool itself — which is exactly the outcome this
    entire cleanup state machine exists to prevent, reached anyway
    through Python's own memory management rather than an explicit
    close() call. Appending connection to this module-level list gives it
    a strong reference that outlives the caller's stack frame for the
    rest of the process's life, so the garbage collector can never
    finalize it and no implicit return-to-pool can ever happen.

    This deliberately, permanently consumes one checkout from the
    connection pool per call — the pool's effective size shrinks by one,
    for good, every time this function runs. There is no automatic
    retry, close, or recycling of a quarantined connection: doing so
    would reintroduce the exact risk (returning a possibly still
    lock-owning session to the pool) this function exists to eliminate.
    Reclaiming the leaked capacity requires a process restart, or
    deliberate, informed operator intervention — never an automatic path
    inside this module.

    Logs at CRITICAL so the resource loss is operationally visible rather
    than a silent, slow pool-capacity leak — includes only the
    already-non-secret lock identifiers (external_system_id,
    external_operation_id) and the running quarantine size, never
    credentials or the operation's payload.
    """
    with _QUARANTINED_LOCK_CONNECTIONS_LOCK:
        _QUARANTINED_LOCK_CONNECTIONS.append(connection)
        quarantined_count = len(_QUARANTINED_LOCK_CONNECTIONS)
    logger.critical(
        "Advisory-lock connection quarantined: invalidate() and detach() both failed after "
        "an unconfirmed unlock (external_system_id=%s, external_operation_id=%s). This "
        "connection can never be closed, invalidated, or reused safely, and is being held "
        "in memory for the rest of this process's life to guarantee it is never returned to "
        "the connection pool. This permanently consumes one pool checkout; %d connection(s) "
        "are now quarantined this way. Restart the process to reclaim the leaked capacity.",
        lock_params.get("a"),
        lock_params.get("b"),
        quarantined_count,
    )


def _release_lock_connection(connection: Connection, lock_params: dict[str, str]) -> None:
    """Release the advisory lock held by connection and finalize the
    connection wrapper — the entire body of apply_foundry_combat_sync()'s
    finally block, factored out so its state machine is directly testable
    via monkeypatch/fault injection rather than only observable through
    the full end-to-end call. Every step is independently guarded: no
    exception raised in here may ever propagate out, so nothing here can
    replace an exception already propagating from the caller's try block
    (a domain failure, a claim/work/fail-step exception, or a normal
    return).

    State machine:
      1. Attempt the unlock and confirm it via pg_advisory_unlock()'s own
         boolean result (_unlock_advisory_lock) — a raised exception here
         is treated the same as an unconfirmed (false) result.
      2. Confirmed released: the physical session no longer holds the
         lock, so an ordinary close() (return the connection to the pool
         for reuse) is safe. A close() failure here is suppressed — it
         cannot mask the operation's real result, and the DBAPI
         connection either closes cleanly or the pool discovers the
         problem on a future checkout (pool_pre_ping's job, not this
         function's).
      3. Not confirmed: the physical session might still hold the lock,
         so it must never be recycled back into the pool under any
         circumstance.
         a. Try invalidate() — this immediately discards/closes the
            underlying DBAPI connection and marks the pool to never
            reuse it. If it succeeds, a plain close() afterward only
            finalizes the (already harmless) wrapper, guarded the same
            way as the confirmed-unlock path.
         b. If invalidate() itself raises, it can no longer be trusted
            to have discarded the DBAPI connection — calling an ordinary
            attached close() at that point would return an untouched,
            possibly lock-owning physical session straight back into the
            pool for some future, unrelated caller to silently inherit.
            detach() is the documented public SQLAlchemy mechanism for
            exactly this situation: it severs this Connection's
            underlying DBAPI connection from the pool's rotation
            entirely, so a close() that follows physically closes the
            DBAPI connection (terminating the PostgreSQL backend
            session, which releases every session-scoped advisory lock
            it held) instead of recycling it. Whether detach() itself
            succeeded is tracked explicitly — close() is only called
            when it did.
         c. If detach() *also* raises, there is no further documented
            public SQLAlchemy mechanism left to reach for, and this
            function does not fall back to any private Pool/Engine
            internals to force one. Calling an ordinary close() at this
            point would be exactly the mistake step 3b exists to avoid —
            it could return a session that may still hold the advisory
            lock straight back into the pool's rotation for reuse. So
            this branch calls neither close() nor detach() again — but
            simply *not* calling close() is not, by itself, a guarantee:
            once this function returns and apply_foundry_combat_sync()'s
            own `lock_connection` reference goes out of scope, an
            unreferenced connection becomes eligible for garbage
            collection, and SQLAlchemy's pooled-connection wrapper can
            implement a finalizer that returns a never-explicitly-closed
            connection to the pool anyway — reaching the exact outcome
            this whole state machine exists to prevent, just via Python's
            memory management instead of an explicit call. This branch
            therefore hands the connection to
            _quarantine_lock_connection() (see its own docstring), which
            retains a strong, process-lifetime reference to it so it can
            never be garbage-collected. That is a real, permanent
            resource leak (the pool's effective size shrinks by one
            connection for the rest of the process's life), and neither
            this docstring nor the quarantine function's own pretends
            otherwise — it also logs at CRITICAL so the loss is
            operationally visible. It is accepted as the lesser failure:
            a single leaked, permanently-inert connection is recoverable
            by restarting the process; a live physical session that may
            still own a session-scoped advisory lock, silently handed to
            some future unrelated caller, is a correctness bug that can
            hang that caller indefinitely with no visible cause. This
            branch is only reachable when both invalidate() and detach()
            — two independent, normally very reliable SQLAlchemy/DBAPI
            operations — have both failed, which in practice means the
            underlying connection or process is already in serious
            trouble.
    """
    try:
        unlock_confirmed = _unlock_advisory_lock(connection, lock_params)
    except Exception:
        unlock_confirmed = False

    if unlock_confirmed:
        with contextlib.suppress(Exception):
            connection.close()
        return

    try:
        connection.invalidate()
    except Exception:
        detached = False
        try:
            connection.detach()
            detached = True
        except Exception:
            detached = False

        if detached:
            with contextlib.suppress(Exception):
                connection.close()
        else:
            # Both invalidate() and detach() failed. Do not call an
            # ordinary close() here — see step 3c above. Quarantine is
            # the only remaining guarantee that this connection can never
            # be returned to the pool, whether by an explicit call or by
            # garbage collection.
            with contextlib.suppress(Exception):
                _quarantine_lock_connection(connection, lock_params)
    else:
        with contextlib.suppress(Exception):
            connection.close()


def _fail_sync_job(connection: Connection, *, sync_job_id: uuid.UUID, error_message: str) -> None:
    """Mark a sync job failed and log the attempt, in the caller's own
    (separate, post-rollback) transaction. Never called for a replay —
    only once the "work" transaction (domain mutation + completion) has
    already rolled back in full."""
    connection.execute(
        text("""
            UPDATE integration.sync_jobs
            SET status = 'failed', error_message = :error, updated_at = now()
            WHERE sync_job_id = :job
        """),
        {"error": error_message, "job": sync_job_id},
    )
    attempt_number = _next_attempt_number(connection, sync_job_id)
    connection.execute(
        text("""
            INSERT INTO integration.delivery_attempts (sync_job_id, attempt_number, succeeded,
                                                         response_summary)
            VALUES (:job, :number, false, :summary)
        """),
        {"job": sync_job_id, "number": attempt_number, "summary": error_message},
    )


def _complete_sync_job(
    connection: Connection,
    *,
    sync_job_id: uuid.UUID,
    external_system_id: uuid.UUID,
    target_encounter_id: uuid.UUID | None,
    target_entity_id: uuid.UUID | None,
    resulting_event_id: uuid.UUID | None,
    resulting_encounter_turn_id: uuid.UUID,
) -> None:
    """Mark a sync job completed, log the successful delivery attempt, and
    upsert its current integration.sync_state row — called from inside the
    same transaction as the domain mutation that produced its arguments
    (see apply_foundry_combat_sync()'s "work" step), so any failure here
    rolls back that mutation too rather than leaving it committed against
    a job that never finished.

    The sync_state upsert is a single atomic `INSERT ... ON CONFLICT ...
    DO UPDATE` against whichever of sync_state's two partial unique
    indexes matches the target actually set
    (ck_sync_state_exactly_one_target guarantees exactly one is) — not a
    SELECT-then-INSERT. Two different operation ids racing to complete for
    the *same* target (a case the advisory lock does not serialize, since
    it is keyed per operation id, not per target) are safe: Postgres
    itself serializes the two upserts at the row level, so the second
    writer blocks on the first's row lock until it commits and then
    applies its own update — last_sync_job_id deterministically ends up as
    whichever of the two genuinely committed last, and exactly one
    sync_state row exists either way.
    """
    connection.execute(
        text("""
            UPDATE integration.sync_jobs
            SET status = 'completed', resulting_event_id = :event,
                resulting_encounter_turn_id = :turn, error_message = NULL, updated_at = now()
            WHERE sync_job_id = :job
        """),
        {"event": resulting_event_id, "turn": resulting_encounter_turn_id, "job": sync_job_id},
    )
    attempt_number = _next_attempt_number(connection, sync_job_id)
    connection.execute(
        text("""
            INSERT INTO integration.delivery_attempts (sync_job_id, attempt_number, succeeded)
            VALUES (:job, :number, true)
        """),
        {"job": sync_job_id, "number": attempt_number},
    )

    if target_entity_id is not None:
        connection.execute(
            text("""
                INSERT INTO integration.sync_state
                    (external_system_id, target_entity_id, target_encounter_id, last_sync_job_id,
                     last_synced_at, sync_status)
                VALUES (:system, :entity, NULL, :job, now(), 'synced')
                ON CONFLICT (external_system_id, target_entity_id) WHERE target_entity_id IS NOT NULL
                DO UPDATE SET last_sync_job_id = EXCLUDED.last_sync_job_id,
                              last_synced_at = EXCLUDED.last_synced_at,
                              sync_status = 'synced', updated_at = now()
            """),
            {"system": external_system_id, "entity": target_entity_id, "job": sync_job_id},
        )
    else:
        assert target_encounter_id is not None, (
            "ck_sync_state_exactly_one_target requires exactly one of "
            "target_entity_id/target_encounter_id"
        )
        connection.execute(
            text("""
                INSERT INTO integration.sync_state
                    (external_system_id, target_entity_id, target_encounter_id, last_sync_job_id,
                     last_synced_at, sync_status)
                VALUES (:system, NULL, :encounter, :job, now(), 'synced')
                ON CONFLICT (external_system_id, target_encounter_id)
                    WHERE target_encounter_id IS NOT NULL
                DO UPDATE SET last_sync_job_id = EXCLUDED.last_sync_job_id,
                              last_synced_at = EXCLUDED.last_synced_at,
                              sync_status = 'synced', updated_at = now()
            """),
            {"system": external_system_id, "encounter": target_encounter_id, "job": sync_job_id},
        )


def apply_foundry_combat_sync(
    engine: Engine,
    *,
    external_system_id: uuid.UUID,
    external_operation_id: str,
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
    """Route an inbound Foundry combat-turn payload through the real combat-
    resolution logic (never a raw write), exactly once per
    external_operation_id, with the domain mutation and its successful
    completion bookkeeping committing or rolling back together — see this
    module's docstring for the full three-step transaction design, the
    single-connection/advisory-lock concurrency model, and the
    replay/retry/conflict rules.

    Deliberately calls _resolve_combat_turn_impl() with no campaign_id
    (leaving _lock_encounter's own expected_campaign_id check unscoped),
    not an oversight: this module's integration.* schema (revision 079)
    scopes an external_system_id to a world_id only — see
    integration.external_systems' own schema — never to a campaign, so
    there is no authoritative campaign_id this function could authorize
    an inbound Foundry combat turn against yet. It still resolves against
    encounter_id's own real, current, FOR-UPDATE-locked timeline/status
    (dnd_ai.commands.encounters._lock_encounter), so a nonexistent or
    non-active encounter is still rejected exactly as it would be with a
    campaign supplied — only the campaign-ownership *assertion* is
    skipped. Phase 11 (Foundry MVP) is where Foundry users get mapped to
    authenticated platform users and campaign membership, at which point
    this function's caller — not this function itself, which has no
    notion of an authenticated request — would be the place to resolve
    and pass an authoritative campaign_id to assert against.

    Not asserting a campaign does not mean discarding one: the
    interaction.interactions row and any resulting narrative.events row
    _resolve_combat_turn_impl creates are still attributed to
    encounter_id's own actual, locked campaign_id (LockedEncounter.
    campaign_id) whenever the target encounter is campaign-owned — the
    same provenance a campaign-scoped caller would get. A campaign-less
    encounter (campaign_id NULL) still produces campaign-less records, as
    it always has. This is provenance inheritance, not authorization —
    Foundry callers remain unauthenticated against any particular
    campaign until Phase 11 does that work; see
    dnd_ai.commands.encounters._lock_encounter's and LockedEncounter's own
    docstrings for the general contract this relies on.
    """
    payload = _canonical_payload(
        encounter_id=encounter_id,
        round_number=round_number,
        turn_order=turn_order,
        actor_entity_id=actor_entity_id,
        world_time_id=world_time_id,
        action_kind=action_kind,
        target_entity_id=target_entity_id,
        hit=hit,
        damage_amount=damage_amount,
        raw_payload=raw_payload,
    )
    lock_params = {"a": str(external_system_id), "b": external_operation_id}

    # Everything below — the claim, work, and (on failure) fail steps — runs
    # on this one connection, never on a second connection pulled from the
    # pool while it holds the advisory lock. See this module's docstring
    # for the pool-deadlock this avoids.
    lock_connection = engine.connect()
    try:
        lock_connection.execute(
            text("SELECT pg_advisory_lock(hashtext(:a), hashtext(:b))"), lock_params
        )
        lock_connection.commit()

        # Step 1: claim. Always committed before any domain work starts.
        with lock_connection.begin():
            existing = _find_existing_sync_job(
                lock_connection,
                external_system_id=external_system_id,
                external_operation_id=external_operation_id,
            )
            if existing is not None:
                if existing.payload_jsonb != payload:
                    raise ConflictingSyncPayloadError(
                        f"external_operation_id {external_operation_id!r} on external system "
                        f"{external_system_id} was already used with a different payload"
                    )
                if existing.status == "completed":
                    combat_result = _reconstruct_combat_result(
                        lock_connection,
                        resulting_event_id=existing.resulting_event_id,
                        resulting_encounter_turn_id=existing.resulting_encounter_turn_id,
                    )
                    return ApplyFoundryCombatSyncResult(
                        sync_job_id=existing.sync_job_id,
                        combat_result=combat_result,
                        replayed=True,
                    )
                # 'failed', or a crashed 'in_progress' left behind by a session that died
                # before completing (the advisory lock does not survive that) — retry under
                # the same sync_jobs row rather than treat either as an error.
                sync_job_id = existing.sync_job_id
                lock_connection.execute(
                    text("""
                        UPDATE integration.sync_jobs
                        SET status = 'in_progress', error_message = NULL, updated_at = now()
                        WHERE sync_job_id = :job
                    """),
                    {"job": sync_job_id},
                )
            else:
                sync_job_id = _insert_sync_job(
                    lock_connection,
                    external_system_id=external_system_id,
                    direction="inbound",
                    job_type="combat_turn",
                    target_encounter_id=encounter_id,
                    external_operation_id=external_operation_id,
                    payload=payload,
                )

        # Step 2: work. The domain mutation and its completion bookkeeping
        # commit or roll back together — see this module's docstring.
        try:
            with lock_connection.begin():
                combat_result = _resolve_combat_turn_impl(
                    lock_connection,
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
                _complete_sync_job(
                    lock_connection,
                    sync_job_id=sync_job_id,
                    external_system_id=external_system_id,
                    target_encounter_id=encounter_id,
                    target_entity_id=None,
                    resulting_event_id=combat_result.event_id,
                    resulting_encounter_turn_id=combat_result.encounter_turn_id,
                )
        except Exception as exc:
            # Step 3: fail. Only reached once step 2 has fully rolled back.
            try:
                with lock_connection.begin():
                    _fail_sync_job(lock_connection, sync_job_id=sync_job_id, error_message=str(exc))
            except Exception:
                # A failure recording the failure must never replace the original domain
                # exception — the caller needs to see what step 2 actually raised, not a
                # secondary bookkeeping error.
                pass
            raise

        return ApplyFoundryCombatSyncResult(
            sync_job_id=sync_job_id, combat_result=combat_result, replayed=False
        )
    finally:
        # See _release_lock_connection()'s own docstring for the full
        # unlock/invalidate/detach state machine and why nothing in it can
        # mask an exception already propagating from the try block above.
        _release_lock_connection(lock_connection, lock_params)
