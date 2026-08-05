"""Parent-side entity-type-change protection (revision 048).

core.enforce_entity_subtype() (revision 004) validates from the subtype
side: an INSERT or UPDATE on e.g. world.dungeons checks the owning entity's
type. These tests cover the reverse direction — UPDATE core.entities SET
entity_type_id — which revision 048 closes with two triggers: a generic one
driven by core.entity_types metadata, and a dungeon-specific one for the
"child areas stranded even after the marker row is deleted" case the generic
trigger alone cannot see.
"""

import multiprocessing
import queue
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

from tests.factories import (
    lookup_id,
    make_dungeon,
    make_dungeon_area,
    make_location,
    make_world,
)

pytestmark = pytest.mark.database


def _entity_type_id(connection: Connection, code: str) -> object:
    return lookup_id(connection, "core", "entity_types", "entity_type_id", code)


def test_a_dungeon_cannot_be_retyped_to_region(db_connection: Connection) -> None:
    world = make_world(db_connection, slug="retype-dungeon-region")
    dungeon = make_dungeon(db_connection, world)

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
            {"t": _entity_type_id(db_connection, "region"), "e": dungeon},
        )
    assert "cannot change type" in str(exc.value)


def test_a_dungeon_cannot_be_retyped_to_building(db_connection: Connection) -> None:
    """A second, differently-shaped incompatible type — not just the one above."""
    world = make_world(db_connection, slug="retype-dungeon-building")
    dungeon = make_dungeon(db_connection, world)

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
            {"t": _entity_type_id(db_connection, "building"), "e": dungeon},
        )
    assert "cannot change type" in str(exc.value)


def test_a_dungeon_area_cannot_be_retyped_away_while_its_parent_needs_it(
    db_connection: Connection,
) -> None:
    """The subtype-side analogue: dungeon_area is also protected, not just dungeon."""
    world = make_world(db_connection, slug="retype-dungeon-area")
    dungeon = make_dungeon(db_connection, world)
    area = make_dungeon_area(db_connection, dungeon)

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
            {"t": _entity_type_id(db_connection, "region"), "e": area},
        )
    assert "cannot change type" in str(exc.value)


def test_updating_an_entity_without_changing_its_type_is_unaffected(
    db_connection: Connection,
) -> None:
    """A valid, ordinary update — renaming — must not be blocked by this trigger."""
    world = make_world(db_connection, slug="retype-noop")
    dungeon = make_dungeon(db_connection, world, name="Old Name")

    db_connection.execute(
        text("UPDATE core.entities SET canonical_name = 'New Name' WHERE entity_id = :e"),
        {"e": dungeon},
    )
    name = db_connection.execute(
        text("SELECT canonical_name FROM core.entities WHERE entity_id = :e"), {"e": dungeon}
    ).scalar()
    assert name == "New Name"


def test_setting_entity_type_id_to_its_current_value_is_a_no_op(
    db_connection: Connection,
) -> None:
    """UPDATE ... OF entity_type_id fires whenever the column is named in the SET
    list, even if the value does not change — the trigger must not treat that as
    a real change and go looking for orphaned subtype rows."""
    world = make_world(db_connection, slug="retype-same-value")
    dungeon = make_dungeon(db_connection, world)
    current_type = db_connection.execute(
        text("SELECT entity_type_id FROM core.entities WHERE entity_id = :e"), {"e": dungeon}
    ).scalar()

    db_connection.execute(
        text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
        {"t": current_type, "e": dungeon},
    )


def test_a_bare_location_can_be_retyped_before_any_subtype_row_exists(
    db_connection: Connection,
) -> None:
    """A type change that strands nothing remains allowed — this is a correction
    guard, not a blanket immutability lock like world_id's."""
    world = make_world(db_connection, slug="retype-bare-location")
    location = make_location(db_connection, world, entity_type_code="location")

    db_connection.execute(
        text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
        {"t": _entity_type_id(db_connection, "district"), "e": location},
    )
    code = db_connection.execute(
        text(
            "SELECT et.code FROM core.entities e "
            "JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id "
            "WHERE e.entity_id = :e"
        ),
        {"e": location},
    ).scalar()
    assert code == "district"


def test_removing_the_dungeon_row_first_still_does_not_permit_stranding_its_areas(
    db_connection: Connection,
) -> None:
    """Lifecycle-then-retype: deleting world.dungeons (permitted per conventions
    §7.5) removes the row the generic trigger looks for, but the dungeon-specific
    trigger must still reject the type change while dungeon_area children exist —
    this is the "existing child areas cannot be stranded" case, distinct from the
    generic subtype-row check."""
    world = make_world(db_connection, slug="retype-after-marker-removed")
    dungeon = make_dungeon(db_connection, world)
    make_dungeon_area(db_connection, dungeon)

    db_connection.execute(text("DELETE FROM world.dungeons WHERE dungeon_id = :d"), {"d": dungeon})

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
            {"t": _entity_type_id(db_connection, "region"), "e": dungeon},
        )
    assert "still has" in str(exc.value) and "dungeon area" in str(exc.value)


def test_a_dungeon_with_no_areas_can_be_retyped_once_its_marker_row_is_removed(
    db_connection: Connection,
) -> None:
    """The negative-of-the-negative: once world.dungeons is gone and there are no
    dungeon_area children, the type change is legitimate and must succeed."""
    world = make_world(db_connection, slug="retype-after-marker-removed-empty")
    dungeon = make_dungeon(db_connection, world)

    db_connection.execute(text("DELETE FROM world.dungeons WHERE dungeon_id = :d"), {"d": dungeon})

    db_connection.execute(
        text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
        {"t": _entity_type_id(db_connection, "region"), "e": dungeon},
    )
    code = db_connection.execute(
        text(
            "SELECT et.code FROM core.entities e "
            "JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id "
            "WHERE e.entity_id = :e"
        ),
        {"e": dungeon},
    ).scalar()
    assert code == "region"


def test_a_character_npc_cannot_be_retyped_to_bare_character(db_connection: Connection) -> None:
    """The generic mechanism protects Phase 4 subtypes too, not just Phase 5's."""
    from tests.factories import make_character

    world = make_world(db_connection, slug="retype-npc")
    npc = make_character(db_connection, world, entity_type_code="npc")
    db_connection.execute(text("INSERT INTO character.npcs (npc_id) VALUES (:n)"), {"n": npc})

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
            {"t": _entity_type_id(db_connection, "character"), "e": npc},
        )
    assert "cannot change type" in str(exc.value)


# ---------------------------------------------------------------------------
# Concurrency safety of the parent-side/subtype-side checks (revisions 053, 056)
# ---------------------------------------------------------------------------
# Two real connections. Earlier versions of these tests proved blocking by
# setting a short lock_timeout on the second statement, letting it fail, and
# retrying in a fresh third connection — useful lock-attachment evidence, but
# not proof that the *original* waiting statement itself ever resumes and
# revalidates against the newly committed state. A post-merge review
# (PHASE5_REMAINING_ISSUES.md) required the stronger standard, which every
# test below now meets: keep the second statement genuinely alive in its own
# worker while the first transaction commits, confirm via pg_stat_activity
# that it was truly waiting on a lock (not merely slow), join the worker and
# assert on its actual resumed outcome, and then — on a third, independent
# connection — query the committed database state directly to prove no
# invalid combination survived, regardless of which side won. This reuses
# the pattern already established in
# test_world_ruleset_dependency_and_concurrency.py::_assert_blocked_delete_resumes_and_is_rejected
# (redistributed there from the former test_phase4_remaining_issues.py
# monolith — see DEVELOPMENT.md §2.1) for a FOR SHARE row lock, generalized
# here to pg_advisory_xact_lock.


def _cleanup_world(engine: Engine, slug: str) -> None:
    with engine.begin() as cleanup:
        params = {"s": slug}
        cleanup.execute(
            text(
                "DELETE FROM core.entities WHERE world_id IN "
                "(SELECT world_id FROM core.worlds WHERE slug = :s)"
            ),
            params,
        )
        cleanup.execute(text("DELETE FROM core.worlds WHERE slug = :s"), params)


# ---------------------------------------------------------------------------
# _BackgroundStatement: an independently terminable worker process
# ---------------------------------------------------------------------------
# PHASE5_REMAINING_ISSUES.md's tenth review: no Python thread can be safely
# and unconditionally stopped while blocked inside a C-level call (a
# blocking network read, in this file's case) — which meant every earlier
# thread-based version of this helper had at least one path (a statement
# lock_timeout does not govern, plus every graceful PostgreSQL-side signal
# failing) where __exit__ could only report a surviving worker, never
# actually end it. A real OS process does not have that limitation: it can
# always be unconditionally reclaimed by its owner, regardless of what it is
# doing. This section runs the blocked statement in exactly that — a
# multiprocessing.Process, using the "spawn" start method on every platform
# (not just where POSIX "fork" is unavailable) so the guarantees below hold
# identically everywhere.


def _attempt(problems: list[tuple[str, Exception]], label: str, fn: Callable[[], None]) -> None:
    """Runs fn(), appending (label, exc) to problems on failure rather than
    silently discarding it. Every caller attempts every required cleanup
    step regardless of whether an earlier one failed, and every failure
    that happens along the way is collected for reporting — never
    suppressed."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - collected, not swallowed
        problems.append((label, exc))


def _bounded_join_thread(q: Any, timeout: float) -> None:
    """multiprocessing.Queue.join_thread() has no timeout parameter of its
    own, so a queue whose feeder thread genuinely never exits would hang
    cleanup indefinitely. Wraps it in a short-lived daemon thread used only
    to add a bound to that one blocking stdlib call — not a mechanism for
    abandoning the worker process itself, which this class never marks
    daemon — and reports a timeout as a real problem rather than silently
    giving up. Also relays any exception the wrapped call itself raises
    back to this thread: `Thread.join()` alone would only observe the
    thread ending, silently discarding an exception raised inside it
    (Python's default `threading.excepthook` just logs it, which is how an
    earlier version of this helper leaked join_thread()'s own precondition
    assertion as an unhandled-thread-exception warning instead of a
    reported cleanup problem).

    Callers must only invoke this after `q.close()` has already succeeded:
    `join_thread()`'s own documented precondition is that `close()` was
    called first, and calling it against a queue that failed to close
    raises its own unrelated `AssertionError` that must not be mistaken
    for the queue's feeder thread genuinely hanging."""
    outcome: list[BaseException] = []

    def _run() -> None:
        try:
            q.join_thread()
        except BaseException as exc:  # noqa: BLE001 - relayed to the caller, not swallowed
            outcome.append(exc)

    joiner = threading.Thread(target=_run, daemon=True)
    joiner.start()
    joiner.join(timeout=timeout)
    if joiner.is_alive():
        raise TimeoutError(f"queue feeder thread did not finish within {timeout}s")
    if outcome:
        raise outcome[0]


class _InjectedFailure(Exception):
    """Marks a deliberately injected failure — either in one of
    _BackgroundStatement's controller-side fallback seams (_send_signal,
    _cancel_via_driver) or, via the worker's own fault_injection_stage
    parameter, at a specific point in the worker process's startup sequence
    — distinguishing it from a genuine PostgreSQL or driver error."""


def _worker_main(
    database_url: str,
    sql: str,
    params: dict[str, Any],
    lock_timeout_seconds: float,
    connect_timeout_seconds: int,
    startup_delay_seconds: float,
    fault_injection_stage: str | None,
    handshake_queue: Any,
    outcome_queue: Any,
    control_queue: Any,
) -> None:
    """Entry point for _BackgroundStatement's worker process. Defined at
    module level (not a closure or method) because multiprocessing's
    "spawn" start method must be able to pickle a reference to it.

    Three phases: (1) acquire a connection, begin its transaction, set the
    deterministic lock_timeout backstop, and report the real backend pid
    back through handshake_queue — or, on any failure, attempt every
    cleanup step for whatever was partially acquired and report the primary
    failure plus any cleanup problems instead of it; (2) run the given
    statement, watching control_queue on a background thread for a
    driver-native cancel_safe() request from the controller; (3) attempt
    commit() only if the statement succeeded, attempt rollback() only if
    commit() then fails, always attempt close() and dispose() regardless of
    what came before, and report through outcome_queue as
    `(status, primary_error, problems)` — `status` is `"committed"` only
    when the statement, its commit, and every cleanup step all succeeded
    with nothing left to report; a cleanup-only problem after an otherwise
    successful commit still reports `"failed"`.

    None of this running to completion is what makes the controller's own
    guarantee hold: if this process does not respond, or does not stop, the
    controller can unconditionally terminate the OS process itself."""
    if startup_delay_seconds:
        time.sleep(startup_delay_seconds)

    problems: list[tuple[str, Exception]] = []
    engine: Engine | None = None
    connection: Connection | None = None

    def _inject(stage: str) -> None:
        if fault_injection_stage == stage:
            raise _InjectedFailure(f"injected failure at stage: {stage}")

    try:
        engine = create_engine(
            database_url, connect_args={"connect_timeout": connect_timeout_seconds}
        )
        connection = engine.connect()
        _inject("after_connect")
        connection.begin()
        _inject("after_begin")
        if fault_injection_stage == "after_begin_kill_then_fail":
            # Simulates the connection becoming unexpectedly unusable at the
            # exact moment startup fails, with a transaction genuinely
            # active (so SQLAlchemy does not just no-op the rollback below
            # believing there is nothing to roll back) — the except
            # block's own cleanup attempts then genuinely fail too, a real
            # secondary failure, not a synthetic one layered on the primary.
            connection.connection.dbapi_connection.close()
            raise _InjectedFailure("injected failure at stage: after_begin_kill_then_fail")
        connection.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout_seconds}s'"))
        _inject("after_set_lock_timeout")
        pid = connection.execute(text("SELECT pg_backend_pid()")).scalar()
        _inject("after_pid_lookup")
    except Exception as exc:  # noqa: BLE001 - reported via handshake_queue, not swallowed
        if connection is not None:
            _attempt(problems, "rollback after startup failure", connection.rollback)
            _attempt(problems, "close after startup failure", connection.close)
        if engine is not None:
            _attempt(problems, "dispose after startup failure", engine.dispose)
        handshake_queue.put(("failed", repr(exc), problems))
        return

    handshake_queue.put(("ready", pid, []))

    def _watch_for_cancel() -> None:
        while True:
            message = control_queue.get()
            if message is None:
                return
            if message == "cancel":
                try:
                    dbapi_connection = connection.connection.dbapi_connection  # type: ignore[union-attr]
                    dbapi_connection.cancel_safe(timeout=5.0)
                except Exception as exc:  # noqa: BLE001 - collected, not swallowed
                    problems.append(("cancel_via_driver (in worker)", exc))

    watcher = threading.Thread(target=_watch_for_cancel, daemon=True)
    watcher.start()

    def _close_with_optional_injection() -> None:
        if fault_injection_stage == "close_fails":
            raise _InjectedFailure("injected failure at stage: close_fails")
        connection.close()  # type: ignore[union-attr]

    def _dispose_with_optional_injection() -> None:
        if fault_injection_stage == "dispose_fails":
            raise _InjectedFailure("injected failure at stage: dispose_fails")
        engine.dispose()  # type: ignore[union-attr]

    statement_error: Exception | None = None
    commit_error: Exception | None = None
    try:
        connection.execute(text(sql), params)
    except Exception as exc:  # noqa: BLE001 - reported via outcome_queue, not swallowed
        statement_error = exc
        _attempt(problems, "invalidate after statement failure", connection.invalidate)
    else:
        if fault_injection_stage == "after_statement_kill_then_fail":
            # Mirrors after_begin_kill_then_fail, one phase later: the
            # connection becomes genuinely unusable right after the
            # statement succeeds but before commit() is attempted, so both
            # commit() and the subsequent rollback-after-commit-failure
            # attempt fail for real - a genuine secondary failure, not a
            # synthetic one layered on top of a mocked primary.
            connection.connection.dbapi_connection.close()
        try:
            connection.commit()
        except Exception as exc:  # noqa: BLE001 - reported via outcome_queue, not swallowed
            commit_error = exc
            _attempt(problems, "rollback after commit failure", connection.rollback)
    finally:
        control_queue.put(None)
        watcher.join(timeout=5.0)
        _attempt(problems, "close", _close_with_optional_injection)
        _attempt(problems, "dispose", _dispose_with_optional_injection)

    # "committed" is reported only once the statement genuinely executed,
    # its commit genuinely succeeded, and no other cleanup step (rollback,
    # invalidate, close, dispose) reported a problem either - a cleanup-only
    # failure after a real commit must still surface as a failure, not be
    # silently absorbed into an apparently-successful outcome.
    primary_error = (
        repr(statement_error)
        if statement_error is not None
        else (repr(commit_error) if commit_error is not None else None)
    )
    status = "failed" if primary_error is not None or problems else "committed"
    outcome_queue.put((status, primary_error, problems))


class _BackgroundStatement:
    """Runs one SQL statement, with parameters, on its own connection in an
    independently terminable worker process — not a Python thread, since no
    supported mechanism exists to forcibly stop a Python thread blocked
    inside a C-level call, and PHASE5_REMAINING_ISSUES.md's tenth review
    requires a guarantee no thread-based design can make. A real OS process
    can always be unconditionally reclaimed by its owner (SIGKILL /
    TerminateProcess), regardless of what it is doing — that is the
    property this class is built around.

    `__enter__` performs an explicit startup handshake: the worker
    connects, begins its transaction, sets a bounded `lock_timeout` on it,
    and reports its real backend pid back through a queue, all before
    `__enter__` returns. If that handshake fails, times out, or the process
    cannot be confirmed started, `__enter__` terminates and reaps the
    process — never leaving a worker alive — before raising, with any
    cleanup problems attached as notes on the raised error. `backend_pid`
    is exposed only as a read-only property once the handshake completes;
    there is no way for a caller to overwrite it.

    `__exit__` guarantees that by the time it returns or raises, the worker
    process is provably no longer running, and that PostgreSQL has actually
    noticed — checked through a fresh connection, not assumed from the
    process alone. If the process is still alive when the `with` block
    exits, `__exit__` attempts, in order: `pg_terminate_backend()`, then
    `pg_cancel_backend()` (both through an isolated, mockable
    `_send_signal` seam); driver-native cancellation via psycopg's
    `cancel_safe()`, relayed to a watcher thread inside the worker process
    itself (a resource this helper genuinely owns, needing no second
    authenticated connection); and the `lock_timeout` configured during
    startup, which PostgreSQL enforces unconditionally on a genuine lock
    wait. If every one of those fails or does not apply (a statement not
    blocked on a lock at all cannot be rescued by `lock_timeout`), the
    worker process is forcibly terminated — a step that cannot itself fail
    to end the process, unlike every mechanism before it — followed by one
    more, unconditional `pg_terminate_backend()` call. That last call is
    necessary, not redundant: ending the client-side process guarantees
    that process's own resources are reclaimed, but does not by itself
    guarantee PostgreSQL has noticed, since a backend blocked inside a call
    that never touches its client socket (`pg_sleep`, unlike a lock wait)
    can keep running until it next tries to communicate.

    Every step's outcome is collected, never silently discarded. The
    worker's own statement, commit, rollback, invalidation, close, and
    engine-disposal failures are all represented in a structured outcome
    (see `_worker_main`); a statement that succeeds but whose commit then
    fails is reported as a failure, never as committed, and a cleanup-only
    problem after an otherwise-successful commit still fails the caller
    rather than being silently absorbed. Whatever the caller does not
    explicitly consume via `resume_and_get_outcome` is still drained and
    processed by `__exit__`, so an outcome nobody read is never lost. If an
    exception was already propagating out of the `with` block, every
    cleanup problem is attached to it via `add_note`; if nothing was
    already propagating, cleanup problems are raised directly and become
    the `with` block's own failure. A `with` block backed by this class
    therefore never returns or raises with an owned worker, IPC queue, or
    process object still alive/open — the guarantee no earlier thread-based
    design in this file's history could make.
    """

    _CONNECT_TIMEOUT_SECONDS = 3

    def __init__(
        self,
        engine: Engine,
        sql: str,
        params: dict[str, Any] | None = None,
        *,
        lock_timeout_seconds: float = 8.0,
        signal_join_seconds: float = 5.0,
        handshake_timeout_seconds: float = 10.0,
        _startup_delay_seconds: float = 0.0,
        _fault_injection_stage: str | None = None,
    ) -> None:
        self._engine = engine
        self._sql = sql
        self._params: dict[str, Any] = dict(params or {})
        self._lock_timeout_seconds = lock_timeout_seconds
        self._signal_join_seconds = signal_join_seconds
        self._handshake_timeout_seconds = handshake_timeout_seconds
        self._startup_delay_seconds = _startup_delay_seconds
        self._fault_injection_stage = _fault_injection_stage
        self.outcome: list[tuple[str, Exception | None]] = []
        self._backend_pid_value: int | None = None
        self._process: Any = None
        self._handshake_queue: Any = None
        self._outcome_queue: Any = None
        self._control_queue: Any = None
        self._worker_confirmed_stopped = False

    @property
    def backend_pid(self) -> int:
        """The worker's real backend pid — private storage, read-only
        exposure. There is deliberately no way for a caller to overwrite
        this: fault-injection tests inject failures at the signaling
        operations themselves (`_send_signal`, `_cancel_via_driver`), never
        by corrupting this identity."""
        assert self._backend_pid_value is not None, "backend_pid read before __enter__ completed"
        return self._backend_pid_value

    @property
    def worker_confirmed_stopped(self) -> bool:
        """True once the worker process has been confirmed not-alive and
        its Process object closed. Callers (including tests) that need to
        confirm containment after `__exit__`/`_reap` must use this rather
        than `._process.is_alive()` directly: once the Process object is
        closed (per this class's own IPC/process cleanup — see
        `_close_queues` and the `close process object` step), calling
        `is_alive()` on it raises `ValueError: process object is closed`
        instead of meaningfully answering the question."""
        return self._worker_confirmed_stopped

    def __enter__(self) -> "_BackgroundStatement":
        ctx = multiprocessing.get_context("spawn")
        handshake_queue: Any = ctx.Queue()
        outcome_queue: Any = ctx.Queue()
        control_queue: Any = ctx.Queue()
        # Stored immediately, not only on success: __exit__ is never called
        # if __enter__ raises, so every failure branch below is responsible
        # for its own cleanup, and needs these to be able to find the queues
        # it must close.
        self._handshake_queue = handshake_queue
        self._outcome_queue = outcome_queue
        self._control_queue = control_queue

        try:
            process = ctx.Process(
                target=_worker_main,
                args=(
                    self._engine.url.render_as_string(hide_password=False),
                    self._sql,
                    self._params,
                    self._lock_timeout_seconds,
                    self._CONNECT_TIMEOUT_SECONDS,
                    self._startup_delay_seconds,
                    self._fault_injection_stage,
                    handshake_queue,
                    outcome_queue,
                    control_queue,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - reported directly, not swallowed
            construction_problems: list[tuple[str, Exception]] = []
            self._close_queues(construction_problems)
            construction_error = RuntimeError(
                f"failed to construct the background worker process: {exc}"
            )
            for label, cleanup_exc in construction_problems:
                construction_error.add_note(
                    f"cleanup also reported a problem ({label}): {cleanup_exc}"
                )
            raise construction_error from exc

        try:
            process.start()
        except Exception as exc:  # noqa: BLE001 - reported directly, not swallowed
            # A Process object whose start() raised was never actually
            # spawned as an OS process - is_alive()/terminate()/join()/
            # close() are all invalid on it, so it must never be stored or
            # treated as a live resource needing reaping.
            start_problems: list[tuple[str, Exception]] = []
            self._close_queues(start_problems)
            start_error = RuntimeError(f"background worker process failed to start: {exc}")
            for label, cleanup_exc in start_problems:
                start_error.add_note(f"cleanup also reported a problem ({label}): {cleanup_exc}")
            raise start_error from exc

        self._process = process

        startup_problems: list[tuple[str, Exception]] = []
        try:
            status, payload, handshake_problems = handshake_queue.get(
                timeout=self._handshake_timeout_seconds
            )
        except queue.Empty:
            self._reap(startup_problems)
            error = TimeoutError(
                f"background worker did not complete its startup handshake within "
                f"{self._handshake_timeout_seconds}s"
            )
            for label, exc in startup_problems:
                error.add_note(f"startup cleanup also reported a problem ({label}): {exc}")
            raise error from None

        if status == "failed":
            self._reap(startup_problems)
            error = RuntimeError(f"background worker failed to start: {payload}")
            for label, exc in [*handshake_problems, *startup_problems]:
                error.add_note(f"startup cleanup also reported a problem ({label}): {exc}")
            raise error

        self._backend_pid_value = payload
        return self

    def _reap(self, problems: list[tuple[str, Exception]]) -> None:
        """Unconditionally terminates and joins a worker process that must
        not be left running, then closes every IPC queue and the process
        object itself. Used on every __enter__ failure path: __exit__ is
        never invoked when __enter__ raises, so this method alone is
        responsible for leaving no process, queue, or process-object
        resource behind on that path."""
        assert self._process is not None
        _attempt(problems, "terminate", self._process.terminate)
        self._process.join(timeout=self._signal_join_seconds)
        if self._process.is_alive():
            _attempt(problems, "kill", self._process.kill)
            self._process.join(timeout=self._signal_join_seconds)
        if self._process.is_alive():
            problems.append(("reap", RuntimeError("process survived forcible termination")))
        else:
            self._worker_confirmed_stopped = True
            _attempt(problems, "close process object", self._process.close)
        self._close_queues(problems)

    def _close_queues(self, problems: list[tuple[str, Exception]]) -> None:
        """Closes every IPC queue this instance created and bounds the wait
        for each queue's background feeder thread to flush, attempted
        independently and failure-safely per queue regardless of whether an
        earlier queue's cleanup failed - so no queue-related file
        descriptor or thread survives the helper, and a queue that
        genuinely cannot be closed is reported rather than silently
        ignored. join_thread() is skipped for a queue whose own close()
        failed: join_thread()'s documented precondition is that close()
        already succeeded, and calling it anyway raises its own unrelated
        precondition error that would misreport a close failure as a
        feeder-thread hang."""
        for label, q in (
            ("handshake_queue", self._handshake_queue),
            ("outcome_queue", self._outcome_queue),
            ("control_queue", self._control_queue),
        ):
            if q is None:
                continue
            close_problems: list[tuple[str, Exception]] = []
            _attempt(close_problems, f"close {label}", q.close)
            problems.extend(close_problems)
            if close_problems:
                continue

            def _join_this_queue_thread(queue_to_join: Any = q) -> None:
                _bounded_join_thread(queue_to_join, 5.0)

            _attempt(problems, f"join feeder thread ({label})", _join_this_queue_thread)

    def wait_until_blocked(self, poll_connection: Connection, label: str) -> None:
        """Blocks the caller until pg_stat_activity reports this statement's
        backend genuinely waiting on a lock — proof it is truly blocked, not
        merely running slowly. (`__enter__` already guarantees the backend
        connection itself exists by the time this is called.)"""
        pid = self.backend_pid

        waiting = False
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            wait_event_type = poll_connection.execute(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :p"), {"p": pid}
            ).scalar()
            if wait_event_type == "Lock":
                waiting = True
                break
            time.sleep(0.05)
        assert waiting, f"expected {label} to be genuinely waiting on a lock"

    @staticmethod
    def _build_outcome_exception(
        status: str,
        primary_error: str | None,
        problems: list[tuple[str, Exception]],
    ) -> Exception | None:
        """Shared by resume_and_get_outcome and __exit__'s own unread-outcome
        drain, so both paths report a worker's failure identically. `status`
        is trusted as computed by the worker (`_worker_main`): "failed"
        whenever the statement itself failed, the commit failed, or any
        other cleanup step reported a problem - so a cleanup-only failure
        after an otherwise-successful commit still produces a real
        exception here, not a silent None."""
        if status != "failed":
            return None
        exc = (
            RuntimeError(primary_error)
            if primary_error is not None
            else RuntimeError("worker statement committed but its own cleanup reported problems")
        )
        if problems:
            summary = "; ".join(f"{lbl}: {e}" for lbl, e in problems)
            exc.add_note(f"worker's own cleanup also reported problems: {summary}")
        return exc

    def resume_and_get_outcome(self, label: str) -> tuple[str, Exception | None]:
        """Waits (bounded) for the blocker to commit and the original
        waiting statement to actually resume — not a substitute retry —
        then returns its real outcome."""
        assert self._process is not None and self._outcome_queue is not None
        try:
            status, primary_error, problems = self._outcome_queue.get(timeout=10.0)
        except queue.Empty:
            raise AssertionError(f"{label} thread reported no outcome within 10s") from None
        self._process.join(timeout=5.0)
        assert not self._process.is_alive(), (
            f"{label} did not resume within the bounded window after the blocking "
            "transaction's commit"
        )
        exc = self._build_outcome_exception(status, primary_error, problems)
        self.outcome.append((status, exc))
        return status, exc

    def _drain_unread_outcome(self) -> tuple[str, Exception] | None:
        """Reads any outcome the worker already produced but that nobody
        consumed via resume_and_get_outcome — called from __exit__ so a
        statement, commit, or cleanup failure inside a worker that finished
        (or was forcibly stopped after producing one) before anyone
        consumed it cannot be silently discarded. Returns None whenever
        there is nothing unread, which is the ordinary case whenever
        resume_and_get_outcome already consumed it (the queue is then
        already empty) or the worker never got far enough to produce one
        (e.g. it was forcibly terminated mid-statement)."""
        if self._outcome_queue is None:
            return None
        try:
            status, primary_error, problems = self._outcome_queue.get(timeout=2.0)
        except queue.Empty:
            return None
        exc = self._build_outcome_exception(status, primary_error, problems)
        if exc is None:
            return None
        return ("unread worker outcome", exc)

    def _with_isolated_connection(self, fn: Callable[[Connection], Any]) -> Any:
        """Runs fn against a fresh, isolated connection and guarantees the
        connection is closed no matter what fn does. A close failure is
        attached as a note rather than replacing whatever fn itself raised
        — the point of this helper is exactly that a controller-side
        verification/signaling connection can never silently leak, and can
        never let a close failure mask a real, already-happening error. If
        fn succeeds but close then fails, that close failure becomes the
        reported error, there being no more-important error already in
        flight to preserve."""
        connection = self._engine.connect()
        try:
            result = fn(connection)
        except Exception as exc:  # noqa: BLE001 - reported to the caller, not swallowed
            try:
                connection.close()
            except Exception as close_exc:  # noqa: BLE001 - attached, not swallowed
                exc.add_note(f"connection close also failed: {close_exc}")
            raise
        else:
            try:
                connection.close()
            except Exception as close_exc:  # noqa: BLE001 - reported, not swallowed
                raise RuntimeError(
                    "operation succeeded but closing its connection failed"
                ) from close_exc
            return result

    def _send_signal(self, description: str, sql: str) -> bool:
        """Issues one termination/cancellation SQL signal against the
        tracked (real, immutable) backend pid, via a separate, isolated
        connection. Isolated as its own method so regression tests can
        monkeypatch this exact seam to inject a false result or a raised
        exception without ever corrupting backend_pid itself."""

        def _do(connection: Connection) -> bool:
            sent = connection.execute(text(sql), {"p": self.backend_pid}).scalar()
            connection.commit()
            return bool(sent)

        return bool(self._with_isolated_connection(_do))

    def _cancel_via_driver(self) -> None:
        """Asks the worker process to cancel its own blocked statement via
        psycopg's driver-native cancel_safe(), relayed through the control
        queue to a watcher thread running inside that process — the
        controller never holds a live connection object to the worker's
        database session, since that connection exists entirely inside the
        worker process."""
        assert self._control_queue is not None
        self._control_queue.put("cancel")

    def _force_stop(self) -> list[tuple[str, Exception]]:
        """Layered attempt to make the worker process stop — see the class
        docstring for the full fallback chain. Every layer is followed by a
        bounded join verifying the process actually exited, not just that a
        signal was sent or accepted. The final layer (forcible OS-level
        termination) is unconditionally guaranteed to succeed, so this
        method never returns while the process is still alive."""
        assert self._process is not None
        problems: list[tuple[str, Exception]] = []

        for description, sql in (
            ("pg_terminate_backend", "SELECT pg_terminate_backend(:p)"),
            ("pg_cancel_backend", "SELECT pg_cancel_backend(:p)"),
        ):
            if not self._process.is_alive():
                break
            try:
                sent = self._send_signal(description, sql)
            except Exception as exc:  # noqa: BLE001 - collected, not swallowed
                problems.append((description, exc))
            else:
                if not sent:
                    problems.append(
                        (
                            description,
                            RuntimeError(
                                f"reported failure (no signalable backend {self.backend_pid})"
                            ),
                        )
                    )
            self._process.join(timeout=self._signal_join_seconds)

        if self._process.is_alive():
            try:
                self._cancel_via_driver()
            except Exception as exc:  # noqa: BLE001 - collected, not swallowed
                problems.append(("cancel_via_driver", exc))
            self._process.join(timeout=self._signal_join_seconds)

        if self._process.is_alive():
            # Deterministic backstop: the worker's own transaction was
            # configured with a bounded lock_timeout during __enter__,
            # before it could block on anything, so PostgreSQL itself
            # guarantees a lock-waiting statement cannot wait longer than
            # that — independent of every mechanism above. This cannot
            # rescue a statement that was never waiting on a lock at all
            # (pg_sleep, used only by the regression tests proving exactly
            # that limitation).
            self._process.join(timeout=self._lock_timeout_seconds + self._signal_join_seconds)
            if self._process.is_alive():
                problems.append(
                    (
                        "lock_timeout backstop",
                        RuntimeError(
                            f"worker still alive after its {self._lock_timeout_seconds}s "
                            "lock_timeout backstop elapsed — it was not blocked on anything "
                            "lock_timeout governs"
                        ),
                    )
                )

        if self._process.is_alive():
            # Unlike every mechanism above, this cannot fail to end the
            # process regardless of what it is doing — a real OS process,
            # unlike a Python thread, can always be forcibly reclaimed by
            # its owner. A survival here would mean that OS-level guarantee
            # itself was violated; reported like every other problem rather
            # than raised directly, so it cannot replace an
            # already-propagating exception at a higher level.
            _attempt(problems, "terminate", self._process.terminate)
            self._process.join(timeout=self._signal_join_seconds)
            if self._process.is_alive():
                _attempt(problems, "kill", self._process.kill)
                self._process.join(timeout=self._signal_join_seconds)
            if self._process.is_alive():
                problems.append(
                    (
                        "forced termination",
                        RuntimeError(
                            "worker process survived forcible termination — an OS-level "
                            "guarantee was violated"
                        ),
                    )
                )
            else:
                problems.append(
                    (
                        "forced termination",
                        RuntimeError(
                            "every graceful mechanism failed; the worker was forcibly terminated"
                        ),
                    )
                )
            # Ending our own client-side process guarantees *our* resources
            # are reclaimed, but does not by itself guarantee PostgreSQL has
            # noticed: a backend blocked inside a call that never touches
            # its client socket (pg_sleep, unlike a lock wait) can keep
            # running until it next tries to communicate, regardless of the
            # client's TCP connection already being gone — PostgreSQL has
            # no built-in reason to poll for that on its own. Unconditionally
            # ask PostgreSQL itself to end that backend too, through a real
            # (not the mockable _send_signal seam) pg_terminate_backend()
            # call, independent of whatever fault injection did to the
            # graceful attempt earlier in this method, and regardless of
            # whether the process itself was confirmed dead above — this is
            # the "by whatever means necessary" guarantee, not a best-effort
            # repeat.
            _attempt(
                problems,
                "authoritative pg_terminate_backend",
                self._terminate_backend_unconditionally,
            )

        self._verify_backend_gone(problems)
        return problems

    def _terminate_backend_unconditionally(self) -> None:
        """A real, always-executed `pg_terminate_backend()` call — distinct
        from the mockable `_send_signal()` seam used earlier in the
        fallback chain — so the guaranteed final termination step always
        actually asks PostgreSQL to end the backend, regardless of what
        fault injection did to the graceful attempt above. Not itself part
        of what regression tests mock: it exists specifically so the
        "everything mocked to fail" tests still prove the backend is
        genuinely gone, not just that this process no longer exists."""

        def _do(connection: Connection) -> None:
            connection.execute(text("SELECT pg_terminate_backend(:p)"), {"p": self.backend_pid})
            connection.commit()

        self._with_isolated_connection(_do)

    def _query_backend_state(self) -> tuple[str, bool] | None:
        """One failure-safe pg_stat_activity lookup for backend_pid. Returns
        None if no row exists (the backend is gone), or (state,
        in_transaction) if one does — in_transaction is true whenever the
        backend's own transaction is still open, which for this test
        suite's exclusive use of pg_advisory_xact_lock (transaction-scoped,
        released at COMMIT/ROLLBACK) is also a complete proxy for "does this
        backend still hold any advisory lock it took": the lock cannot
        outlive the transaction. A query failure here (connection refused,
        etc.) propagates to the caller rather than being interpreted as the
        backend being gone."""

        def _do(connection: Connection) -> tuple[str, bool] | None:
            row = connection.execute(
                text("SELECT state, (xact_start IS NOT NULL) FROM pg_stat_activity WHERE pid = :p"),
                {"p": self.backend_pid},
            ).one_or_none()
            return None if row is None else (row[0], bool(row[1]))

        result: tuple[str, bool] | None = self._with_isolated_connection(_do)
        return result

    def _verify_backend_gone(self, problems: list[tuple[str, Exception]]) -> None:
        """Confirms, through fresh connections, that the worker's backend
        has actually disappeared from pg_stat_activity — the OS process
        exiting (gracefully or by force) does not by itself guarantee
        PostgreSQL has already noticed the dropped connection at the exact
        instant this method runs, so this polls briefly rather than
        assuming it. Distinguishes three outcomes, never conflating any of
        them with "gone": the backend is present but idle with no open
        transaction; the backend is present and still active or holding a
        transaction; or verification itself could not be completed (a
        fresh connection could not be established, or the query failed) —
        which must never be treated as proof the backend disappeared. This
        method never raises: every failure it encounters, including its own
        query failing, is appended to problems instead, so a verification
        error can never replace an exception already propagating from a
        caller further up the stack."""
        deadline = time.monotonic() + 5.0
        verification_error: Exception | None = None
        last_state: str | None = None
        while time.monotonic() < deadline:
            try:
                row = self._query_backend_state()
            except Exception as exc:  # noqa: BLE001 - collected, not swallowed or re-raised
                verification_error = exc
                time.sleep(0.05)
                continue
            verification_error = None
            if row is None:
                return
            state, in_transaction = row
            last_state = f"state={state!r} in_transaction={in_transaction}"
            time.sleep(0.05)

        if verification_error is not None:
            problems.append(
                (
                    "backend liveness verification",
                    RuntimeError(
                        f"could not verify backend pid {self.backend_pid} disappeared: "
                        f"{verification_error}"
                    ),
                )
            )
            return

        problems.append(
            (
                "backend liveness verification",
                RuntimeError(
                    f"backend pid {self.backend_pid} was still present in pg_stat_activity "
                    f"5s after its owning process exited ({last_state})"
                ),
            )
        )

    def __exit__(self, exc_type: object, exc: BaseException | None, tb: object) -> bool:
        problems: list[tuple[str, Exception]] = []
        if self._process is not None and self._process.is_alive():
            problems.extend(self._force_stop())

        # Whether the worker exited on its own or was just forcibly
        # stopped, drain any outcome it left behind: a statement, commit,
        # or cleanup failure the caller never consumed via
        # resume_and_get_outcome must not be silently discarded just
        # because nobody explicitly asked for it.
        unread_outcome = self._drain_unread_outcome()
        if unread_outcome is not None:
            problems.append(unread_outcome)

        if self._process is not None:
            if self._process.is_alive():
                problems.append(
                    (
                        "close process object",
                        RuntimeError("process still alive; refusing to close its object"),
                    )
                )
            else:
                self._worker_confirmed_stopped = True
                _attempt(problems, "close process object", self._process.close)

        self._close_queues(problems)

        if not problems:
            return False
        summary = "; ".join(f"{label}: {e}" for label, e in problems)
        message = f"_BackgroundStatement cleanup encountered problems: {summary}"
        if exc is not None:
            exc.add_note(message)
            return False
        raise RuntimeError(message)


# ---------------------------------------------------------------------------
# _BackgroundStatement's own cleanup contract
# ---------------------------------------------------------------------------
# The helper above is tested in isolation from any production trigger or
# advisory-lock function: a plain pg_advisory_xact_lock stands in for
# whatever a real blocked statement would be waiting on. That keeps these
# tests from depending on (or having to deliberately break) revision 048/053/
# 056's actual locking logic, while still proving the helper's own forced-
# cleanup guarantees hold against a genuinely blocked backend.


class _SentinelFailure(Exception):
    """A synthetic, easily-distinguished failure standing in for "the with
    block's body raised" — used to prove forced cleanup preserves whatever
    exception was already propagating rather than replacing or losing it."""


def _failing_send_signal(mode: str) -> Callable[[str, str], bool]:
    """A `_send_signal` replacement for monkeypatching onto one instance:
    fails every signal attempt, either by returning `False`
    (`mode="returns_false"`) or by raising (`mode="raises"`)."""

    def _send(description: str, sql: str) -> bool:
        if mode == "raises":
            raise _InjectedFailure(f"simulated {description} failure")
        return False

    return _send


def _failing_cancel_via_driver() -> None:
    """A `_cancel_via_driver` replacement for monkeypatching: simulates the
    driver-native cancellation itself failing, so whatever comes after it
    (the `lock_timeout` backstop, or — for the pg_sleep-based tests —
    forced termination) is what has to take over."""
    raise _InjectedFailure("simulated cancel_via_driver failure")


def _failing_terminate_unconditionally() -> None:
    """A `_terminate_backend_unconditionally` replacement for
    monkeypatching: simulates the final, otherwise-unconditional
    `pg_terminate_backend()` call itself failing, distinct from every
    earlier (already independently tested) fallback in the chain."""
    raise _InjectedFailure("simulated authoritative pg_terminate_backend failure")


def _raise_injected_failure(*_args: object, **_kwargs: object) -> None:
    """A generic monkeypatch replacement for any zero-meaningful-args
    method that should simulate failure without performing its real
    action — used for IPC/process-object cleanup seams."""
    raise _InjectedFailure("simulated cleanup failure")


def _assert_backend_eventually_gone(engine: Engine, pid: int, timeout: float = 5.0) -> None:
    """Polls pg_stat_activity from a fresh, independent connection until the
    given backend pid disappears — proof its connection, transaction, and
    any advisory lock it held are actually gone, not merely that the
    controller believes the worker process exited."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with engine.connect() as checker:
            still_present = checker.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE pid = :p)"), {"p": pid}
            ).scalar()
        if not still_present:
            return
        time.sleep(0.05)
    raise AssertionError(
        f"backend pid {pid} was still present in pg_stat_activity after {timeout}s — its "
        "connection, transaction, or advisory lock may have survived cleanup"
    )


def test_background_statement_forced_cleanup_terminates_a_genuinely_blocked_worker(
    postgres_engine: Engine,
) -> None:
    """The main thread's transaction never commits — deliberately, since the
    point is proving forced cleanup, not normal resumption — and the `with`
    block exits early via a synthetic failure while the worker is still
    genuinely blocked on the lock. Cleanup must still terminate it, via the
    real (unmocked) primary signal path."""
    engine = postgres_engine
    lock_key = uuid.uuid4().int % (2**63 - 1)

    with engine.connect() as first:
        first.begin()
        first.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key})

        worker_pid: int | None = None
        try:
            with (
                pytest.raises(_SentinelFailure),
                _BackgroundStatement(
                    engine, "SELECT pg_advisory_xact_lock(:k)", {"k": lock_key}
                ) as blocked,
            ):
                blocked.wait_until_blocked(first, "the sentinel-blocked worker")
                worker_pid = blocked.backend_pid
                raise _SentinelFailure("deliberate failure while the worker is still blocked")

            assert worker_pid is not None
            _assert_backend_eventually_gone(engine, worker_pid)
        finally:
            # Safety-net cleanup in finally, not sequential code: if any
            # assertion above ever fails, `first` (and the advisory lock it
            # holds) must still be released rather than leaking into later
            # tests. __exit__ should already have terminated the worker via
            # the real, primary signal path in this test — this is a
            # backstop, not the primary proof point.
            first.rollback()


@pytest.mark.parametrize("mode", ["returns_false", "raises"])
def test_background_statement_falls_back_to_driver_native_cancel_when_sql_signals_fail(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """Both `pg_terminate_backend` and `pg_cancel_backend` are made to fail
    (as a false result, or by raising, per `mode`) via the `_send_signal`
    seam — `backend_pid` itself is never touched. The real, unmocked
    driver-native `cancel_safe()` (relayed to the worker process) must then
    take over and stop the genuinely blocked worker."""
    engine = postgres_engine
    lock_key = uuid.uuid4().int % (2**63 - 1)

    with engine.connect() as first:
        first.begin()
        first.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key})

        blocked = _BackgroundStatement(engine, "SELECT pg_advisory_xact_lock(:k)", {"k": lock_key})
        monkeypatch.setattr(blocked, "_send_signal", _failing_send_signal(mode))

        worker_pid: int | None = None
        try:
            with pytest.raises(_SentinelFailure), blocked:
                blocked.wait_until_blocked(first, "the worker (SQL signals mocked to fail)")
                worker_pid = blocked.backend_pid
                raise _SentinelFailure("deliberate failure with SQL signals disabled")

            assert worker_pid is not None
            _assert_backend_eventually_gone(engine, worker_pid)
        finally:
            first.rollback()


def test_background_statement_falls_back_to_lock_timeout_backstop_when_every_active_mechanism_fails(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every *active* fallback — both SQL signals, and driver-native
    `cancel_safe()` — is mocked to fail, proving the passive layer still
    works: the `lock_timeout` PostgreSQL itself enforces on the worker's own
    transaction, configured during `__enter__` before the worker could block
    on anything. Short bounds keep this test fast while still proving the
    mechanism deterministically, not by luck."""
    engine = postgres_engine
    lock_key = uuid.uuid4().int % (2**63 - 1)

    with engine.connect() as first:
        first.begin()
        first.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key})

        blocked = _BackgroundStatement(
            engine,
            "SELECT pg_advisory_xact_lock(:k)",
            {"k": lock_key},
            lock_timeout_seconds=2.0,
            signal_join_seconds=1.0,
        )
        monkeypatch.setattr(blocked, "_send_signal", _failing_send_signal("raises"))
        monkeypatch.setattr(blocked, "_cancel_via_driver", _failing_cancel_via_driver)

        worker_pid: int | None = None
        try:
            with pytest.raises(_SentinelFailure), blocked:
                blocked.wait_until_blocked(
                    first, "the worker (every active mechanism mocked to fail)"
                )
                worker_pid = blocked.backend_pid
                raise _SentinelFailure("deliberate failure with every active mechanism disabled")

            assert worker_pid is not None
            _assert_backend_eventually_gone(engine, worker_pid)
        finally:
            first.rollback()


def test_background_statement_forcibly_terminates_the_worker_and_preserves_the_original_exception_when_nothing_else_stops_it(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one case no graceful mechanism can rescue: every active
    mechanism (both SQL signals and driver-native cancellation) mocked to
    fail, and the worker is not waiting on a lock at all (`pg_sleep`, not
    `pg_advisory_xact_lock`), so the `lock_timeout` backstop every other
    regression test relies on has nothing to cancel either. `__exit__` must
    still guarantee the worker is gone — via forcible OS-level termination —
    before it returns, with no join or manual cleanup performed by this
    test after the `with` block. The with block's own sentinel failure must
    remain the primary, reported cause; the forced-termination problem is
    attached as a note."""
    engine = postgres_engine
    # Comfortably longer than every bounded fallback step combined, so the
    # only way this worker ever stops is forced termination — never a race
    # against pg_sleep finishing naturally.
    sleep_seconds = 30.0
    blocked = _BackgroundStatement(
        engine,
        "SELECT pg_sleep(:s)",
        {"s": sleep_seconds},
        lock_timeout_seconds=1.0,
        signal_join_seconds=1.0,
    )
    monkeypatch.setattr(blocked, "_send_signal", _failing_send_signal("raises"))
    monkeypatch.setattr(blocked, "_cancel_via_driver", _failing_cancel_via_driver)

    with pytest.raises(_SentinelFailure) as excinfo, blocked:
        # No wait_until_blocked here: pg_sleep never reports wait_event_type
        # 'Lock', so there is nothing to poll for — the worker starts
        # sleeping essentially immediately after __enter__ returns (which
        # itself only returns once the connection, its lock_timeout, and
        # its backend pid are all established).
        raise _SentinelFailure("deliberate failure while nothing can stop the worker early")

    # __exit__ has already returned by this point. Everything below is
    # independent proof that containment is complete, not part of making
    # cleanup happen — there is no join() or process manipulation here.
    assert isinstance(excinfo.value, _SentinelFailure), (
        "the original sentinel failure must still be what propagates"
    )
    notes = "\n".join(getattr(excinfo.value, "__notes__", []))
    assert "forcibly terminated" in notes.lower(), (
        f"expected the forced-termination problem to be reported on the propagated "
        f"exception via add_note, got notes: {notes!r}"
    )
    assert blocked.worker_confirmed_stopped, "the worker process must not survive __exit__"
    _assert_backend_eventually_gone(engine, blocked.backend_pid)


def test_background_statement_cleanup_failure_fails_the_test_when_no_original_exception(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same fault injection as above, but the with block exits normally —
    no exception of its own — while nothing can stop the worker early.
    `__exit__` itself must raise, since there is no already-propagating
    exception for it to attach the forced-termination problem to — but only
    once the worker is actually gone, not instead of terminating it. No
    join or manual cleanup is performed by this test after the `with`
    block."""
    engine = postgres_engine
    sleep_seconds = 30.0
    blocked = _BackgroundStatement(
        engine,
        "SELECT pg_sleep(:s)",
        {"s": sleep_seconds},
        lock_timeout_seconds=1.0,
        signal_join_seconds=1.0,
    )
    monkeypatch.setattr(blocked, "_send_signal", _failing_send_signal("returns_false"))
    monkeypatch.setattr(blocked, "_cancel_via_driver", _failing_cancel_via_driver)

    with pytest.raises(RuntimeError, match="forcibly terminated"), blocked:
        pass  # No exception here: __exit__ not raising is the only way this test can fail.

    assert blocked.worker_confirmed_stopped, "the worker process must not survive __exit__"
    _assert_backend_eventually_gone(engine, blocked.backend_pid)


@pytest.mark.parametrize(
    "stage",
    ["after_connect", "after_begin", "after_set_lock_timeout", "after_pid_lookup"],
)
def test_background_statement_enter_reports_startup_failure_at_each_partial_stage(
    postgres_engine: Engine, stage: str
) -> None:
    """Injects a failure at each point after a resource has been partially
    acquired during worker startup — after the connection, after the
    transaction begins, after `lock_timeout` is set, and after the backend
    pid is looked up — deterministically, via the worker's own
    fault_injection_stage hook rather than a real, hard-to-construct
    database failure. For every stage, `__enter__` must fail predictably
    and leave no worker process alive; the worker's own except-block
    cleanup (rollback, close, dispose) runs inside the now-confirmed-dead
    process."""
    engine = postgres_engine
    blocked = _BackgroundStatement(engine, "SELECT 1", {}, _fault_injection_stage=stage)
    with pytest.raises(RuntimeError, match="failed to start") as excinfo:
        blocked.__enter__()
    assert stage in str(excinfo.value), f"expected the injected stage {stage!r} to be reported"
    assert blocked._process is not None
    assert blocked.worker_confirmed_stopped


def test_background_statement_enter_reports_both_startup_and_cleanup_failures_together(
    postgres_engine: Engine,
) -> None:
    """The worker's own connection becomes unexpectedly unusable at the
    exact moment startup fails, so the except block's own cleanup attempts
    (rollback, close) genuinely fail too — a real secondary failure, not a
    synthetic one. Proves both the primary startup error and the secondary
    cleanup errors are preserved (as notes), not swallowed, and that
    `__enter__` still fails predictably with no worker left alive."""
    engine = postgres_engine
    blocked = _BackgroundStatement(
        engine, "SELECT 1", {}, _fault_injection_stage="after_begin_kill_then_fail"
    )
    with pytest.raises(RuntimeError, match="failed to start") as excinfo:
        blocked.__enter__()
    notes = "\n".join(getattr(excinfo.value, "__notes__", []))
    assert "cleanup" in notes.lower(), (
        f"expected startup cleanup problems to be reported as notes, got: {notes!r}"
    )
    assert blocked._process is not None
    assert blocked.worker_confirmed_stopped


def test_background_statement_enter_times_out_and_reaps_a_slow_starting_worker(
    postgres_engine: Engine,
) -> None:
    """Simulates a worker whose startup handshake genuinely takes longer
    than `__enter__` is willing to wait — deterministically, via a real
    sleep the test controls, not by depending on actual network stalls.
    Proves `__enter__` raises within a bounded interval and that the slow
    worker is terminated and reaped before `__enter__` returns, not left to
    finish connecting on its own afterward."""
    engine = postgres_engine
    blocked = _BackgroundStatement(
        engine,
        "SELECT 1",
        {},
        handshake_timeout_seconds=1.0,
        _startup_delay_seconds=5.0,
    )
    start = time.monotonic()
    with pytest.raises(TimeoutError, match="startup handshake"):
        blocked.__enter__()
    elapsed = time.monotonic() - start
    assert elapsed < 4.0, (
        f"expected __enter__ to raise well before the worker's own 5s startup delay, "
        f"took {elapsed:.1f}s"
    )
    assert blocked._process is not None
    assert blocked.worker_confirmed_stopped


def test_background_statement_enter_fails_with_no_process_alive_when_a_real_connection_is_refused(
    postgres_engine: Engine,
) -> None:
    """Complements the deterministic fault-injection tests above with a
    real (not injected) connection failure — a local port nothing listens
    on. Confirms the same structural guarantee holds for a genuine driver
    error, whatever its exact type and message on the platform running the
    test."""
    unreachable_engine = create_engine(postgres_engine.url.set(host="127.0.0.1", port=1))
    blocked = _BackgroundStatement(unreachable_engine, "SELECT 1", {})
    with pytest.raises(RuntimeError, match="failed to start"):
        blocked.__enter__()
    assert blocked._process is not None
    assert blocked.worker_confirmed_stopped


# ---------------------------------------------------------------------------
# Worker outcome and cleanup reporting protocol
# ---------------------------------------------------------------------------
# The tests above cover startup (before the worker's statement ever runs);
# these cover the statement/commit/cleanup path afterward — proving a
# successful statement followed by a commit failure is never reported as
# committed, a cleanup-only failure after a genuine commit still fails the
# caller, and an outcome nobody explicitly consumed is still drained and
# reported by __exit__ rather than silently discarded.


def test_background_statement_reports_the_statement_error_when_the_statement_itself_fails(
    postgres_engine: Engine,
) -> None:
    """A baseline case distinct from the five concurrency tests below: a
    statement that fails for an ordinary reason (not a business-rule
    trigger), with nothing else going wrong during cleanup. Proves the
    statement's own error is what gets reported."""
    engine = postgres_engine
    blocked = _BackgroundStatement(engine, "SELECT 1/0", {})
    with blocked:
        status, exc = blocked.resume_and_get_outcome("statement-failure probe")

    assert status == "failed"
    assert exc is not None
    assert "division by zero" in str(exc).lower()


def test_background_statement_reports_failure_when_commit_fails_after_a_successful_statement(
    postgres_engine: Engine,
) -> None:
    """The statement itself succeeds, but the connection becomes genuinely
    unusable before commit() is attempted (mirroring the startup section's
    after_begin_kill_then_fail one phase later), so commit() fails for
    real — not mocked. The rollback-after-commit-failure attempt is also
    exercised (this is the "where applicable" case), but SQLAlchemy's own
    rollback() turns out to be a safe no-op here too: once commit() has
    already failed, SQLAlchemy's bookkeeping no longer considers the
    transaction active, mirroring the same no-op behavior the tenth pass
    found for rollback()/close() before begin() ever ran — so it does not
    itself report a second problem. What this test proves is the primary
    contract: the outcome is reported as "failed", never "committed" — the
    register's explicit requirement that a successful statement followed by
    a commit failure must never be reported as committed."""
    engine = postgres_engine
    blocked = _BackgroundStatement(
        engine, "SELECT 1", {}, _fault_injection_stage="after_statement_kill_then_fail"
    )
    with blocked:
        status, exc = blocked.resume_and_get_outcome("commit-failure probe")

    assert status == "failed", f"a failed commit must never be reported as committed, got: {status}"
    assert exc is not None
    assert "closed" in str(exc).lower(), (
        f"expected the commit failure's own connection-closed message to be the reported "
        f"cause, got: {exc}"
    )


@pytest.mark.parametrize("stage", ["close_fails", "dispose_fails"])
def test_background_statement_reports_failure_for_a_cleanup_only_problem_after_a_successful_commit(
    postgres_engine: Engine, stage: str
) -> None:
    """The statement and its commit both genuinely succeed, but a
    deterministically injected failure in close() or dispose() afterward
    must still fail the caller — the register's explicit requirement that a
    cleanup-only failure fails the test even though the transaction itself
    was fine."""
    engine = postgres_engine
    blocked = _BackgroundStatement(engine, "SELECT 1", {}, _fault_injection_stage=stage)
    with blocked:
        status, exc = blocked.resume_and_get_outcome(f"cleanup-only probe ({stage})")

    assert status == "failed", (
        f"a cleanup-only failure ({stage}) after a successful commit must still be "
        f"reported as failed, got: {status}"
    )
    assert exc is not None
    expected_label = "close" if stage == "close_fails" else "dispose"
    notes = "\n".join(getattr(exc, "__notes__", []))
    assert expected_label in notes.lower(), (
        f"expected {expected_label!r} to be reported, got notes: {notes!r}"
    )


def test_background_statement_exit_drains_and_reports_an_outcome_nobody_consumed(
    postgres_engine: Engine,
) -> None:
    """The with block never calls resume_and_get_outcome — the worker
    finishes a failing statement on its own before the block exits (proven
    by polling before __exit__ ever runs, not after). Proves __exit__
    itself drains the outcome queue and fails the test, rather than
    silently discarding a failure nobody explicitly asked for."""
    engine = postgres_engine

    def _run_and_wait_for_natural_exit() -> None:
        with _BackgroundStatement(engine, "SELECT 1/0", {}) as blocked:
            # Still inside the with block, so __exit__ (and its
            # worker_confirmed_stopped bookkeeping) has not run yet — the
            # process object itself is still open here, so is_alive() is
            # the right check for this specific pre-__exit__ wait.
            deadline = time.monotonic() + 5.0
            while blocked._process.is_alive() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert not blocked._process.is_alive(), (
                "worker did not finish the fast failing statement in time"
            )

    with pytest.raises(RuntimeError, match="division by zero"):
        _run_and_wait_for_natural_exit()


# ---------------------------------------------------------------------------
# Controller-side database cleanup failure-safety
# ---------------------------------------------------------------------------


def test_background_statement_reports_a_problem_when_the_final_termination_call_itself_fails(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every earlier fallback (both SQL signals, driver-native cancel) is
    also mocked to fail, and the worker is not lock-bound (pg_sleep), so
    _force_stop reaches its final, otherwise-unconditional
    pg_terminate_backend call — which is itself mocked to fail here, unlike
    every previous review's regression tests, which left it operational.
    Proves that failure is reported as a note on the original exception
    rather than propagating uncaught and replacing it, and that the worker
    process is still forcibly terminated regardless."""
    engine = postgres_engine
    sleep_seconds = 30.0
    blocked = _BackgroundStatement(
        engine,
        "SELECT pg_sleep(:s)",
        {"s": sleep_seconds},
        lock_timeout_seconds=1.0,
        signal_join_seconds=1.0,
    )
    monkeypatch.setattr(blocked, "_send_signal", _failing_send_signal("raises"))
    monkeypatch.setattr(blocked, "_cancel_via_driver", _failing_cancel_via_driver)
    monkeypatch.setattr(
        blocked, "_terminate_backend_unconditionally", _failing_terminate_unconditionally
    )

    worker_pid: int | None = None
    try:
        with pytest.raises(_SentinelFailure) as excinfo, blocked:
            worker_pid = blocked.backend_pid
            raise _SentinelFailure("deliberate failure while the final termination call also fails")

        assert isinstance(excinfo.value, _SentinelFailure)
        notes = "\n".join(getattr(excinfo.value, "__notes__", []))
        assert "authoritative pg_terminate_backend" in notes, (
            f"expected the final termination failure to be reported as a note, got: {notes!r}"
        )
        assert blocked.worker_confirmed_stopped, (
            "the worker process must still be forcibly terminated"
        )
    finally:
        # Safety net, not proof: with the authoritative termination call
        # itself mocked away, nothing in the mechanism under test ever
        # actually told PostgreSQL to stop this pg_sleep-blocked backend —
        # a real, unmocked terminate keeps it from lingering in the shared
        # dev database for the statement's full 30s duration.
        if worker_pid is not None:
            with engine.connect() as cleanup_conn:
                cleanup_conn.execute(text("SELECT pg_terminate_backend(:p)"), {"p": worker_pid})
                cleanup_conn.commit()


def test_background_statement_reports_a_problem_when_backend_verification_itself_fails(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backend-state verification itself is mocked to fail (simulating a
    verification connection being unreachable), while the real termination
    signal is left operational. Proves the verification failure is reported
    as a distinct problem — never silently treated as proof the backend
    disappeared — and never replaces the original test-body exception."""
    engine = postgres_engine
    lock_key = uuid.uuid4().int % (2**63 - 1)

    with engine.connect() as first:
        first.begin()
        first.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key})

        blocked = _BackgroundStatement(engine, "SELECT pg_advisory_xact_lock(:k)", {"k": lock_key})
        monkeypatch.setattr(blocked, "_query_backend_state", _raise_injected_failure)

        worker_pid: int | None = None
        try:
            with pytest.raises(_SentinelFailure) as excinfo, blocked:
                blocked.wait_until_blocked(first, "the worker (verification mocked to fail)")
                worker_pid = blocked.backend_pid
                raise _SentinelFailure("deliberate failure with verification mocked to fail")

            assert isinstance(excinfo.value, _SentinelFailure)
            notes = "\n".join(getattr(excinfo.value, "__notes__", []))
            assert "could not verify" in notes.lower(), (
                f"expected the verification failure to be reported distinctly, got: {notes!r}"
            )
            assert worker_pid is not None
            assert blocked.worker_confirmed_stopped, "the worker must still be terminated for real"
            _assert_backend_eventually_gone(engine, worker_pid)
        finally:
            first.rollback()


# ---------------------------------------------------------------------------
# Process startup, reaping, and IPC cleanup
# ---------------------------------------------------------------------------


def test_background_statement_enter_reports_process_construction_failure(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """multiprocessing.Process(...) construction itself is mocked to fail —
    a real OS-level trigger for this is impractical to construct
    deterministically. Proves __enter__ reports it clearly, with no process
    ever stored (there is nothing valid to reap), and its queues still
    closed."""
    engine = postgres_engine
    ctx = multiprocessing.get_context("spawn")
    monkeypatch.setattr(ctx, "Process", _raise_injected_failure)
    monkeypatch.setattr(multiprocessing, "get_context", lambda method: ctx)

    blocked = _BackgroundStatement(engine, "SELECT 1", {})
    with pytest.raises(RuntimeError, match="failed to construct"):
        blocked.__enter__()
    assert blocked._process is None


def test_background_statement_enter_reports_process_start_failure(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """multiprocessing.Process.start() itself is mocked to fail — again, a
    real OS-level trigger (resource exhaustion) is impractical to construct
    deterministically. Proves __enter__ reports it clearly, and that
    self._process is left None: a Process object whose start() raised was
    never actually spawned, so it must never be treated as a live resource
    needing reaping (is_alive()/terminate()/close() are all invalid on
    it)."""
    engine = postgres_engine
    ctx = multiprocessing.get_context("spawn")
    monkeypatch.setattr(ctx.Process, "start", _raise_injected_failure)
    monkeypatch.setattr(multiprocessing, "get_context", lambda method: ctx)

    blocked = _BackgroundStatement(engine, "SELECT 1", {})
    with pytest.raises(RuntimeError, match="failed to start"):
        blocked.__enter__()
    assert blocked._process is None


def test_background_statement_escalates_to_kill_when_terminate_does_not_stop_the_process(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """terminate() is mocked to a no-op — simulating an edge case where it
    does not actually stop the process — while kill() is left real. Proves
    _force_stop detects the process is still alive after terminate() and
    escalates to kill(), which genuinely stops it."""
    engine = postgres_engine
    sleep_seconds = 30.0
    blocked = _BackgroundStatement(
        engine,
        "SELECT pg_sleep(:s)",
        {"s": sleep_seconds},
        lock_timeout_seconds=1.0,
        signal_join_seconds=1.0,
    )
    monkeypatch.setattr(blocked, "_send_signal", _failing_send_signal("raises"))
    monkeypatch.setattr(blocked, "_cancel_via_driver", _failing_cancel_via_driver)

    with pytest.raises(_SentinelFailure), blocked:
        monkeypatch.setattr(blocked._process, "terminate", lambda: None)
        raise _SentinelFailure("deliberate failure with terminate() mocked to a no-op")

    assert blocked.worker_confirmed_stopped, "kill() must still have stopped the process"


def test_background_statement_reports_a_problem_when_a_queue_fails_to_close(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One IPC queue's close() is mocked to fail after a fast, successful
    statement. Proves the failure is collected as a problem — reported by
    __exit__ — rather than propagating uncaught, and that cleanup for the
    other queues and the process object still proceeds regardless."""
    engine = postgres_engine

    def _run() -> None:
        with _BackgroundStatement(engine, "SELECT 1", {}) as blocked:
            blocked.resume_and_get_outcome("queue-close-failure probe")
            monkeypatch.setattr(blocked._outcome_queue, "close", _raise_injected_failure)

    with pytest.raises(RuntimeError, match="close outcome_queue"):
        _run()


def test_background_statement_reports_a_problem_when_the_process_object_fails_to_close(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Process object's own close() is mocked to fail after a fast,
    successful statement. Proves the failure is collected and reported by
    __exit__ rather than propagating uncaught."""
    engine = postgres_engine

    def _run() -> None:
        with _BackgroundStatement(engine, "SELECT 1", {}) as blocked:
            blocked.resume_and_get_outcome("process-close-failure probe")
            monkeypatch.setattr(blocked._process, "close", _raise_injected_failure)

    with pytest.raises(RuntimeError, match="close process object"):
        _run()


def test_a_concurrent_subtype_insert_and_type_change_is_serialized(
    postgres_engine: Engine,
) -> None:
    """The generic race: one transaction inserts a subtype row
    (world.dungeons) for an entity while another concurrently retypes that
    same entity away from 'dungeon'. core.enforce_entity_subtype() (the
    generic, table-agnostic check every subtype table shares) and
    core.enforce_entity_type_change() must serialize on the same entity,
    not just the dungeon-specific pair — and the retype, left genuinely
    waiting rather than timed out, must resume and be rejected once the
    insert commits, leaving the entity's type and its subtype row in
    agreement."""
    engine = postgres_engine
    slug = f"subtype-lock-generic-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            world = make_world(setup, slug=slug)
            dungeon = make_location(setup, world, entity_type_code="dungeon")
            region_type = lookup_id(setup, "core", "entity_types", "entity_type_id", "region")

        with engine.connect() as first:
            first.begin()

            # Transaction 1: insert the subtype row. Still uncommitted.
            first.execute(
                text("INSERT INTO world.dungeons (dungeon_id) VALUES (:d)"), {"d": dungeon}
            )

            with _BackgroundStatement(
                engine,
                "UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e",
                {"t": region_type, "e": dungeon},
            ) as blocked:
                blocked.wait_until_blocked(first, "the concurrent retype away from 'dungeon'")
                first.commit()
                result, exc = blocked.resume_and_get_outcome("the concurrent retype")

        assert result == "failed", f"expected the resumed retype to be rejected, got: {result}"
        assert "cannot change type" in str(exc)

        with engine.connect() as verify:
            entity_type = verify.execute(
                text(
                    "SELECT et.code FROM core.entities e "
                    "JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id "
                    "WHERE e.entity_id = :e"
                ),
                {"e": dungeon},
            ).scalar()
            has_dungeons_row = verify.execute(
                text("SELECT EXISTS (SELECT 1 FROM world.dungeons WHERE dungeon_id = :d)"),
                {"d": dungeon},
            ).scalar()
        assert entity_type == "dungeon", (
            "the committed subtype insert must have kept the entity dungeon-typed"
        )
        assert has_dungeons_row is True, (
            "the committed world.dungeons subtype row must remain — no subtype row may end up "
            "incompatible with core.entities.entity_type"
        )
    finally:
        _cleanup_world(engine, slug)


def test_a_concurrent_dungeon_area_insert_and_marker_removal_plus_retype_is_serialized(
    postgres_engine: Engine,
) -> None:
    """The compound race the review named explicitly: one transaction
    removes world.dungeons (permitted per conventions §7.5) and retypes the
    parent away from 'dungeon' while another concurrently inserts a new
    dungeon_area parented under that same entity. world.enforce_dungeon_
    area_parent_dungeon() (checking "is my parent dungeon-typed") and
    world.enforce_dungeon_type_change_preserves_areas() (checking "do I have
    dungeon-area children") must serialize on the dungeon's own entity_id,
    and the insert, left genuinely waiting, must resume and be rejected once
    the retype commits — leaving no dungeon-area row dependent on an entity
    no longer registered as a dungeon."""
    engine = postgres_engine
    slug = f"subtype-lock-area-insert-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            world = make_world(setup, slug=slug)
            dungeon = make_location(setup, world, entity_type_code="dungeon")
            setup.execute(
                text("INSERT INTO world.dungeons (dungeon_id) VALUES (:d)"), {"d": dungeon}
            )
            area = make_location(
                setup, world, parent_location_id=dungeon, entity_type_code="dungeon_area"
            )
            region_type = lookup_id(setup, "core", "entity_types", "entity_type_id", "region")

        with engine.connect() as first:
            first.begin()

            # Transaction 1: remove the marker, then retype the dungeon
            # away. Still uncommitted.
            first.execute(text("DELETE FROM world.dungeons WHERE dungeon_id = :d"), {"d": dungeon})
            first.execute(
                text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
                {"t": region_type, "e": dungeon},
            )

            with _BackgroundStatement(
                engine,
                "INSERT INTO world.dungeon_areas (dungeon_area_id) VALUES (:a)",
                {"a": area},
            ) as blocked:
                blocked.wait_until_blocked(first, "the concurrent dungeon_area insert")
                first.commit()
                result, exc = blocked.resume_and_get_outcome("the concurrent dungeon_area insert")

        assert result == "failed", f"expected the resumed insert to be rejected, got: {result}"
        assert "not dungeon" in str(exc)

        with engine.connect() as verify:
            entity_type = verify.execute(
                text(
                    "SELECT et.code FROM core.entities e "
                    "JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id "
                    "WHERE e.entity_id = :e"
                ),
                {"e": dungeon},
            ).scalar()
            has_dungeons_row = verify.execute(
                text("SELECT EXISTS (SELECT 1 FROM world.dungeons WHERE dungeon_id = :d)"),
                {"d": dungeon},
            ).scalar()
            has_area_row = verify.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM world.dungeon_areas WHERE dungeon_area_id = :a)"
                ),
                {"a": area},
            ).scalar()
        assert entity_type == "region", "the committed retype must have taken effect"
        assert has_dungeons_row is False, "the committed marker removal must have taken effect"
        assert has_area_row is False, (
            "the rejected dungeon_area insert must not have taken effect — no dungeon-area row "
            "may remain dependent on an entity no longer registered as a dungeon"
        )
    finally:
        _cleanup_world(engine, slug)


def test_a_concurrent_dungeon_area_reparent_and_retype_is_serialized(
    postgres_engine: Engine,
) -> None:
    """Reparenting an existing dungeon_area under a dungeon while another
    transaction concurrently retypes that same dungeon away — the two sides
    of "does this dungeon still have area children," contended from
    opposite directions, must serialize rather than each reading a stale
    snapshot of the other, and the retype, left genuinely waiting, must
    resume and be rejected once the reparent commits, leaving the area
    parented under a location that is still genuinely dungeon-typed."""
    engine = postgres_engine
    slug = f"subtype-lock-reparent-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            world = make_world(setup, slug=slug)
            old_dungeon = make_dungeon(setup, world, name="Old Dungeon")
            new_dungeon = make_dungeon(setup, world, name="New Dungeon")
            area = make_dungeon_area(setup, old_dungeon)
            region_type = lookup_id(setup, "core", "entity_types", "entity_type_id", "region")

        with engine.connect() as first:
            first.begin()

            # Transaction 1: reparent the area under new_dungeon. Still
            # uncommitted.
            first.execute(
                text("UPDATE world.locations SET parent_location_id = :d WHERE location_id = :a"),
                {"d": new_dungeon, "a": area},
            )

            with _BackgroundStatement(
                engine,
                "UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e",
                {"t": region_type, "e": new_dungeon},
            ) as blocked:
                blocked.wait_until_blocked(first, "the concurrent retype away from 'dungeon'")
                first.commit()
                result, exc = blocked.resume_and_get_outcome("the concurrent retype")

        assert result == "failed", f"expected the resumed retype to be rejected, got: {result}"
        assert "still has" in str(exc) and "dungeon area" in str(exc)

        with engine.connect() as verify:
            new_dungeon_type = verify.execute(
                text(
                    "SELECT et.code FROM core.entities e "
                    "JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id "
                    "WHERE e.entity_id = :e"
                ),
                {"e": new_dungeon},
            ).scalar()
            area_parent = verify.execute(
                text("SELECT parent_location_id FROM world.locations WHERE location_id = :a"),
                {"a": area},
            ).scalar()
        assert new_dungeon_type == "dungeon", "the rejected retype must not have taken effect"
        assert area_parent == new_dungeon, (
            "the committed reparent must have taken effect, and the area's parent must still be "
            "genuinely dungeon-typed"
        )
    finally:
        _cleanup_world(engine, slug)


# ---------------------------------------------------------------------------
# Concurrency safety of the child-location lock (revision 056)
# ---------------------------------------------------------------------------
# The race PHASE5_REMAINING_ISSUES.md's schema blocker named: inserting
# world.dungeon_areas for child location L versus directly changing that
# same L's parent_location_id. Revision 053's locking did not cover this
# path at all — the insert locked only the proposed parent, and the
# location-update side never acquired any shared lock before its early
# return. Both possible starting orders are covered, since the review noted
# the race exists either way.


def test_a_concurrent_dungeon_area_insert_and_child_parent_clear_is_serialized(
    postgres_engine: Engine,
) -> None:
    """Insert starts first: transaction 1 inserts the dungeon_area row for L
    (validating L's current parent while transaction 2 waits), then commits.
    Transaction 2's clear must resume and be rejected — L is now a
    committed dungeon area and its parent may not be cleared, so it must
    never end up without a valid dungeon parent."""
    engine = postgres_engine
    slug = f"child-lock-insert-first-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            world = make_world(setup, slug=slug)
            dungeon = make_dungeon(setup, world)
            area = make_location(
                setup, world, parent_location_id=dungeon, entity_type_code="dungeon_area"
            )

        with engine.connect() as first:
            first.begin()

            # Transaction 1: insert the pending dungeon_area row. Still
            # uncommitted.
            first.execute(
                text("INSERT INTO world.dungeon_areas (dungeon_area_id) VALUES (:a)"), {"a": area}
            )

            with _BackgroundStatement(
                engine,
                "UPDATE world.locations SET parent_location_id = NULL WHERE location_id = :a",
                {"a": area},
            ) as blocked:
                blocked.wait_until_blocked(first, "the concurrent parent-clearing update")
                first.commit()
                result, exc = blocked.resume_and_get_outcome(
                    "the concurrent parent-clearing update"
                )

        assert result == "failed", f"expected the resumed update to be rejected, got: {result}"
        assert "cannot be cleared" in str(exc)

        with engine.connect() as verify:
            has_area_row = verify.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM world.dungeon_areas WHERE dungeon_area_id = :a)"
                ),
                {"a": area},
            ).scalar()
            area_parent = verify.execute(
                text("SELECT parent_location_id FROM world.locations WHERE location_id = :a"),
                {"a": area},
            ).scalar()
        assert has_area_row is True, "the committed dungeon_area insert must have taken effect"
        assert area_parent == dungeon, (
            "the rejected parent-clearing update must not have taken effect — a dungeon area "
            "must never end up without a valid dungeon parent"
        )
    finally:
        _cleanup_world(engine, slug)


def test_a_concurrent_child_parent_clear_and_dungeon_area_insert_is_serialized(
    postgres_engine: Engine,
) -> None:
    """Reverse order: transaction 1 clears L's parent_location_id first
    (L is not yet a dungeon area, so this passes and stays open), then
    commits. Transaction 2's pending dungeon_area insert must resume and be
    rejected — L's parent is now NULL, not a dungeon, so no dungeon-area row
    may end up depending on it."""
    engine = postgres_engine
    slug = f"child-lock-update-first-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            world = make_world(setup, slug=slug)
            dungeon = make_dungeon(setup, world)
            area = make_location(
                setup, world, parent_location_id=dungeon, entity_type_code="dungeon_area"
            )

        with engine.connect() as first:
            first.begin()

            # Transaction 1: clear the parent before `area` has a
            # world.dungeon_areas row at all, so this is currently valid and
            # passes immediately. Held open (uncommitted) rather than
            # committed right away, so the advisory lock it took stays held
            # while transaction 2 attempts the insert below.
            first.execute(
                text("UPDATE world.locations SET parent_location_id = NULL WHERE location_id = :a"),
                {"a": area},
            )

            with _BackgroundStatement(
                engine,
                "INSERT INTO world.dungeon_areas (dungeon_area_id) VALUES (:a)",
                {"a": area},
            ) as blocked:
                blocked.wait_until_blocked(first, "the concurrent dungeon_area insert")
                first.commit()
                result, exc = blocked.resume_and_get_outcome("the concurrent dungeon_area insert")

        assert result == "failed", f"expected the resumed insert to be rejected, got: {result}"
        assert "no parent_location_id" in str(exc)

        with engine.connect() as verify:
            has_area_row = verify.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM world.dungeon_areas WHERE dungeon_area_id = :a)"
                ),
                {"a": area},
            ).scalar()
            area_parent = verify.execute(
                text("SELECT parent_location_id FROM world.locations WHERE location_id = :a"),
                {"a": area},
            ).scalar()
        assert area_parent is None, "the committed parent-clearing update must have taken effect"
        assert has_area_row is False, (
            "the rejected dungeon_area insert must not have taken effect — no dungeon-area row "
            "may exist without a valid dungeon parent"
        )
    finally:
        _cleanup_world(engine, slug)
