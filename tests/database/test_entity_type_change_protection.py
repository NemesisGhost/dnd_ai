"""Parent-side entity-type-change protection (revision 048).

core.enforce_entity_subtype() (revision 004) validates from the subtype
side: an INSERT or UPDATE on e.g. world.dungeons checks the owning entity's
type. These tests cover the reverse direction — UPDATE core.entities SET
entity_type_id — which revision 048 closes with two triggers: a generic one
driven by core.entity_types metadata, and a dungeon-specific one for the
"child areas stranded even after the marker row is deleted" case the generic
trigger alone cannot see.
"""

import contextlib
import multiprocessing
import sys
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any, Protocol

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


def _attempt(problems: list[tuple[str, Exception]], label: str, fn: Callable[[], None]) -> bool:
    """Runs fn(), appending (label, exc) to problems and returning False on
    failure rather than silently discarding it or letting the exception
    propagate and replace whatever exception a caller further up the
    stack (startup, statement, or outcome) may already be reporting.
    Every caller attempts every required cleanup step regardless of
    whether an earlier one failed, and every failure that happens along
    the way is collected for reporting — never suppressed. The boolean
    return lets a caller that needs to know whether a specific step
    actually *succeeded* — not merely "was attempted" — make that
    distinction (Phase 5 fourteenth exit review: evidence-based
    forced-termination classification needs exactly this)."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - collected, not swallowed
        problems.append((label, exc))
        return False
    return True


def _safe_read(
    problems: list[tuple[str, Exception]], label: str, fn: Callable[[], Any]
) -> tuple[Any, bool]:
    """Runs a zero-argument read-only accessor (a status/identity check
    such as `.pid`, `.is_alive()`, or `.exitcode`), collecting any
    failure into problems and returning `(None, False)` instead of
    letting it propagate — the same failure-safety `_attempt` gives
    actions, for reads. The `ok` flag lets a caller distinguish a
    genuinely observed falsy/None value from a failed read that merely
    looks like one: an unknown state must never be silently treated as a
    confirmed one (Phase 5 fourteenth exit review §§1-2 — this is what
    keeps "could not determine" from being misread as "never started" or
    "already gone")."""
    try:
        return fn(), True
    except Exception as exc:  # noqa: BLE001 - collected, not swallowed
        problems.append((label, exc))
        return None, False


def _process_liveness(
    problems: list[tuple[str, Exception]], label: str, process: Any
) -> bool | None:
    """Guards `process.is_alive()`, returning True/False when confirmed or
    None when it could not be determined. None must never be treated as
    "not alive" by a caller — every caller here either escalates
    (attempts a stronger containment step) or reports an indeterminate
    outcome rather than silently assuming the process is gone."""
    alive, ok = _safe_read(problems, label, process.is_alive)
    return alive if ok else None


def _exitcode_confirms_forced_termination(
    problems: list[tuple[str, Exception]], label: str, process: Any
) -> bool:
    """Best-effort positive evidence that a signal *this controller sent*
    — not a coincidentally-overlapping natural exit — is what ended the
    process. `multiprocessing.Process.exitcode` is negative (-N) when the
    child was ended by signal N; confirmed empirically on this platform
    that both `terminate()` and `kill()` produce a negative exitcode
    (Phase 5 fourteenth exit review §1). A natural/graceful exit reports
    0. Returns False (not confirmed) rather than raising if `exitcode`
    itself cannot be read — absence of evidence is never treated as
    evidence of forced termination."""
    code, ok = _safe_read(problems, label, lambda: process.exitcode)
    return ok and code is not None and code < 0


def _poll_and_recv(conn: Any, timeout: float) -> tuple[bool, Any]:
    """Bounded wait for one message on a multiprocessing.Connection (a
    `Pipe()` end). Returns `(True, payload)` if a message arrived within
    `timeout`, or `(False, None)` if the wait timed out or the peer closed
    its end without ever sending one — both are "nothing arrived" from the
    caller's point of view, and every caller here (the startup handshake,
    and the outcome channel) already treats those two cases identically.

    A closed peer surfaces differently by platform: POSIX reports the pipe
    as readable and lets `recv()` raise `EOFError`, while Windows'
    `PipeConnection.poll()` itself raises `BrokenPipeError` (a subclass of
    `OSError`) as soon as the peer has closed — reproduced running this
    suite locally. Both are the same "peer closed, nothing sent" case, not
    a real failure, so both `poll()` and `recv()` are guarded here rather
    than only `recv()`.

    Unlike the multiprocessing.Queue-based design this replaced (Phase 5
    twelfth exit review §4), `Connection.poll()`/`.recv()`/`.close()` are
    direct, synchronous operations on an OS-level pipe handle — none of
    them spin up a background feeder thread, so there is nothing here that
    can itself need a bounded join or ever survive as an orphaned thread
    the way `Queue.join_thread()` could."""
    try:
        if not conn.poll(timeout=timeout):
            return False, None
    except (EOFError, OSError):
        return False, None
    try:
        return True, conn.recv()
    except (EOFError, OSError):
        return False, None


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
    watcher_join_timeout_seconds: float,
    fault_injection_stage: str | None,
    handshake_send: Any,
    outcome_send: Any,
    control_recv: Any,
) -> None:
    """Entry point for _BackgroundStatement's worker process. Defined at
    module level (not a closure or method) because multiprocessing's
    "spawn" start method must be able to pickle a reference to it.
    `handshake_send`/`outcome_send`/`control_recv` are this worker's own
    ends of three one-way `multiprocessing.Pipe(duplex=False)` channels —
    see the class docstring for why these replaced `multiprocessing.Queue`.

    Three phases: (1) acquire a connection, begin its transaction, set the
    deterministic lock_timeout backstop, and report the real backend pid
    back through handshake_send — or, on any failure, attempt every cleanup
    step for whatever was partially acquired and report the primary failure
    plus any cleanup problems instead of it; (2) run the given statement,
    watching control_recv on a background thread for a driver-native
    cancel_safe() request from the controller — that thread's own stop
    signal is a purely local threading.Event, never IPC: only the
    controller's cancel requests need to cross the process boundary, and
    this worker's own main thread telling its own watcher thread to stop
    never did; (3) attempt commit() only if the statement succeeded,
    attempt rollback() only if commit() then fails, then attempt every
    remaining cleanup step — signaling the watcher, joining it, closing the
    connection, disposing the engine — independently of whether an earlier
    one failed, so one failure never skips the rest, and report through
    outcome_send as `(status, primary_error, problems)` — `status` is
    `"committed"` only when the statement, its commit, and every cleanup
    step all succeeded with nothing left to report; a cleanup-only problem
    after an otherwise successful commit still reports `"failed"`, and a
    watcher thread still alive after its own bounded join is itself
    recorded as a cleanup problem.

    Publishing that outcome is this worker's one mandatory duty — see the
    class docstring and `_BackgroundStatement._finalize_worker_outcome`
    for how the controller enforces that. Nothing here can single-handedly
    guarantee the publish itself succeeds, since if the one channel for
    reporting a failure is what failed, there is no second channel left to
    report that failure through.

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
    except Exception as exc:  # noqa: BLE001 - reported via handshake_send, not swallowed
        if connection is not None:
            _attempt(problems, "rollback after startup failure", connection.rollback)
            _attempt(problems, "close after startup failure", connection.close)
        if engine is not None:
            _attempt(problems, "dispose after startup failure", engine.dispose)
        # The handshake channel itself is what might fail here; nothing
        # further can be attempted through it. The controller's bounded
        # handshake wait times out instead of hanging.
        with contextlib.suppress(Exception):
            handshake_send.send(("failed", repr(exc), problems))
        return

    try:
        handshake_send.send(("ready", pid, []))
    except Exception:  # noqa: BLE001 - see above: the controller's handshake wait times out.
        return

    stop_watcher = threading.Event()

    def _watch_for_cancel() -> None:
        while fault_injection_stage == "watcher_ignores_stop_signal" or not stop_watcher.is_set():
            received, message = _poll_and_recv(control_recv, 0.5)
            if not received:
                continue
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

    def _stop_watcher_with_optional_injection() -> None:
        if fault_injection_stage == "watcher_stop_signal_fails":
            raise _InjectedFailure("injected failure at stage: watcher_stop_signal_fails")
        stop_watcher.set()

    statement_error: Exception | None = None
    commit_error: Exception | None = None
    try:
        connection.execute(text(sql), params)
    except Exception as exc:  # noqa: BLE001 - reported via outcome_send, not swallowed
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
        except Exception as exc:  # noqa: BLE001 - reported via outcome_send, not swallowed
            commit_error = exc
            _attempt(problems, "rollback after commit failure", connection.rollback)
    finally:
        # Every step below is attempted independently of whether an
        # earlier one failed (Phase 5 twelfth exit review §3): a failure
        # signaling the watcher to stop must not skip joining it, closing
        # the connection, or disposing the engine — none of those depend
        # on any other having succeeded.
        _attempt(problems, "signal watcher to stop", _stop_watcher_with_optional_injection)
        watcher.join(timeout=watcher_join_timeout_seconds)
        if watcher.is_alive():
            problems.append(
                (
                    "watcher thread",
                    RuntimeError(
                        "cancel-watcher thread did not stop within its "
                        f"{watcher_join_timeout_seconds}s bounded join"
                    ),
                )
            )
        _attempt(problems, "close", _close_with_optional_injection)
        _attempt(problems, "dispose", _dispose_with_optional_injection)

    # "committed" is reported only once the statement genuinely executed,
    # its commit genuinely succeeded, and no other cleanup step (rollback,
    # invalidate, close, dispose, signaling/joining the watcher) reported a
    # problem either - a cleanup-only failure after a real commit must
    # still surface as a failure, not be silently absorbed into an
    # apparently-successful outcome.
    primary_error = (
        repr(statement_error)
        if statement_error is not None
        else (repr(commit_error) if commit_error is not None else None)
    )
    status = "failed" if primary_error is not None or problems else "committed"
    outcome_payload = (status, primary_error, problems)
    try:
        if fault_injection_stage == "outcome_publish_fails":
            raise _InjectedFailure("injected failure at stage: outcome_publish_fails")
        outcome_send.send(outcome_payload)
        if fault_injection_stage == "duplicate_outcome_publish":
            outcome_send.send(outcome_payload)
    except Exception:  # noqa: BLE001 - the one channel for reporting this outcome is exactly
        # what just failed; nothing further can be attempted here. The
        # controller detects the missing outcome and reports its own
        # protocol failure instead (see
        # _BackgroundStatement._finalize_worker_outcome).
        return


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
    noticed — checked through a fresh connection on every path, not assumed
    from the process alone and not only when the process happened to still
    be alive when the `with` block exited (Phase 5 thirteenth exit review
    §2): a worker that already exited on its own is verified in `__exit__`
    directly; a worker still alive is verified as the last step of
    `_force_stop` below. Exactly one of those two runs per `__exit__` call,
    never both. If the process is still alive when the `with` block exits,
    `__exit__` attempts, in order: `pg_terminate_backend()`, then
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
    can keep running until it next tries to communicate. `_force_stop`
    reports which of these actually ended the process — graceful,
    positively-confirmed-forced, survived, or indeterminate (see its own
    docstring) — since only the positively-confirmed-forced case
    legitimately excuses a missing worker outcome below. Two earlier
    versions of this class got that classification wrong in different
    ways: treating "was alive when `__exit__` began" as proof of forced
    termination regardless of how containment was actually achieved
    (Phase 5 thirteenth exit review §1), and then treating "no longer
    alive after an attempted `terminate()`/`kill()`" as proof that
    attempt succeeded, which a failed or no-op forcible call racing a
    coincidental natural exit could satisfy identically (Phase 5
    fourteenth exit review §1) — both let graceful cancellation followed
    by a failed outcome publish report false success.

    Every step's outcome is collected, never silently discarded. The
    worker's own statement, commit, rollback, invalidation, close, and
    engine-disposal failures are all represented in a structured outcome
    (see `_worker_main`); a statement that succeeds but whose commit then
    fails is reported as a failure, never as committed, and a cleanup-only
    problem after an otherwise-successful commit still fails the caller
    rather than being silently absorbed. Publishing that outcome is the
    worker's one mandatory duty, and this class treats it as total, not
    best-effort: a worker that exits on its own without ever publishing one
    is reported as a protocol failure, not silently treated as success, and
    a worker that somehow publishes more than one is reported the same way;
    the one legitimate "no outcome" case is a worker this controller itself
    *forcibly terminated* before it could publish anything — not merely a
    worker that happened to still be alive at some point — which is
    recorded as such rather than conflated with either failure mode (see
    `_finalize_worker_outcome`). Whatever the caller does not explicitly
    consume via `resume_and_get_outcome` is still drained and processed by
    `__exit__`, so an outcome nobody read is never lost. If an exception was
    already propagating out of the `with` block, every cleanup problem is
    attached to it via `add_note`; if nothing was already propagating,
    cleanup problems are raised directly and become the `with` block's own
    failure. A `with` block backed by this class therefore never returns
    or raises with an owned worker, IPC channel, or process object still
    alive/open — the guarantee no earlier thread-based design in this
    file's history could make.

    IPC between controller and worker is three one-way
    `multiprocessing.Pipe(duplex=False)` channels (handshake, outcome, and
    a controller-to-worker control channel for cancel requests), not
    `multiprocessing.Queue`. A prior version of this class used Queue and
    bounded its background feeder-thread cleanup with a wrapping daemon
    thread of its own; a review reproduced that wrapping thread itself
    surviving past its bound, an abandonable resource created specifically
    to solve an abandonable-resource problem. `Connection.close()` is a
    direct, synchronous close of an OS-level pipe handle with no feeder
    thread at all, which removes that whole class of bug by construction
    rather than bounding it (Phase 5 twelfth exit review §4).
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
        _watcher_join_timeout_seconds: float = 5.0,
    ) -> None:
        self._engine = engine
        self._sql = sql
        self._params: dict[str, Any] = dict(params or {})
        self._lock_timeout_seconds = lock_timeout_seconds
        self._signal_join_seconds = signal_join_seconds
        self._handshake_timeout_seconds = handshake_timeout_seconds
        self._startup_delay_seconds = _startup_delay_seconds
        self._fault_injection_stage = _fault_injection_stage
        self._watcher_join_timeout_seconds = _watcher_join_timeout_seconds
        self.outcome: list[tuple[str, Exception | None]] = []
        self._backend_pid_value: int | None = None
        self._process: Any = None
        self._handshake_recv: Any = None
        self._handshake_send: Any = None
        self._outcome_recv: Any = None
        self._outcome_send: Any = None
        self._control_recv: Any = None
        self._control_send: Any = None
        self._worker_confirmed_stopped = False
        self._outcome_consumed = False
        self.outcome_protocol_state = "pending"
        # Failures closing the controller's own redundant copies of the
        # ends handed off to the worker (see __enter__) are owned by this
        # instance rather than __enter__ itself: a redundant-copy close
        # failure does not mean the worker is broken, so __enter__ does
        # not fail over it when the handshake otherwise succeeds — but it
        # must still be reported somewhere, not silently dropped (Phase 5
        # thirteenth exit review §4). __exit__ folds these into its own
        # problems unconditionally.
        self._startup_cleanup_problems: list[tuple[str, Exception]] = []

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
        `_close_ipc_channels` and the `close process object` step),
        calling `is_alive()` on it raises `ValueError: process object is
        closed` instead of meaningfully answering the question."""
        return self._worker_confirmed_stopped

    def __enter__(self) -> "_BackgroundStatement":
        ctx = multiprocessing.get_context("spawn")

        try:
            # Stored immediately, one Pipe() call at a time, not only on
            # full success: __exit__ is never called if __enter__ raises,
            # so the except block below is responsible for closing
            # whichever of these three pipes actually got created before
            # a later one failed — a Pipe() call itself either returns
            # both of its own ends or raises, so there is never a "half a
            # pipe" to worry about, only "some earlier pipes already exist
            # and this one does not."
            self._handshake_recv, self._handshake_send = ctx.Pipe(duplex=False)
            self._outcome_recv, self._outcome_send = ctx.Pipe(duplex=False)
            self._control_recv, self._control_send = ctx.Pipe(duplex=False)
        except Exception as exc:  # noqa: BLE001 - reported directly, not swallowed
            construction_problems: list[tuple[str, Exception]] = []
            self._close_ipc_channels(construction_problems)
            construction_error = RuntimeError(
                f"failed to construct the background worker's IPC channels: {exc}"
            )
            for label, cleanup_exc in construction_problems:
                construction_error.add_note(
                    f"cleanup also reported a problem ({label}): {cleanup_exc}"
                )
            raise construction_error from exc

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
                    self._watcher_join_timeout_seconds,
                    self._fault_injection_stage,
                    self._handshake_send,
                    self._outcome_send,
                    self._control_recv,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - reported directly, not swallowed
            construction_problems = []
            self._close_ipc_channels(construction_problems)
            construction_error = RuntimeError(
                f"failed to construct the background worker process: {exc}"
            )
            for label, cleanup_exc in construction_problems:
                construction_error.add_note(
                    f"cleanup also reported a problem ({label}): {cleanup_exc}"
                )
            raise construction_error from exc

        # Ownership begins at construction, not only once start() has
        # confirmed success (Phase 5 thirteenth exit review §3): a
        # Process object whose start() raises is not always a no-op that
        # never touched the OS — start() can fail after partially (or
        # fully) launching the child, and this instance must own whatever
        # __enter__'s except block below discovers, rather than treating
        # every start() failure as automatically nothing-to-clean-up.
        self._process = process

        try:
            process.start()
        except Exception as exc:  # noqa: BLE001 - reported directly, not swallowed
            start_problems: list[tuple[str, Exception]] = []
            self._cleanup_process_after_start_failure(process, start_problems)
            self._close_ipc_channels(start_problems)
            start_error = RuntimeError(f"background worker process failed to start: {exc}")
            for label, cleanup_exc in start_problems:
                start_error.add_note(f"cleanup also reported a problem ({label}): {cleanup_exc}")
            raise start_error from exc

        # The worker process now has its own duplicated copies of
        # handshake_send/outcome_send/control_recv; this side no longer
        # needs its own. Closing them here (rather than waiting for final
        # cleanup) also means a worker that crashes without ever sending
        # anything produces a genuine EOF on the read ends below instead
        # of poll() only ever timing out. Connection.close() is idempotent
        # (a no-op the second time), so closing these same three again in
        # final cleanup later is always safe. A close failure here does
        # not by itself mean the worker is broken (these are redundant
        # copies the worker never uses), so it does not fail __enter__
        # over it — but it must not be silently dropped either (Phase 5
        # thirteenth exit review §4): it is owned by this instance and
        # __exit__ reports it, chosen over failing/reaping the worker
        # solely because a copy the worker itself never touches failed to
        # close on this side.
        _attempt(
            self._startup_cleanup_problems,
            "close handshake_send (controller copy)",
            self._handshake_send.close,
        )
        _attempt(
            self._startup_cleanup_problems,
            "close outcome_send (controller copy)",
            self._outcome_send.close,
        )
        _attempt(
            self._startup_cleanup_problems,
            "close control_recv (controller copy)",
            self._control_recv.close,
        )

        received, handshake_message = _poll_and_recv(
            self._handshake_recv, self._handshake_timeout_seconds
        )
        if not received:
            self._reap(self._startup_cleanup_problems)
            error = TimeoutError(
                f"background worker did not complete its startup handshake within "
                f"{self._handshake_timeout_seconds}s (timed out, or its handshake "
                "channel closed without sending one)"
            )
            for label, exc in self._startup_cleanup_problems:
                error.add_note(f"startup cleanup also reported a problem ({label}): {exc}")
            raise error from None

        status, payload, handshake_problems = handshake_message

        if status == "failed":
            self._reap(self._startup_cleanup_problems)
            error = RuntimeError(f"background worker failed to start: {payload}")
            for label, exc in [*handshake_problems, *self._startup_cleanup_problems]:
                error.add_note(f"startup cleanup also reported a problem ({label}): {exc}")
            raise error

        self._backend_pid_value = payload
        return self

    def _cleanup_process_after_start_failure(
        self, process: Any, problems: list[tuple[str, Exception]]
    ) -> None:
        """`process.start()` raised. Classifies whether that left a
        genuinely live child behind before deciding how to clean up
        (Phase 5 thirteenth exit review §3), and does so — and every
        subsequent containment step — through fully guarded reads and
        actions, never letting a cleanup exception escape and replace the
        original `start()` failure this method exists to clean up after
        (Phase 5 fourteenth exit review §2: an unguarded `join()`/
        `is_alive()` here previously did exactly that, and also skipped
        the IPC-channel cleanup `__enter__`'s except block runs
        immediately afterward).

        `pid` and `is_alive()` are both safe to call regardless of
        whether the process ever started (returning `None`/`False`
        rather than raising, confirmed empirically) — but a failure
        reading either is collected into `problems`, not silently
        reinterpreted as "never started": only a *positively confirmed*
        `pid is None and not alive` (both reads succeeded) takes the
        never-started shortcut. Anything else — a genuine partial start,
        or simply an unreadable status — falls through to the same
        terminate → join → status → kill → join → status → close fallback
        `_force_stop` uses, on the same reasoning: an unknown state must
        never be treated as proof no process exists. `worker_confirmed_stopped`
        is set only once the absence of a live child has actually been
        established, never merely assumed."""
        pid, pid_ok = _safe_read(problems, "pid inspection (partial start)", lambda: process.pid)
        alive = _process_liveness(problems, "initial status check (partial start)", process)

        if pid_ok and pid is None and alive is False:
            # Positively confirmed never-started: terminate()/kill()/join()
            # are invalid operations on a never-started Process (they
            # raise), so this shortcut avoids attempting them at all.
            self._worker_confirmed_stopped = True
            _attempt(problems, "close process object (partial start)", process.close)
            return

        _attempt(problems, "terminate (partial start)", process.terminate)
        _attempt(
            problems,
            "post-terminate join (partial start)",
            lambda: process.join(timeout=self._signal_join_seconds),
        )
        alive = _process_liveness(problems, "post-terminate status check (partial start)", process)

        if alive is not False:
            _attempt(problems, "kill (partial start)", process.kill)
            _attempt(
                problems,
                "post-kill join (partial start)",
                lambda: process.join(timeout=self._signal_join_seconds),
            )
            alive = _process_liveness(problems, "final status check (partial start)", process)

        if alive is False:
            self._worker_confirmed_stopped = True
            _attempt(problems, "close process object (partial start)", process.close)
        elif alive is True:
            problems.append(
                (
                    "reap (partial start)",
                    RuntimeError(
                        "process survived forcible termination after a partial start failure"
                    ),
                )
            )
        else:
            problems.append(
                (
                    "reap (partial start)",
                    RuntimeError(
                        "process liveness could not be confirmed after a partial start failure"
                    ),
                )
            )

    def _reap(self, problems: list[tuple[str, Exception]]) -> None:
        """Unconditionally terminates and joins a worker process that must
        not be left running, then closes every IPC channel and the process
        object itself. Used on every __enter__ failure path: __exit__ is
        never invoked when __enter__ raises, so this method alone is
        responsible for leaving no process, IPC, or process-object
        resource behind on that path — every step below is guarded
        (Phase 5 fourteenth exit review §2) so a cleanup failure here can
        never itself propagate and replace the startup/handshake error
        `__enter__` is in the middle of raising."""
        assert self._process is not None
        _attempt(problems, "terminate", self._process.terminate)
        _attempt(problems, "join", lambda: self._process.join(timeout=self._signal_join_seconds))
        alive = _process_liveness(problems, "status check", self._process)
        if alive is not False:
            _attempt(problems, "kill", self._process.kill)
            _attempt(
                problems,
                "join after kill",
                lambda: self._process.join(timeout=self._signal_join_seconds),
            )
            alive = _process_liveness(problems, "status check after kill", self._process)
        if alive is False:
            self._worker_confirmed_stopped = True
            _attempt(problems, "close process object", self._process.close)
        elif alive is True:
            problems.append(("reap", RuntimeError("process survived forcible termination")))
        else:
            problems.append(
                ("reap", RuntimeError("process liveness could not be confirmed after reaping"))
            )
        self._close_ipc_channels(problems)

    def _close_ipc_channels(self, problems: list[tuple[str, Exception]]) -> None:
        """Closes every IPC connection this instance holds — both the ends
        it reads/writes through itself and its own (post-start(), already
        redundant but harmless — see __enter__) copies of the ends handed
        to the worker process — attempted independently and failure-safely
        per connection regardless of whether an earlier one's close
        failed. Unlike the multiprocessing.Queue-based design this
        replaced, Connection.close() is a direct, synchronous close of an
        OS-level pipe handle: no background feeder thread is ever
        created, so there is nothing here that can itself need a bounded
        join or survive as an orphaned thread."""
        for label, conn in (
            ("handshake_recv", self._handshake_recv),
            ("handshake_send", self._handshake_send),
            ("outcome_recv", self._outcome_recv),
            ("outcome_send", self._outcome_send),
            ("control_recv", self._control_recv),
            ("control_send", self._control_send),
        ):
            if conn is None:
                continue
            _attempt(problems, f"close {label}", conn.close)

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
        assert self._process is not None and self._outcome_recv is not None
        outcome = self._drain_one_outcome(timeout=10.0)
        if outcome is None:
            raise AssertionError(f"{label} thread reported no outcome within 10s")
        self._outcome_consumed = True
        status, primary_error, problems = outcome
        self._process.join(timeout=5.0)
        assert not self._process.is_alive(), (
            f"{label} did not resume within the bounded window after the blocking "
            "transaction's commit"
        )
        exc = self._build_outcome_exception(status, primary_error, problems)
        self.outcome.append((status, exc))
        return status, exc

    def _drain_one_outcome(
        self, timeout: float
    ) -> tuple[str, str | None, list[tuple[str, Exception]]] | None:
        """One bounded read of the outcome channel. Returns the raw
        `(status, primary_error, problems)` payload, or None if nothing
        arrived within `timeout` — used both to consume the worker's one
        expected outcome and, in `_finalize_worker_outcome`, to check for
        an unconsumed or an unexpected extra one."""
        if self._outcome_recv is None:
            return None
        received, payload = _poll_and_recv(self._outcome_recv, timeout)
        return payload if received else None

    def _finalize_worker_outcome(
        self, problems: list[tuple[str, Exception]], *, worker_was_forcibly_stopped: bool
    ) -> None:
        """Ensures the worker's one required outcome is accounted for
        exactly once (Phase 5 twelfth exit review §2), regardless of
        whether `resume_and_get_outcome` already consumed it. Three
        outcomes are distinguished, recorded on `self.outcome_protocol_state`,
        and none are silently treated as success:

        - Nothing arrives and the worker was never forcibly stopped: the
          worker exited on its own without publishing a required outcome
          — a protocol failure, appended to `problems` like any other.
        - More than one outcome arrives — whether the second is found here
          because nobody consumed the first, or because a second turns up
          after `resume_and_get_outcome` already consumed one — also a
          protocol failure: this worker's own cleanup contract guarantees
          at most one.
        - Nothing arrives and the worker *was* forcibly stopped: the one
          legitimate "no outcome" case (the controller ended it before it
          could publish anything), recorded as such rather than treated as
          either a protocol failure or silently ignored.

        A first outcome found here that nobody consumed is reported
        exactly as resume_and_get_outcome would have reported it (via
        `_build_outcome_exception`), so a statement/commit/cleanup failure
        nobody explicitly asked for is never silently discarded."""
        if self._outcome_consumed:
            # Already handed to the caller via resume_and_get_outcome; the
            # process is confirmed not alive by that point, so anything
            # still waiting here would already be fully flushed — only
            # checking for an unexpected extra, not waiting for a normal
            # one that will never come.
            extra = self._drain_one_outcome(timeout=0.3)
            if extra is not None:
                problems.append(
                    (
                        "worker outcome protocol",
                        RuntimeError(
                            f"worker published more than one outcome; unexpected extra: {extra}"
                        ),
                    )
                )
            self.outcome_protocol_state = "consumed"
            return

        first = self._drain_one_outcome(timeout=2.0)
        if first is None:
            if worker_was_forcibly_stopped:
                self.outcome_protocol_state = "missing-after-forced-termination"
                return
            self.outcome_protocol_state = "missing-after-natural-exit"
            problems.append(
                (
                    "worker outcome protocol",
                    RuntimeError(
                        "worker process exited on its own without publishing a required outcome"
                    ),
                )
            )
            return

        status, primary_error, cleanup_problems = first
        exc = self._build_outcome_exception(status, primary_error, cleanup_problems)
        if exc is not None:
            problems.append(("unread worker outcome", exc))
        self.outcome_protocol_state = "unread"

        second = self._drain_one_outcome(timeout=0.3)
        if second is not None:
            problems.append(
                (
                    "worker outcome protocol",
                    RuntimeError(
                        f"worker published more than one outcome; unexpected extra: {second}"
                    ),
                )
            )

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
        channel to a watcher thread running inside that process — the
        controller never holds a live connection object to the worker's
        database session, since that connection exists entirely inside the
        worker process."""
        assert self._control_send is not None
        self._control_send.send("cancel")

    def _force_stop(self) -> tuple[list[tuple[str, Exception]], str]:
        """Layered attempt to make the worker process stop — see the class
        docstring for the full fallback chain. Every layer is followed by a
        bounded, guarded join verifying the process actually exited, not
        just that a signal was sent or accepted; every status/liveness
        read in this method is similarly guarded (Phase 5 fourteenth exit
        review §1-audit) so a cleanup-side failure can never itself
        propagate and replace an exception already active higher up the
        stack. The final layer (forcible OS-level termination) is
        unconditionally guaranteed to succeed, so this method never
        returns while the process is still alive.

        Returns `(problems, containment_reason)`. `containment_reason` is
        one of:

        - `"graceful"`: a PostgreSQL/driver-level mechanism (an SQL
          signal, driver-native cancellation, or the `lock_timeout`
          backstop) ended the process on its own, without this method
          ever needing to attempt `terminate()`/`kill()`.
        - `"forced"`: this method's own `terminate()`/`kill()` call is
          what actually ended the process, confirmed by *positive
          evidence* — the call itself completed without raising, and the
          process's own `exitcode` afterward indicates it was ended by a
          signal this controller sent (Phase 5 fourteenth exit review
          §1) — not merely that the process was no longer alive after the
          attempt.
        - `"survived"`: even forced termination did not end the process
          — an OS-level guarantee violation everywhere else in this class
          assumes cannot happen.
        - `"indeterminate"`: the process was no longer alive after a
          forcible attempt, but without positive evidence that *this
          controller's own call* — as opposed to a coincidentally
          overlapping natural/graceful exit racing the same join window,
          or a call that itself raised — is what ended it; also used
          when liveness itself could not be confirmed even after both
          forcible attempts. Never a legitimate excuse for a missing
          outcome, exactly like `"graceful"` and `"survived"`.

        Distinguishing these matters because only `"forced"` legitimately
        excuses a missing worker outcome (Phase 5 thirteenth exit review
        §1): a worker stopped gracefully — or one whose apparent
        stopping this controller cannot actually attribute to its own
        forcible call — had every opportunity to reach its own
        outcome-publication step (see `_worker_main`) before exiting, so
        a missing outcome afterward is a genuine protocol failure, not an
        artifact of forcible termination cutting the worker off
        mid-flight. Two earlier versions of this class got this wrong in
        different ways: the twelfth pass's version treated the worker
        merely being *alive* when the `with` block exited as proof of
        forced termination regardless of how containment was actually
        achieved; the thirteenth pass's fix still treated the process
        merely being *not alive* after an attempted `terminate()`/
        `kill()` as proof that attempt succeeded, which a failed or
        no-op forcible call followed by a coincidental natural exit
        during the same join window could satisfy just as easily — both
        let graceful cancellation followed by a failed outcome publish
        report false success."""
        assert self._process is not None
        problems: list[tuple[str, Exception]] = []

        for description, sql in (
            ("pg_terminate_backend", "SELECT pg_terminate_backend(:p)"),
            ("pg_cancel_backend", "SELECT pg_cancel_backend(:p)"),
        ):
            alive = _process_liveness(problems, f"pre-{description} status check", self._process)
            if alive is False:
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
            _attempt(
                problems,
                f"post-{description} join",
                lambda: self._process.join(timeout=self._signal_join_seconds),
            )

        alive = _process_liveness(problems, "pre-cancel_via_driver status check", self._process)
        if alive is not False:
            try:
                self._cancel_via_driver()
            except Exception as exc:  # noqa: BLE001 - collected, not swallowed
                problems.append(("cancel_via_driver", exc))
            _attempt(
                problems,
                "post-cancel_via_driver join",
                lambda: self._process.join(timeout=self._signal_join_seconds),
            )

        alive = _process_liveness(problems, "pre-lock_timeout-backstop status check", self._process)
        if alive is not False:
            # Deterministic backstop: the worker's own transaction was
            # configured with a bounded lock_timeout during __enter__,
            # before it could block on anything, so PostgreSQL itself
            # guarantees a lock-waiting statement cannot wait longer than
            # that — independent of every mechanism above. This cannot
            # rescue a statement that was never waiting on a lock at all
            # (pg_sleep, used only by the regression tests proving exactly
            # that limitation).
            _attempt(
                problems,
                "lock_timeout backstop join",
                lambda: self._process.join(
                    timeout=self._lock_timeout_seconds + self._signal_join_seconds
                ),
            )
            alive = _process_liveness(
                problems, "post-lock_timeout-backstop status check", self._process
            )
            if alive is not False:
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

        # Everything above is "graceful": a PostgreSQL/driver mechanism
        # that leaves the worker's own outcome-publication step fully
        # reachable. Only forcibly ending the OS process itself, below,
        # can legitimately cut the worker off before it publishes. An
        # unknown status (alive is None) is never treated as "already
        # gone" — it still routes into the forced-termination attempt,
        # the same "unknown must never mean no process" rule §2 applies
        # to `_cleanup_process_after_start_failure`.
        needed_forced_termination = alive is not False
        containment_reason = "graceful"

        if needed_forced_termination:
            containment_reason = self._attempt_forced_termination(problems)
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
        return problems, containment_reason

    def _attempt_forced_termination(self, problems: list[tuple[str, Exception]]) -> str:
        """`terminate()`, escalating to `kill()` if the process is still
        (or unknowably) alive afterward, classified using only positive
        evidence that *this controller's own call* — not a merely
        coincidentally overlapping natural/graceful exit — ended the
        process (Phase 5 fourteenth exit review §1). A step counts as
        confirmed-effective only when both hold: the call itself
        completed without raising, and the process's `exitcode`
        afterward is negative (ended by a signal this controller sent —
        confirmed empirically to hold for both `terminate()` and
        `kill()` on this platform, and true by definition on POSIX).
        Every join/status read is guarded; nothing here can itself raise
        and replace an exception already active higher up the stack."""
        terminate_ok = _attempt(problems, "terminate", self._process.terminate)
        _attempt(
            problems,
            "post-terminate join",
            lambda: self._process.join(timeout=self._signal_join_seconds),
        )
        alive = _process_liveness(problems, "post-terminate status check", self._process)

        if alive is False:
            confirmed = terminate_ok and _exitcode_confirms_forced_termination(
                problems, "post-terminate exitcode check", self._process
            )
            return self._report_forced_termination_result(problems, confirmed=confirmed)

        kill_ok = _attempt(problems, "kill", self._process.kill)
        _attempt(
            problems,
            "post-kill join",
            lambda: self._process.join(timeout=self._signal_join_seconds),
        )
        alive = _process_liveness(problems, "post-kill status check", self._process)

        if alive is False:
            confirmed = (terminate_ok or kill_ok) and _exitcode_confirms_forced_termination(
                problems, "post-kill exitcode check", self._process
            )
            return self._report_forced_termination_result(problems, confirmed=confirmed)

        if alive is True:
            problems.append(
                (
                    "forced termination",
                    RuntimeError(
                        "worker process survived forcible termination — an OS-level "
                        "guarantee was violated"
                    ),
                )
            )
            return "survived"

        problems.append(
            (
                "forced termination",
                RuntimeError(
                    "worker process liveness could not be confirmed after forcible "
                    "termination attempts"
                ),
            )
        )
        return "indeterminate"

    @staticmethod
    def _report_forced_termination_result(
        problems: list[tuple[str, Exception]], *, confirmed: bool
    ) -> str:
        """Shared by both the post-terminate() and post-kill() branches of
        `_attempt_forced_termination`: the process is no longer alive: if
        that is positively attributable to this controller's own call,
        report and return `"forced"`; otherwise report and return
        `"indeterminate"` — never silently treat "not alive" alone as
        proof of which one it was."""
        if confirmed:
            problems.append(
                (
                    "forced termination",
                    RuntimeError(
                        "every graceful mechanism failed; the worker was forcibly terminated"
                    ),
                )
            )
            return "forced"
        problems.append(
            (
                "forced termination",
                RuntimeError(
                    "the worker process was no longer alive after a forcible termination "
                    "attempt, but this controller's own call raised or left no positive "
                    "evidence (a negative exitcode) that it — rather than a coincidentally "
                    "overlapping natural/graceful exit — actually ended it"
                ),
            )
        )
        return "indeterminate"

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
        # Startup-cleanup problems __enter__ chose not to fail/reap over
        # (Phase 5 thirteenth exit review §4) are owned by this instance
        # and reported here, exactly once, on every path — this is the
        # only place they are folded in.
        problems: list[tuple[str, Exception]] = list(self._startup_cleanup_problems)

        worker_was_forcibly_stopped = False
        if self._process is not None:
            # Guarded (Phase 5 fourteenth exit review §1-audit): an
            # unguarded is_alive() raising here would previously escape
            # __exit__ entirely, replacing whatever exception was already
            # propagating out of the `with` block and skipping every
            # cleanup step below it. An unknown status is routed into
            # _force_stop, never treated as "already gone" — the same
            # "unknown must never mean no process" rule used everywhere
            # else in this class.
            alive = _process_liveness(problems, "pre-cleanup status check", self._process)
            if alive is not False:
                force_stop_problems, containment_reason = self._force_stop()
                problems.extend(force_stop_problems)
                # Only a genuine terminate()/kill() by this controller
                # excuses a missing outcome (Phase 5 thirteenth exit
                # review §1) — "graceful", "survived", and
                # "indeterminate" all leave the worker's own
                # outcome-publication step reachable (or, for "survived",
                # already reported as its own distinct problem above), so
                # none of them are treated as the legitimate
                # forced-termination exemption in _finalize_worker_outcome
                # below.
                worker_was_forcibly_stopped = containment_reason == "forced"
            else:
                # The worker already exited on its own by the time
                # __exit__ began — natural completion, not the
                # forced-stop path, which already verifies internally.
                # That alone does not prove PostgreSQL has already
                # noticed the dropped connection (see
                # _verify_backend_gone), so verify it here instead: every
                # successfully entered helper's backend is verified
                # through a fresh connection on every path, exactly once,
                # before __exit__ returns or raises (Phase 5 thirteenth
                # exit review §2) — not inferred merely from the Python
                # process having exited or from an outcome having
                # arrived.
                self._verify_backend_gone(problems)

        # Whether the worker exited on its own or was just forcibly
        # stopped, account for its one required outcome: a statement,
        # commit, or cleanup failure the caller never consumed via
        # resume_and_get_outcome must not be silently discarded just
        # because nobody explicitly asked for it, and a worker that never
        # produced one at all must not be silently treated as success
        # either (see _finalize_worker_outcome).
        self._finalize_worker_outcome(
            problems, worker_was_forcibly_stopped=worker_was_forcibly_stopped
        )

        if self._process is not None:
            alive = _process_liveness(problems, "pre-close status check", self._process)
            if alive is not False:
                problems.append(
                    (
                        "close process object",
                        RuntimeError(
                            "process still alive; refusing to close its object"
                            if alive is True
                            else "process liveness could not be confirmed; refusing to close "
                            "its object"
                        ),
                    )
                )
            else:
                self._worker_confirmed_stopped = True
                _attempt(problems, "close process object", self._process.close)

        self._close_ipc_channels(problems)

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


def _raise_once_then_succeed(
    message: str = "simulated cleanup failure",
) -> Callable[..., None]:
    """Like `_raise_injected_failure`, but raises only the *first* time
    it's called and is a silent no-op afterward — matching the
    idempotent-close semantics real `multiprocessing.Process`/
    `Connection` objects actually have (confirmed empirically: a second
    `close()` on either does not re-raise). Used specifically for
    `close()` seams: `_raise_injected_failure` itself stays as-is for
    seams (`_query_backend_state`, `ctx.Process`/`Process.start`
    construction) that must keep failing on every call for their own
    test to reach its intended state. Without this distinction, the
    independent `_emergency_teardown` safety net's own (deliberately
    redundant) close attempt on the same already-"closed" fake would
    observe a second, spurious failure from a problem the test already
    fully proved and asserted on once (Phase 5 fourteenth exit review
    §3)."""
    state = {"raised": False}

    def _fn(*_args: object, **_kwargs: object) -> None:
        if state["raised"]:
            return
        state["raised"] = True
        raise _InjectedFailure(message)

    return _fn


class _FakeConnection:
    """A minimal stand-in for a multiprocessing.Pipe() end, used only to
    prove __enter__'s partial-IPC-construction cleanup (Phase 5 twelfth
    exit review §4) without needing a real Pipe() call to fail — real ones
    are impractical to construct deterministically, like every other
    OS-level construction failure this file fault-injects instead."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.closed = False

    def close(self) -> None:
        # Raises on the first call, then behaves like the idempotent
        # no-op a real multiprocessing.Connection.close() is on every
        # call after the first (confirmed empirically) — so an
        # independent second close attempt (the _emergency_teardown
        # safety net's own redundant one) does not observe a second,
        # spurious failure from the same already-reported problem
        # (Phase 5 fourteenth exit review §3).
        if self.closed:
            return
        self.closed = True
        raise _InjectedFailure(f"simulated close failure for {self.label}")


class _FakeProcess:
    """A minimal test double for `multiprocessing.Process`, used to drive
    `_attempt_forced_termination` deterministically through combinations
    of `terminate()`/`kill()` outcomes and post-call liveness/`exitcode`
    that a real OS process makes impractical or outright racy to
    construct on demand (Phase 5 fourteenth exit review §1) — the same
    "reproduced deterministically with a fake process" approach the
    review itself used. `alive_sequence` and `exitcode_sequence` are
    consumed one value per call, in order; an `Exception` instance in
    either sequence is raised instead of returned, simulating a status
    read itself failing."""

    def __init__(
        self,
        *,
        alive_sequence: list[bool | Exception],
        exitcode_sequence: list[int | None | Exception] = (),  # type: ignore[assignment]
        terminate_effect: Exception | None = None,
        kill_effect: Exception | None = None,
        join_effect_sequence: list[Exception | None] = (),  # type: ignore[assignment]
        pid: int | None | Exception = None,
        close_effect: Exception | None = None,
    ) -> None:
        self._alive_sequence = list(alive_sequence)
        self._exitcode_sequence = list(exitcode_sequence)
        self._terminate_effect = terminate_effect
        self._kill_effect = kill_effect
        self._join_effect_sequence = list(join_effect_sequence)
        self._pid = pid
        self._close_effect = close_effect
        self.terminate_calls = 0
        self.kill_calls = 0
        self.join_calls = 0
        self.close_calls = 0

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self._terminate_effect is not None:
            raise self._terminate_effect

    def kill(self) -> None:
        self.kill_calls += 1
        if self._kill_effect is not None:
            raise self._kill_effect

    def join(self, timeout: float | None = None) -> None:
        self.join_calls += 1
        if self._join_effect_sequence:
            effect = self._join_effect_sequence.pop(0)
            if effect is not None:
                raise effect

    def is_alive(self) -> bool:
        assert self._alive_sequence, "_FakeProcess.is_alive() called more times than scripted"
        value = self._alive_sequence.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    @property
    def exitcode(self) -> int | None:
        if not self._exitcode_sequence:
            return None
        value = self._exitcode_sequence.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    @property
    def pid(self) -> int | None:
        if isinstance(self._pid, Exception):
            raise self._pid
        return self._pid

    def close(self) -> None:
        self.close_calls += 1
        if self._close_effect is not None:
            raise self._close_effect


@pytest.mark.parametrize(
    ("label", "fake_process", "expected_reason", "expected_terminate_calls", "expected_kill_calls"),
    [
        (
            "terminate() raises, process naturally not alive during its join",
            lambda: _FakeProcess(
                alive_sequence=[False],
                terminate_effect=_InjectedFailure("simulated terminate() failure"),
            ),
            "indeterminate",
            1,
            0,
        ),
        (
            "terminate() succeeds but does not stop it; naturally not alive afterward",
            lambda: _FakeProcess(alive_sequence=[False], exitcode_sequence=[0]),
            "indeterminate",
            1,
            0,
        ),
        (
            "terminate() fails, kill() then succeeds with confirming exitcode",
            lambda: _FakeProcess(
                alive_sequence=[True, False],
                exitcode_sequence=[-9],
                terminate_effect=_InjectedFailure("simulated terminate() failure"),
            ),
            "forced",
            1,
            1,
        ),
        (
            "both terminate() and kill() fail, process remains alive",
            lambda: _FakeProcess(
                alive_sequence=[True, True],
                terminate_effect=_InjectedFailure("simulated terminate() failure"),
                kill_effect=_InjectedFailure("simulated kill() failure"),
            ),
            "survived",
            1,
            1,
        ),
        (
            "terminate() succeeds with a confirming (negative) exitcode",
            lambda: _FakeProcess(alive_sequence=[False], exitcode_sequence=[-15]),
            "forced",
            1,
            0,
        ),
        (
            "post-terminate and post-kill liveness both unconfirmable",
            lambda: _FakeProcess(
                alive_sequence=[_InjectedFailure("simulated is_alive() failure")] * 2,
            ),
            "indeterminate",
            1,
            1,
        ),
    ],
    ids=[
        "terminate-raises-then-natural-exit",
        "terminate-noop-then-natural-exit",
        "failed-terminate-then-successful-kill",
        "both-forcible-operations-fail",
        "confirmed-forced-termination",
        "liveness-unconfirmable-throughout",
    ],
)
def test_attempt_forced_termination_classifies_containment_from_positive_evidence_only(
    label: str,
    fake_process: Callable[[], _FakeProcess],
    expected_reason: str,
    expected_terminate_calls: int,
    expected_kill_calls: int,
) -> None:
    """Deterministic, fake-process-driven proof that
    `_attempt_forced_termination` never classifies containment as
    `"forced"` from mere post-attempt absence of liveness alone (Phase 5
    fourteenth exit review §1): a raised or no-op forcible call that
    happens to be followed by the process no longer being alive is
    `"indeterminate"`, not `"forced"` — only a call that both completed
    without raising *and* left positive exitcode evidence earns
    `"forced"`. Uses a bare, never-`__enter__`ed `_BackgroundStatement`
    (no real process, connection, or backend pid needed) with its
    `_process` replaced by a fake — this method touches only
    `self._process`, never the database or IPC."""
    blocked = _BackgroundStatement(
        create_engine("postgresql+psycopg://unused/unused"), "SELECT 1", {}
    )
    process = fake_process()
    blocked._process = process
    problems: list[tuple[str, Exception]] = []

    reason = blocked._attempt_forced_termination(problems)

    assert reason == expected_reason, f"{label}: expected {expected_reason!r}, got {reason!r}"
    assert process.terminate_calls == expected_terminate_calls
    assert process.kill_calls == expected_kill_calls
    assert problems, "every containment outcome must be reported, not silently returned"


@pytest.mark.parametrize(
    ("containment_reason", "expected_state", "expect_protocol_failure"),
    [
        ("graceful", "missing-after-natural-exit", True),
        ("indeterminate", "missing-after-natural-exit", True),
        ("survived", "missing-after-natural-exit", True),
        ("forced", "missing-after-forced-termination", False),
    ],
)
def test_only_forced_containment_exempts_a_missing_outcome(
    containment_reason: str, expected_state: str, expect_protocol_failure: bool
) -> None:
    """Directly exercises the real `_finalize_worker_outcome` (not a
    reimplementation of its logic) with each of `_force_stop`'s four
    possible `containment_reason` values reduced to the one boolean it
    actually receives (`worker_was_forcibly_stopped`), proving a missing
    outcome is a protocol failure for every value except `"forced"`
    (Phase 5 fourteenth exit review §1). End-to-end coverage of the two
    ends actually reachable through a real worker already exists — a
    genuinely forced kill exempting a missing outcome
    (`test_background_statement_records_a_forced_termination_as_the_legitimate_missing_outcome_case`)
    and a graceful stop not exempting one
    (`test_background_statement_reports_a_protocol_failure_when_graceful_cancellation_conceals_a_missing_outcome`)
    — constructing a real process that ends up genuinely "survived" or
    "indeterminate" is impractical (the former is explicitly an
    OS-level guarantee violation this class assumes cannot happen); this
    test covers those states as well, directly, at the point where they
    actually matter: `_finalize_worker_outcome` only ever sees the
    boolean, never the specific reason string. A bare, never-`__enter__`ed
    `_BackgroundStatement` needs no real process or IPC: `_outcome_recv`
    is `None` by construction, so `_drain_one_outcome` reports "nothing
    arrived" immediately, exactly like a worker that never published."""
    blocked = _BackgroundStatement(
        create_engine("postgresql+psycopg://unused/unused"), "SELECT 1", {}
    )
    problems: list[tuple[str, Exception]] = []

    blocked._finalize_worker_outcome(
        problems, worker_was_forcibly_stopped=(containment_reason == "forced")
    )

    assert blocked.outcome_protocol_state == expected_state
    if expect_protocol_failure:
        assert any(label == "worker outcome protocol" for label, _ in problems), (
            f"containment_reason={containment_reason!r} must report a missing outcome as a "
            "protocol failure"
        )
    else:
        assert not problems, (
            "a positively confirmed forced termination must not report the missing outcome "
            "as a problem at all"
        )


@pytest.mark.parametrize(
    (
        "label",
        "fake_process",
        "expected_label_fragment",
        "expected_confirmed_stopped",
        "expected_terminate_calls",
        "expected_kill_calls",
    ),
    [
        (
            "pid inspection fails",
            lambda: _FakeProcess(alive_sequence=[False, False], pid=_InjectedFailure("pid boom")),
            "pid inspection (partial start)",
            True,
            1,
            0,
        ),
        (
            "initial is_alive() fails",
            lambda: _FakeProcess(
                alive_sequence=[_InjectedFailure("is_alive boom"), False], pid=None
            ),
            "initial status check (partial start)",
            True,
            1,
            0,
        ),
        (
            "terminate() fails",
            lambda: _FakeProcess(
                alive_sequence=[True, False],
                pid=4242,
                terminate_effect=_InjectedFailure("terminate boom"),
            ),
            "terminate (partial start)",
            True,
            1,
            0,
        ),
        (
            "first join() (post-terminate) fails",
            lambda: _FakeProcess(
                alive_sequence=[True, False],
                pid=4242,
                join_effect_sequence=[_InjectedFailure("join boom")],
            ),
            "post-terminate join (partial start)",
            True,
            1,
            0,
        ),
        (
            "post-terminate status check fails",
            lambda: _FakeProcess(
                alive_sequence=[True, _InjectedFailure("status boom"), False],
                pid=4242,
            ),
            "post-terminate status check (partial start)",
            True,
            1,
            1,
        ),
        (
            "kill() fails",
            lambda: _FakeProcess(
                alive_sequence=[True, True, False],
                pid=4242,
                kill_effect=_InjectedFailure("kill boom"),
            ),
            "kill (partial start)",
            True,
            1,
            1,
        ),
        (
            "second join() (post-kill) fails",
            lambda: _FakeProcess(
                alive_sequence=[True, True, False],
                pid=4242,
                join_effect_sequence=[None, _InjectedFailure("join boom")],
            ),
            "post-kill join (partial start)",
            True,
            1,
            1,
        ),
        (
            "final status check fails",
            lambda: _FakeProcess(
                alive_sequence=[True, True, _InjectedFailure("final status boom")],
                pid=4242,
            ),
            "reap (partial start)",
            False,
            1,
            1,
        ),
        (
            "process close fails on the confirmed never-started path",
            lambda: _FakeProcess(
                alive_sequence=[False], pid=None, close_effect=_InjectedFailure("close boom")
            ),
            "close process object (partial start)",
            True,
            0,
            0,
        ),
    ],
    ids=[
        "pid-inspection-failure",
        "initial-is-alive-failure",
        "terminate-failure",
        "first-join-failure",
        "post-terminate-status-failure",
        "kill-failure",
        "second-join-failure",
        "final-status-failure",
        "process-close-failure",
    ],
)
def test_cleanup_process_after_start_failure_collects_every_guarded_step_failure(
    label: str,
    fake_process: Callable[[], _FakeProcess],
    expected_label_fragment: str,
    expected_confirmed_stopped: bool,
    expected_terminate_calls: int,
    expected_kill_calls: int,
) -> None:
    """Deterministic, fake-process-driven proof that every read/action
    step inside `_cleanup_process_after_start_failure` — pid inspection,
    the initial and every subsequent liveness check, `terminate()`,
    both bounded joins, `kill()`, and the final `close()` — is
    individually guarded: a failure at any one of them is collected into
    `problems` rather than escaping and replacing the `Process.start()`
    exception this method exists to clean up after (which is exactly
    what an unguarded `join()`/`is_alive()` did before this review: see
    the class's own `_cleanup_process_after_start_failure` docstring),
    and never stops a later, still-valid containment step from being
    attempted (Phase 5 fourteenth exit review §2). `worker_confirmed_stopped`
    is asserted to become true only when the absence of a live child was
    actually established, never merely assumed from an unreadable
    status."""
    blocked = _BackgroundStatement(
        create_engine("postgresql+psycopg://unused/unused"), "SELECT 1", {}
    )
    process = fake_process()
    problems: list[tuple[str, Exception]] = []

    blocked._cleanup_process_after_start_failure(process, problems)

    labels = [lbl for lbl, _ in problems]
    assert expected_label_fragment in labels, (
        f"{label}: expected {expected_label_fragment!r} in {labels!r}"
    )
    assert blocked.worker_confirmed_stopped is expected_confirmed_stopped, label
    assert process.terminate_calls == expected_terminate_calls, label
    assert process.kill_calls == expected_kill_calls, label


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

        blocked = _BackgroundStatement(engine, "SELECT pg_advisory_xact_lock(:k)", {"k": lock_key})
        worker_pid: int | None = None
        try:
            with pytest.raises(_SentinelFailure), blocked:
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
            # the real, primary signal path in this test — _emergency_teardown
            # is a genuinely independent backstop (not __exit__() again),
            # not the primary proof point.
            _emergency_teardown(blocked, engine, extra_connections=(first,))


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
            _emergency_teardown(blocked, engine, extra_connections=(first,))


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
            _emergency_teardown(blocked, engine, extra_connections=(first,))


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

    try:
        with pytest.raises(_SentinelFailure) as excinfo, blocked:
            # No wait_until_blocked here: pg_sleep never reports
            # wait_event_type 'Lock', so there is nothing to poll for —
            # the worker starts sleeping essentially immediately after
            # __enter__ returns (which itself only returns once the
            # connection, its lock_timeout, and its backend pid are all
            # established).
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
    finally:
        _emergency_teardown(blocked, engine)


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

    try:
        with pytest.raises(RuntimeError, match="forcibly terminated"), blocked:
            pass  # No exception here: __exit__ not raising is the only way this test can fail.

        assert blocked.worker_confirmed_stopped, "the worker process must not survive __exit__"
        _assert_backend_eventually_gone(engine, blocked.backend_pid)
    finally:
        _emergency_teardown(blocked, engine)


class _BackendConnectable(Protocol):
    """Structural type for what `_run_emergency_teardown` and its helpers
    actually need from an `engine` argument — just `.connect()` as a
    context manager. Real `sqlalchemy.Engine` satisfies this
    structurally, and so does the `_FakeDBEngine` test double used to
    unit-test this module's backend-verification failure paths, so
    these functions can accept either without a type mismatch at every
    fake-engine call site."""

    def connect(self) -> contextlib.AbstractContextManager[Any]: ...


def _emergency_process_state(
    problems: list[tuple[str, Exception]], label: str, process: Any
) -> str:
    """Returns `"closed"`, `"alive"`, `"not-alive"`, or `"unknown"` for a
    `Process` object during emergency teardown. `"closed"` (an
    already-closed `Process` object — the benign, common case when
    `_BackgroundStatement.__exit__` already fully tore it down and this
    net is running as a redundant backstop) is distinguished from
    `"unknown"` so the net never re-attempts `terminate()`/`close()` on
    an object that no longer supports either call, which would
    otherwise report a spurious problem for a test that actually passed
    cleanly."""
    try:
        alive = process.is_alive()
    except ValueError:
        return "closed"
    except Exception as exc:  # noqa: BLE001 - collected, not swallowed
        problems.append((label, exc))
        return "unknown"
    return "alive" if alive else "not-alive"


def _run_emergency_teardown(
    blocked: "_BackgroundStatement",
    engine: _BackendConnectable,
    extra_connections: tuple[Connection, ...],
) -> list[tuple[str, Exception]]:
    """Does the actual work for `_emergency_teardown` (see its docstring
    for the contract) and returns every problem encountered instead of
    raising or suppressing any of them — collected, never silently
    discarded, exactly like every cleanup path in `_BackgroundStatement`
    itself (Phase 5 fourteenth exit review §3)."""
    problems: list[tuple[str, Exception]] = []

    for connection in extra_connections:
        _attempt(problems, "emergency rollback of test-controlled connection", connection.rollback)

    process = blocked._process
    if process is not None:
        state = _emergency_process_state(problems, "emergency status check", process)
        if state in ("alive", "unknown"):
            _attempt(problems, "emergency terminate", process.terminate)
            _attempt(problems, "emergency join", lambda: process.join(timeout=5.0))
            state = _emergency_process_state(
                problems, "emergency status check after terminate", process
            )
        if state in ("alive", "unknown"):
            _attempt(problems, "emergency kill", process.kill)
            _attempt(problems, "emergency join after kill", lambda: process.join(timeout=5.0))
            state = _emergency_process_state(problems, "emergency status check after kill", process)
        if state == "alive":
            problems.append(
                (
                    "emergency containment",
                    RuntimeError("worker process survived emergency termination"),
                )
            )
        elif state == "unknown":
            problems.append(
                (
                    "emergency containment",
                    RuntimeError(
                        "worker process liveness could not be confirmed after emergency termination"
                    ),
                )
            )
        elif state == "not-alive":
            _attempt(problems, "emergency close process object", process.close)
        # state == "closed": already fully torn down; nothing more to do.

    pid = blocked._backend_pid_value
    if pid is not None and _attempt(
        problems,
        "emergency pg_terminate_backend",
        lambda: _emergency_terminate_backend(engine, pid),
    ):
        _confirm_backend_gone_or_report(problems, engine, pid)

    for label, conn in (
        ("handshake_recv", blocked._handshake_recv),
        ("handshake_send", blocked._handshake_send),
        ("outcome_recv", blocked._outcome_recv),
        ("outcome_send", blocked._outcome_send),
        ("control_recv", blocked._control_recv),
        ("control_send", blocked._control_send),
    ):
        if conn is None:
            continue
        _attempt(problems, f"emergency close {label}", conn.close)

    return problems


def _emergency_terminate_backend(engine: _BackendConnectable, pid: int) -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT pg_terminate_backend(:p)"), {"p": pid})
        conn.commit()


def _confirm_backend_gone_or_report(
    problems: list[tuple[str, Exception]], engine: _BackendConnectable, pid: int
) -> None:
    deadline = time.monotonic() + 5.0
    verification_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT 1 FROM pg_stat_activity WHERE pid = :p"), {"p": pid}
                ).one_or_none()
        except Exception as exc:  # noqa: BLE001 - collected, not swallowed
            verification_error = exc
            time.sleep(0.05)
            continue
        verification_error = None
        if row is None:
            return
        time.sleep(0.05)

    if verification_error is not None:
        problems.append(
            (
                "emergency backend verification",
                RuntimeError(
                    f"could not verify backend pid {pid} disappeared: {verification_error}"
                ),
            )
        )
        return
    problems.append(
        (
            "emergency backend verification",
            RuntimeError(
                f"backend pid {pid} still present in pg_stat_activity 5s after emergency "
                "termination"
            ),
        )
    )


def _emergency_teardown(
    blocked: "_BackgroundStatement",
    engine: _BackendConnectable,
    *,
    extra_connections: tuple[Connection, ...] = (),
) -> None:
    """Last-resort, genuinely independent cleanup for `_BackgroundStatement`
    regression tests, called from a test's own `finally` block after its
    assertions about the helper's contract have already run (Phase 5
    thirteenth exit review §5; redesigned in the fourteenth review §3 to
    close every resource it touches and to never silently suppress a
    failure). Deliberately never calls `blocked.__exit__()`,
    `blocked._force_stop()`, or any other `_BackgroundStatement` method
    that is itself part of what many of these tests exercise: relying on
    the implementation under test to clean up after itself would let a
    genuinely broken implementation silently pass — leaking a live
    worker, backend connection, IPC channel, or process object — instead
    of the test failing loudly the way an independent safety net must.
    Operates directly on the real `multiprocessing.Process`/`Connection`
    objects and, if a backend pid was ever recorded, fresh independent
    PostgreSQL connections — the same OS/database primitives
    `_BackgroundStatement` itself is built from, invoked here
    independently of its own code, never counted as evidence that
    `_BackgroundStatement` met its own contract (a problem found here is
    always reported as this net's own finding, never folded into or
    mistaken for the class's own cleanup result).

    Every step — process termination/kill/join/status, backend
    termination and confirmation, every IPC endpoint, the process object
    itself, and (via `extra_connections`) any test-controlled
    transaction/advisory-lock-holding connection the caller wants
    included — is attempted independently, with every failure collected
    rather than suppressed, and every wait bounded (5s). Safe to call
    unconditionally and repeatedly: every operation here tolerates a
    process that is already stopped, already closed, or was never
    started, and a backend that is already gone.

    A test-body exception already propagating through the `finally`
    block that calls this — detected via `sys.exc_info()`, which
    reflects exactly that during unwinding — is preserved as primary:
    any problem this net finds is attached to it as a note, never
    replacing it. When nothing is already propagating (including when an
    expected failure was already fully handled by an enclosing
    `pytest.raises`), a problem this net finds is raised directly,
    surfacing it as the test's own failure rather than letting it
    disappear silently."""
    problems = _run_emergency_teardown(blocked, engine, extra_connections)
    if not problems:
        return
    summary = "; ".join(f"{label}: {e}" for label, e in problems)
    message = f"_emergency_teardown found unreleased or failed resources: {summary}"
    active_exc = sys.exc_info()[1]
    if active_exc is not None:
        active_exc.add_note(message)
        return
    raise RuntimeError(message)


# ---------------------------------------------------------------------------
# Unit tests of the independent _emergency_teardown safety net itself
# ---------------------------------------------------------------------------
# Phase 5 fourteenth exit review §3: the net must be tested like any other
# piece of cleanup logic, using fake process/pipe/backend objects rather than
# relying on it happening to behave correctly as a byproduct of the other
# ~45 regression tests that call it. None of these touch a real process or
# a real database.


class _FakeDBResult:
    def __init__(self, row_present: bool) -> None:
        self._row_present = row_present

    def one_or_none(self) -> tuple[int] | None:
        return (1,) if self._row_present else None


class _FakeDBConnection:
    def __init__(self, *, execute_effect: Exception | None, row_present: bool) -> None:
        self._execute_effect = execute_effect
        self._row_present = row_present
        self.execute_calls = 0
        self.committed = False

    def execute(self, _stmt: object, _params: object = None) -> _FakeDBResult:
        self.execute_calls += 1
        if self._execute_effect is not None:
            raise self._execute_effect
        return _FakeDBResult(self._row_present)

    def commit(self) -> None:
        self.committed = True


class _FakeDBConnectionCtx:
    def __init__(self, connection: _FakeDBConnection) -> None:
        self._connection = connection

    def __enter__(self) -> _FakeDBConnection:
        return self._connection

    def __exit__(self, *_args: object) -> None:
        return None


class _FakeDBEngine:
    """A minimal stand-in for a SQLAlchemy `Engine`, used only to drive
    `_emergency_terminate_backend`/`_confirm_backend_gone_or_report`
    deterministically — real backend-verification failure/timeout paths
    are impractical to construct against a real database on demand, the
    same reasoning behind every other fake in this file. `connect_effect`
    simulates the connection attempt itself failing; `execute_effect`
    simulates the query failing after a connection was made;
    `row_present` controls whether the backend still "shows up" in the
    fake `pg_stat_activity` row."""

    def __init__(
        self,
        *,
        connect_effect: Exception | None = None,
        execute_effect: Exception | None = None,
        row_present: bool = False,
        fail_from_connection_number: int | None = None,
    ) -> None:
        self._connect_effect = connect_effect
        self._execute_effect = execute_effect
        self._row_present = row_present
        self._fail_from_connection_number = fail_from_connection_number
        self._connection_count = 0
        self.connections: list[_FakeDBConnection] = []

    def connect(self) -> _FakeDBConnectionCtx:
        if self._connect_effect is not None:
            raise self._connect_effect
        self._connection_count += 1
        effect = None
        if self._execute_effect is not None and (
            self._fail_from_connection_number is None
            or self._connection_count >= self._fail_from_connection_number
        ):
            effect = self._execute_effect
        connection = _FakeDBConnection(execute_effect=effect, row_present=self._row_present)
        self.connections.append(connection)
        return _FakeDBConnectionCtx(connection)


def _bare_blocked() -> "_BackgroundStatement":
    """A `_BackgroundStatement` constructed but never `__enter__`ed — no
    real process, IPC, or database connection exists, so its attributes
    can be freely replaced with fakes for unit-testing cleanup logic in
    isolation."""
    return _BackgroundStatement(create_engine("postgresql+psycopg://unused/unused"), "SELECT 1", {})


def test_run_emergency_teardown_reports_nothing_on_the_happy_path() -> None:
    """A process that already exited cleanly (state "closed" — the common
    case when `_BackgroundStatement.__exit__` already ran) and no
    recorded backend pid: the net finds nothing to do and reports no
    problems."""
    blocked = _bare_blocked()
    blocked._process = _FakeProcess(alive_sequence=[ValueError("process object is closed")])

    problems = _run_emergency_teardown(blocked, _FakeDBEngine(), ())

    assert problems == []


def test_run_emergency_teardown_closes_a_live_process_after_a_successful_terminate() -> None:
    blocked = _bare_blocked()
    process = _FakeProcess(alive_sequence=[True, False])
    blocked._process = process

    problems = _run_emergency_teardown(blocked, _FakeDBEngine(), ())

    assert problems == []
    assert process.terminate_calls == 1
    assert process.kill_calls == 0
    assert process.close_calls == 1


def test_run_emergency_teardown_escalates_to_kill_when_terminate_fails() -> None:
    blocked = _bare_blocked()
    process = _FakeProcess(
        alive_sequence=[True, True, False],
        terminate_effect=_InjectedFailure("terminate boom"),
    )
    blocked._process = process

    problems = _run_emergency_teardown(blocked, _FakeDBEngine(), ())

    labels = [label for label, _ in problems]
    assert "emergency terminate" in labels
    assert process.kill_calls == 1
    assert process.close_calls == 1


def test_run_emergency_teardown_reports_survival_after_both_forcible_operations_fail() -> None:
    blocked = _bare_blocked()
    process = _FakeProcess(
        alive_sequence=[True, True, True],
        terminate_effect=_InjectedFailure("terminate boom"),
        kill_effect=_InjectedFailure("kill boom"),
    )
    blocked._process = process

    problems = _run_emergency_teardown(blocked, _FakeDBEngine(), ())

    labels = [label for label, _ in problems]
    assert "emergency terminate" in labels
    assert "emergency kill" in labels
    assert "emergency containment" in labels
    assert process.close_calls == 0, "a surviving process object must not be closed"


def test_run_emergency_teardown_reports_a_problem_when_both_bounded_joins_fail() -> None:
    blocked = _bare_blocked()
    process = _FakeProcess(
        alive_sequence=[True, True, False],
        join_effect_sequence=[_InjectedFailure("join boom"), _InjectedFailure("join boom 2")],
    )
    blocked._process = process

    problems = _run_emergency_teardown(blocked, _FakeDBEngine(), ())

    labels = [label for label, _ in problems]
    assert "emergency join" in labels
    assert "emergency join after kill" in labels
    # Still reaches a final close: both joins failing does not by itself
    # stop the net from taking whatever containment step is still valid.
    assert process.close_calls == 1


def test_run_emergency_teardown_reports_a_problem_when_status_inspection_fails() -> None:
    blocked = _bare_blocked()
    process = _FakeProcess(alive_sequence=[_InjectedFailure("is_alive boom")])
    blocked._process = process

    problems = _run_emergency_teardown(blocked, _FakeDBEngine(), ())

    labels = [label for label, _ in problems]
    assert "emergency status check" in labels
    # An unconfirmable status must still be treated as "might be alive",
    # never as "already gone" — terminate() is still attempted.
    assert process.terminate_calls == 1


def test_run_emergency_teardown_reports_a_problem_when_the_process_object_fails_to_close() -> None:
    blocked = _bare_blocked()
    process = _FakeProcess(alive_sequence=[False], close_effect=_InjectedFailure("close boom"))
    blocked._process = process

    problems = _run_emergency_teardown(blocked, _FakeDBEngine(), ())

    labels = [label for label, _ in problems]
    assert "emergency close process object" in labels


def test_run_emergency_teardown_closes_every_ipc_endpoint_independently() -> None:
    """All six IPC endpoints fail to close; every one must be attempted
    and reported, not just the first."""
    blocked = _bare_blocked()
    blocked._handshake_recv = _FakeConnection("handshake_recv")
    blocked._handshake_send = _FakeConnection("handshake_send")
    blocked._outcome_recv = _FakeConnection("outcome_recv")
    blocked._outcome_send = _FakeConnection("outcome_send")
    blocked._control_recv = _FakeConnection("control_recv")
    blocked._control_send = _FakeConnection("control_send")

    problems = _run_emergency_teardown(blocked, _FakeDBEngine(), ())

    labels = {label for label, _ in problems}
    for endpoint in (
        "handshake_recv",
        "handshake_send",
        "outcome_recv",
        "outcome_send",
        "control_recv",
        "control_send",
    ):
        assert f"emergency close {endpoint}" in labels, f"expected {endpoint} close reported"


def test_run_emergency_teardown_reports_a_problem_when_pg_terminate_backend_fails() -> None:
    blocked = _bare_blocked()
    blocked._backend_pid_value = 999999
    engine = _FakeDBEngine(connect_effect=_InjectedFailure("connection refused"))

    problems = _run_emergency_teardown(blocked, engine, ())

    labels = [label for label, _ in problems]
    assert "emergency pg_terminate_backend" in labels
    assert not any(label == "emergency backend verification" for label in labels), (
        "verification must not even be attempted once the terminate call itself failed"
    )


def test_run_emergency_teardown_reports_a_problem_when_backend_verification_query_fails() -> None:
    """The `pg_terminate_backend` call itself (connection #1) succeeds;
    every verification poll afterward (connection #2+) fails — proving
    the verification failure is reported as its own distinct problem,
    not conflated with a terminate-call failure."""
    blocked = _bare_blocked()
    blocked._backend_pid_value = 999999
    engine = _FakeDBEngine(
        execute_effect=_InjectedFailure("query boom"), fail_from_connection_number=2
    )

    problems = _run_emergency_teardown(blocked, engine, ())

    labels = [label for label, _ in problems]
    assert "emergency pg_terminate_backend" not in labels
    assert "emergency backend verification" in labels


def test_run_emergency_teardown_reports_a_problem_when_the_backend_never_disappears() -> None:
    blocked = _bare_blocked()
    blocked._backend_pid_value = 999999
    engine = _FakeDBEngine(row_present=True)

    problems = _run_emergency_teardown(blocked, engine, ())

    labels = [label for label, _ in problems]
    assert "emergency backend verification" in labels
    assert any(
        "still present" in str(exc)
        for label, exc in problems
        if label == "emergency backend verification"
    )


def test_run_emergency_teardown_confirms_a_gone_backend_with_no_problems() -> None:
    blocked = _bare_blocked()
    blocked._backend_pid_value = 999999
    engine = _FakeDBEngine(row_present=False)

    problems = _run_emergency_teardown(blocked, engine, ())

    assert problems == []


def test_run_emergency_teardown_reports_a_problem_when_an_extra_connection_fails_to_rollback() -> (
    None
):
    blocked = _bare_blocked()

    class _FailingRollback:
        def rollback(self) -> None:
            raise _InjectedFailure("rollback boom")

    problems = _run_emergency_teardown(blocked, _FakeDBEngine(), (_FailingRollback(),))  # type: ignore[arg-type]

    labels = [label for label, _ in problems]
    assert "emergency rollback of test-controlled connection" in labels


def test_emergency_teardown_attaches_problems_to_an_already_propagating_exception() -> None:
    """The `sys.exc_info()`-based preservation contract: a problem found
    while a test-body exception is already unwinding through the
    `finally` block is attached as a note, never replaces it, and no new
    exception escapes from `_emergency_teardown` itself."""
    blocked = _bare_blocked()

    def _raise_original() -> None:
        blocked._process = _FakeProcess(
            alive_sequence=[True, True],
            terminate_effect=_InjectedFailure("terminate boom"),
            kill_effect=_InjectedFailure("kill boom"),
        )
        try:
            raise _SentinelFailure("original test-body failure")
        finally:
            _emergency_teardown(blocked, _FakeDBEngine())

    with pytest.raises(_SentinelFailure) as excinfo:
        _raise_original()
    notes = "\n".join(getattr(excinfo.value, "__notes__", []))
    assert "unreleased or failed resources" in notes.lower()


def test_emergency_teardown_raises_directly_when_nothing_else_is_propagating() -> None:
    blocked = _bare_blocked()
    blocked._process = _FakeProcess(
        alive_sequence=[True, True],
        terminate_effect=_InjectedFailure("terminate boom"),
        kill_effect=_InjectedFailure("kill boom"),
    )

    with pytest.raises(RuntimeError, match="unreleased or failed resources"):
        _emergency_teardown(blocked, _FakeDBEngine())


def test_emergency_teardown_is_silent_when_it_finds_nothing_and_nothing_is_propagating() -> None:
    blocked = _bare_blocked()
    blocked._process = _FakeProcess(alive_sequence=[ValueError("process object is closed")])

    _emergency_teardown(blocked, _FakeDBEngine())  # must not raise


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
    try:
        with pytest.raises(RuntimeError, match="failed to start") as excinfo:
            blocked.__enter__()
        assert stage in str(excinfo.value), f"expected the injected stage {stage!r} to be reported"
        assert blocked._process is not None
        assert blocked.worker_confirmed_stopped
    finally:
        _emergency_teardown(blocked, engine)


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
    try:
        with pytest.raises(RuntimeError, match="failed to start") as excinfo:
            blocked.__enter__()
        notes = "\n".join(getattr(excinfo.value, "__notes__", []))
        assert "cleanup" in notes.lower(), (
            f"expected startup cleanup problems to be reported as notes, got: {notes!r}"
        )
        assert blocked._process is not None
        assert blocked.worker_confirmed_stopped
    finally:
        _emergency_teardown(blocked, engine)


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
    try:
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
    finally:
        _emergency_teardown(blocked, engine)


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
    try:
        with pytest.raises(RuntimeError, match="failed to start"):
            blocked.__enter__()
        assert blocked._process is not None
        assert blocked.worker_confirmed_stopped
    finally:
        # The real, reachable engine — not unreachable_engine, which
        # could never connect in the first place and is only for proving
        # __enter__'s own failure path — since backend_pid was never
        # even established here regardless.
        _emergency_teardown(blocked, postgres_engine)


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
    try:
        with blocked:
            status, exc = blocked.resume_and_get_outcome("statement-failure probe")

        assert status == "failed"
        assert exc is not None
        assert "division by zero" in str(exc).lower()
    finally:
        _emergency_teardown(blocked, engine)


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
    try:
        with blocked:
            status, exc = blocked.resume_and_get_outcome("commit-failure probe")

        assert status == "failed", (
            f"a failed commit must never be reported as committed, got: {status}"
        )
        assert exc is not None
        assert "closed" in str(exc).lower(), (
            f"expected the commit failure's own connection-closed message to be the reported "
            f"cause, got: {exc}"
        )
    finally:
        _emergency_teardown(blocked, engine)


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
    try:
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
    finally:
        _emergency_teardown(blocked, engine)


def test_background_statement_exit_drains_and_reports_an_outcome_nobody_consumed(
    postgres_engine: Engine,
) -> None:
    """The with block never calls resume_and_get_outcome — the worker
    finishes a failing statement on its own before the block exits (proven
    by polling before __exit__ ever runs, not after). Proves __exit__
    itself drains the outcome queue and fails the test, rather than
    silently discarding a failure nobody explicitly asked for."""
    engine = postgres_engine
    captured: list[_BackgroundStatement] = []

    def _run_and_wait_for_natural_exit() -> None:
        with _BackgroundStatement(engine, "SELECT 1/0", {}) as blocked:
            captured.append(blocked)
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

    try:
        with pytest.raises(RuntimeError, match="division by zero"):
            _run_and_wait_for_natural_exit()
    finally:
        if captured:
            _emergency_teardown(captured[0], engine)


# ---------------------------------------------------------------------------
# Worker outcome protocol totality (Phase 5 twelfth exit review §2)
# ---------------------------------------------------------------------------
# The tests above prove a *present* outcome is reported correctly. These
# prove the protocol is total, not best-effort: a worker that exits on its
# own without ever publishing one is a failure, not silent success; a
# worker that publishes more than one is also a failure; and the one
# legitimate "no outcome" case — the controller itself terminated the
# worker before it could publish anything — is recorded as such rather than
# conflated with either failure mode.


def test_background_statement_reports_a_protocol_failure_when_the_worker_exits_without_publishing_an_outcome(
    postgres_engine: Engine,
) -> None:
    """The worker's own outcome-publish step is made to fail
    (deterministically, via fault injection) after an otherwise fully
    successful statement and commit, so the worker exits on its own having
    never published anything — the one channel for reporting that failure
    is exactly what failed. Proves the controller detects this as its own
    distinct protocol failure rather than silently treating a naturally
    exited worker with an empty outcome channel as success."""
    engine = postgres_engine
    captured: list[_BackgroundStatement] = []

    def _run_and_wait_for_natural_exit() -> None:
        with _BackgroundStatement(
            engine, "SELECT 1", {}, _fault_injection_stage="outcome_publish_fails"
        ) as blocked:
            captured.append(blocked)
            # Wait for the worker to genuinely finish on its own (proven by
            # polling before __exit__ ever runs, not after), so this proves
            # a *natural* exit without an outcome — not a race against
            # __exit__'s own forced-termination path treating it as the
            # legitimate "deliberately terminated" case instead.
            deadline = time.monotonic() + 5.0
            while blocked._process.is_alive() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert not blocked._process.is_alive(), (
                "worker did not finish the fast statement in time"
            )

    try:
        with pytest.raises(RuntimeError, match="worker outcome protocol") as excinfo:
            _run_and_wait_for_natural_exit()

        assert "without publishing a required outcome" in str(excinfo.value)
        assert captured[0].outcome_protocol_state == "missing-after-natural-exit"
        assert captured[0].worker_confirmed_stopped
    finally:
        if captured:
            _emergency_teardown(captured[0], engine)


def test_background_statement_reports_a_protocol_failure_for_a_duplicate_outcome(
    postgres_engine: Engine,
) -> None:
    """The worker is made to publish its outcome twice (deterministically,
    via fault injection) after an otherwise fully successful statement and
    commit. resume_and_get_outcome consumes the first — a normal-looking
    "committed" result — but the unexpected second must still be detected
    and reported as its own protocol failure, not silently discarded just
    because a first one was already consumed."""
    engine = postgres_engine
    blocked = _BackgroundStatement(
        engine, "SELECT 1", {}, _fault_injection_stage="duplicate_outcome_publish"
    )

    try:
        with pytest.raises(RuntimeError, match="worker outcome protocol") as excinfo, blocked:
            status, exc = blocked.resume_and_get_outcome("duplicate-outcome probe")
            assert status == "committed" and exc is None, (
                "the first, normal outcome must still be reported correctly"
            )

        assert "more than one outcome" in str(excinfo.value)
    finally:
        _emergency_teardown(blocked, engine)


def test_background_statement_marks_outcome_protocol_state_consumed_on_the_happy_path(
    postgres_engine: Engine,
) -> None:
    """The ordinary case: resume_and_get_outcome consumes the worker's one
    outcome and nothing else is ever published. Proves
    outcome_protocol_state ends up "consumed" — an already-consumed
    outcome is not itself a failure — rather than being left at its
    initial "pending" value or confused with either failure mode."""
    engine = postgres_engine
    blocked = _BackgroundStatement(engine, "SELECT 1", {})
    try:
        with blocked:
            status, exc = blocked.resume_and_get_outcome("happy-path probe")
            assert status == "committed"
            assert exc is None

        assert blocked.outcome_protocol_state == "consumed"
    finally:
        _emergency_teardown(blocked, engine)


def test_background_statement_records_a_forced_termination_as_the_legitimate_missing_outcome_case(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worker is pg_sleep-blocked (never reaches its outcome-publishing
    step at all) and every active stopping mechanism is mocked to fail, so
    __exit__ must fall back to forced termination — the one case where a
    missing outcome is legitimate, not a protocol failure. Proves
    outcome_protocol_state records that reason explicitly, and that no
    spurious "worker outcome protocol" problem is added alongside the
    (already covered by other tests) forced-termination problem itself."""
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

    try:
        with pytest.raises(RuntimeError, match="forcibly terminated") as excinfo, blocked:
            pass

        assert blocked.outcome_protocol_state == "missing-after-forced-termination"
        assert blocked.worker_confirmed_stopped
        assert "worker outcome protocol" not in str(excinfo.value), (
            "a deliberately terminated worker's missing outcome must not also be reported as a "
            "protocol failure"
        )
        _assert_backend_eventually_gone(engine, blocked.backend_pid)
    finally:
        _emergency_teardown(blocked, engine)


def test_background_statement_reports_a_protocol_failure_when_graceful_cancellation_conceals_a_missing_outcome(
    postgres_engine: Engine,
) -> None:
    """A worker blocked on a genuine advisory-lock wait is stopped by the
    real, unmocked `pg_terminate_backend()` signal — a graceful mechanism,
    not this controller calling `terminate()`/`kill()` on the OS process
    itself — and its outcome-publish step is then made to fail
    (deterministically, via fault injection). Proves the resulting missing
    outcome is still reported as a protocol failure: graceful cancellation
    leaves the worker's own outcome-publication step fully reachable, so
    nothing here legitimately excuses a missing outcome the way a genuine
    forced OS-level termination would (Phase 5 thirteenth exit review §1)
    — the bug this review found: `__exit__` previously treated the worker
    merely being *alive* when the `with` block exited as proof of forced
    termination, regardless of how containment was actually achieved."""
    engine = postgres_engine
    lock_key = uuid.uuid4().int % (2**63 - 1)

    with engine.connect() as first:
        first.begin()
        first.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key})

        blocked = _BackgroundStatement(
            engine,
            "SELECT pg_advisory_xact_lock(:k)",
            {"k": lock_key},
            _fault_injection_stage="outcome_publish_fails",
        )
        try:
            with pytest.raises(RuntimeError, match="worker outcome protocol") as excinfo, blocked:
                blocked.wait_until_blocked(first, "the worker (graceful-cancellation probe)")
                # Deliberately exit while still genuinely blocked and
                # `first` still holds the lock: __exit__ must reach
                # _force_stop() itself, and the real (unmocked)
                # pg_terminate_backend() signal is what actually ends
                # the worker — a graceful mechanism, not this
                # controller calling terminate()/kill() on the OS
                # process.

            assert "without publishing a required outcome" in str(excinfo.value)
            assert blocked.outcome_protocol_state == "missing-after-natural-exit", (
                "graceful cancellation must not be misclassified as the legitimate forced-"
                f"termination exemption, got: {blocked.outcome_protocol_state!r}"
            )
            assert blocked.worker_confirmed_stopped
        finally:
            _emergency_teardown(blocked, engine, extra_connections=(first,))


# ---------------------------------------------------------------------------
# Worker cleanup independence (Phase 5 twelfth exit review §3)
# ---------------------------------------------------------------------------
# _worker_main's finally block attempts signaling the watcher, joining it,
# closing the connection, and disposing the engine independently of one
# another. These prove the first two of those specifically: a failure
# signaling the watcher to stop must not skip anything after it, and a
# watcher that does not honor that signal within its bounded join is
# itself reported rather than silently ignored.


def test_background_statement_reports_a_problem_when_signaling_the_watcher_to_stop_fails(
    postgres_engine: Engine,
) -> None:
    """The worker's own signal to its cancel-watcher thread ("please stop
    now") is made to fail (deterministically, via fault injection) after
    an otherwise fully successful statement and commit. Proves that
    failure is collected as a cleanup problem and reported through the
    outcome — never skipping the watcher join, close(), dispose(), or
    outcome publication that follow it in the worker's own finally
    block."""
    engine = postgres_engine
    blocked = _BackgroundStatement(
        engine, "SELECT 1", {}, _fault_injection_stage="watcher_stop_signal_fails"
    )
    try:
        with blocked:
            status, exc = blocked.resume_and_get_outcome("watcher-stop-signal-failure probe")

        assert status == "failed", (
            f"a failed watcher-stop signal must still fail the caller, got: {status}"
        )
        assert exc is not None
        notes = "\n".join(getattr(exc, "__notes__", []))
        assert "signal watcher to stop" in notes.lower(), (
            f"expected the watcher-stop-signal failure to be reported, got notes: {notes!r}"
        )
    finally:
        _emergency_teardown(blocked, engine)


def test_background_statement_reports_a_problem_when_the_watcher_does_not_stop_within_its_bounded_join(
    postgres_engine: Engine,
) -> None:
    """The worker's cancel-watcher thread is made to ignore its own stop
    signal (deterministically, via fault injection) after an otherwise
    fully successful statement and commit — proving a watcher still alive
    after its bounded join is itself recorded as a cleanup problem, not
    silently ignored. A short _watcher_join_timeout_seconds keeps this
    test fast rather than waiting out the 5s production default; the
    watcher thread is daemon, so the worker process still exits normally
    around it regardless."""
    engine = postgres_engine
    blocked = _BackgroundStatement(
        engine,
        "SELECT 1",
        {},
        _fault_injection_stage="watcher_ignores_stop_signal",
        _watcher_join_timeout_seconds=0.5,
    )
    try:
        with blocked:
            status, exc = blocked.resume_and_get_outcome("watcher-join-timeout probe")

        assert status == "failed", (
            f"a watcher that never stops must still fail the caller, got: {status}"
        )
        assert exc is not None
        notes = "\n".join(getattr(exc, "__notes__", []))
        assert "watcher thread" in notes.lower(), (
            f"expected the watcher-still-alive problem to be reported, got notes: {notes!r}"
        )
    finally:
        _emergency_teardown(blocked, engine)


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
        # Independently covers the OS process itself too, not just the
        # PostgreSQL backend above — relying on blocked.__exit__() alone
        # would not catch a bug in the very cleanup path this test targets.
        _emergency_teardown(blocked, engine)


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
            _emergency_teardown(blocked, engine, extra_connections=(first,))


def test_background_statement_reports_a_problem_when_backend_verification_itself_fails_on_natural_completion(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backend verification is mocked to fail for a worker that completes
    entirely on its own — no forced-stop path involved at all. Proves
    verification actually runs on the natural-completion path (Phase 5
    thirteenth exit review §2), not only when `_force_stop()` happens to
    run it, and that a verification failure there is reported rather than
    silently skipped."""
    engine = postgres_engine
    blocked = _BackgroundStatement(engine, "SELECT 1", {})
    monkeypatch.setattr(blocked, "_query_backend_state", _raise_injected_failure)

    try:
        with pytest.raises(RuntimeError, match="could not verify"), blocked:
            status, exc = blocked.resume_and_get_outcome("natural-completion verification probe")
            assert status == "committed" and exc is None
    finally:
        _emergency_teardown(blocked, engine)


def test_background_statement_attaches_a_natural_completion_verification_failure_to_an_existing_exception(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same as above, but the with block's own body raises first. Proves
    the natural-completion verification failure is attached as a note to
    that already-propagating exception rather than replacing it."""
    engine = postgres_engine
    blocked = _BackgroundStatement(engine, "SELECT 1", {})
    monkeypatch.setattr(blocked, "_query_backend_state", _raise_injected_failure)

    try:
        with pytest.raises(_SentinelFailure) as excinfo, blocked:
            blocked.resume_and_get_outcome(
                "natural-completion verification probe (with body exception)"
            )
            raise _SentinelFailure(
                "deliberate failure with natural-completion verification mocked to fail"
            )

        assert isinstance(excinfo.value, _SentinelFailure)
        notes = "\n".join(getattr(excinfo.value, "__notes__", []))
        assert "could not verify" in notes.lower(), (
            f"expected the natural-completion verification failure to be reported, got: {notes!r}"
        )
    finally:
        _emergency_teardown(blocked, engine)


# ---------------------------------------------------------------------------
# Process startup, reaping, and IPC cleanup
# ---------------------------------------------------------------------------


def test_background_statement_enter_reports_process_construction_failure(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """multiprocessing.Process(...) construction itself is mocked to fail —
    a real OS-level trigger for this is impractical to construct
    deterministically. Proves __enter__ reports it clearly, with no process
    ever stored (there is nothing valid to reap), and its IPC channels
    still closed."""
    engine = postgres_engine
    ctx = multiprocessing.get_context("spawn")
    monkeypatch.setattr(ctx, "Process", _raise_injected_failure)
    monkeypatch.setattr(multiprocessing, "get_context", lambda method: ctx)

    blocked = _BackgroundStatement(engine, "SELECT 1", {})
    try:
        with pytest.raises(RuntimeError, match="failed to construct"):
            blocked.__enter__()
        assert blocked._process is None
    finally:
        _emergency_teardown(blocked, engine)


def test_background_statement_enter_reports_process_start_failure(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """multiprocessing.Process.start() itself is mocked to fail — again, a
    real OS-level trigger (resource exhaustion) is impractical to construct
    deterministically. Proves __enter__ reports it clearly, and that
    __enter__'s own cleanup closes the Process object directly rather than
    calling terminate()/kill()/join() on it, which are invalid operations
    on a process that genuinely never started (Phase 5 thirteenth exit
    review §3: ownership of the constructed Process object begins before
    start() is even called, not only once start() has confirmed success —
    self._process is retained, not reset to None, so worker_confirmed_stopped
    is the correct post-failure check here, not `_process is None`)."""
    engine = postgres_engine
    ctx = multiprocessing.get_context("spawn")
    monkeypatch.setattr(ctx.Process, "start", _raise_injected_failure)
    monkeypatch.setattr(multiprocessing, "get_context", lambda method: ctx)

    blocked = _BackgroundStatement(engine, "SELECT 1", {})
    try:
        with pytest.raises(RuntimeError, match="failed to start"):
            blocked.__enter__()
        assert blocked._process is not None
        assert blocked.worker_confirmed_stopped, (
            "a process that never actually started must still be reported as confirmed "
            "stopped, via Process.close() rather than terminate()/kill()"
        )
        # Direct proof close() was actually attempted (Phase 5 thirteenth
        # exit review §3, bullet 1), not merely inferred: once close()
        # has run, is_alive() itself raises rather than answering, per
        # multiprocessing.Process's own documented contract.
        with pytest.raises(ValueError, match="process object is closed"):
            blocked._process.is_alive()
    finally:
        _emergency_teardown(blocked, engine)


def test_background_statement_enter_reaps_a_partially_started_process_when_start_raises_after_spawning(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`process.start()` is wrapped so it genuinely spawns the real child
    (via the real, unmocked `start()` implementation) and only then
    raises — simulating a start failure that happens *after* partial (in
    this case, full) initialization, which a real OS-level trigger for
    this is impractical to construct deterministically. Proves __enter__
    detects the live child left behind (via `pid`/`is_alive()`, not by
    assuming a raised `start()` always means nothing was spawned) and
    terminates and reaps it, rather than leaking it (Phase 5 thirteenth
    exit review §3, bullet 2)."""
    engine = postgres_engine
    ctx = multiprocessing.get_context("spawn")
    real_start = ctx.Process.start

    def _start_then_fail(self: Any) -> None:
        real_start(self)
        raise _InjectedFailure("simulated failure after the process was actually spawned")

    monkeypatch.setattr(ctx.Process, "start", _start_then_fail)
    monkeypatch.setattr(multiprocessing, "get_context", lambda method: ctx)

    blocked = _BackgroundStatement(engine, "SELECT 1", {})
    try:
        with pytest.raises(RuntimeError, match="failed to start"):
            blocked.__enter__()
        assert blocked._process is not None
        assert blocked.worker_confirmed_stopped, (
            "the genuinely spawned child must be terminated, reaped, and its Process object "
            "closed, not left alive"
        )
    finally:
        _emergency_teardown(blocked, engine)


def test_background_statement_reports_combined_process_and_ipc_cleanup_failures_during_start_error_cleanup(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`process.start()` genuinely spawns a real, deliberately
    startup-delayed (so it is still alive when cleanup runs) child and
    then raises; the resulting partial-start cleanup's own `terminate()`
    is *also* mocked to fail (the real, unmocked `kill()` still
    succeeds), and one IPC pipe end's `close()` is *also* mocked to
    fail. Proves every one of these co-occurring cleanup failures —
    spanning both the process-focused and IPC-focused halves of
    start-error cleanup — is independently collected and reported, none
    skipped because another failed first, and that the original
    `process.start()` failure remains the primary, unreplaced error
    (Phase 5 fourteenth exit review §2: 'IPC close failure combined with
    one or more process-cleanup failures')."""
    engine = postgres_engine
    ctx = multiprocessing.get_context("spawn")
    real_start = ctx.Process.start
    real_pipe = ctx.Pipe

    def _start_then_fail(self: Any) -> None:
        real_start(self)
        raise _InjectedFailure("simulated failure after the process was actually spawned")

    def _pipe_with_recv_close_failing(duplex: bool = True) -> Any:
        conn1, conn2 = real_pipe(duplex=duplex)
        monkeypatch.setattr(
            conn1, "close", _raise_once_then_succeed("simulated recv-end close failure")
        )
        return conn1, conn2

    monkeypatch.setattr(ctx, "Pipe", _pipe_with_recv_close_failing)
    monkeypatch.setattr(ctx.Process, "start", _start_then_fail)
    monkeypatch.setattr(
        ctx.Process, "terminate", _raise_once_then_succeed("simulated terminate() failure")
    )
    monkeypatch.setattr(multiprocessing, "get_context", lambda method: ctx)

    blocked = _BackgroundStatement(engine, "SELECT 1", {}, _startup_delay_seconds=2.0)
    try:
        with pytest.raises(RuntimeError, match="failed to start") as excinfo:
            blocked.__enter__()
        assert "simulated failure after the process was actually spawned" in str(excinfo.value), (
            "the original process.start() failure must remain the primary error"
        )
        notes = "\n".join(getattr(excinfo.value, "__notes__", []))
        assert "terminate (partial start)" in notes, (
            f"expected the terminate() failure reported, got: {notes!r}"
        )
        assert "handshake_recv" in notes, f"expected an IPC close failure reported, got: {notes!r}"
        assert blocked.worker_confirmed_stopped, (
            "kill() must still have reaped the process despite terminate() failing"
        )
    finally:
        _emergency_teardown(blocked, engine)


def test_background_statement_reports_a_problem_when_the_process_object_fails_to_close_during_start_error_cleanup(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`process.start()` and the constructed `Process` object's own
    `close()` are both mocked to fail — the process never actually
    started, so cleanup takes the direct-close branch, and that close
    itself fails too. Proves the failure is collected and reported rather
    than propagating uncaught or being silently dropped (Phase 5
    thirteenth exit review §3, bullet 3)."""
    engine = postgres_engine
    ctx = multiprocessing.get_context("spawn")
    monkeypatch.setattr(ctx.Process, "start", _raise_injected_failure)
    monkeypatch.setattr(ctx.Process, "close", _raise_once_then_succeed())
    monkeypatch.setattr(multiprocessing, "get_context", lambda method: ctx)

    blocked = _BackgroundStatement(engine, "SELECT 1", {})
    try:
        with pytest.raises(RuntimeError, match="failed to start") as excinfo:
            blocked.__enter__()
        notes = "\n".join(getattr(excinfo.value, "__notes__", []))
        assert "close process object" in notes.lower(), (
            f"expected the process-object close failure to be reported, got: {notes!r}"
        )
    finally:
        _emergency_teardown(blocked, engine)


def test_background_statement_reports_an_ipc_cleanup_failure_during_start_error_cleanup(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`process.start()` fails (mocked) after all three IPC pipes were
    genuinely constructed; one of their ends is made to fail closing
    during the resulting start-error cleanup. Proves that failure is
    collected and reported too, not dropped just because it happened
    during the Process-focused half of start-error cleanup (Phase 5
    thirteenth exit review §3, bullet 4)."""
    engine = postgres_engine
    ctx = multiprocessing.get_context("spawn")
    real_pipe = ctx.Pipe
    calls = {"count": 0}

    def _pipe_with_first_recv_close_failing(duplex: bool = True) -> Any:
        calls["count"] += 1
        conn1, conn2 = real_pipe(duplex=duplex)
        if calls["count"] == 1:
            monkeypatch.setattr(conn1, "close", _raise_once_then_succeed())
        return conn1, conn2

    monkeypatch.setattr(ctx, "Pipe", _pipe_with_first_recv_close_failing)
    monkeypatch.setattr(ctx.Process, "start", _raise_injected_failure)
    monkeypatch.setattr(multiprocessing, "get_context", lambda method: ctx)

    blocked = _BackgroundStatement(engine, "SELECT 1", {})
    try:
        with pytest.raises(RuntimeError, match="failed to start") as excinfo:
            blocked.__enter__()
        notes = "\n".join(getattr(excinfo.value, "__notes__", []))
        assert "handshake_recv" in notes, (
            f"expected the IPC close failure during start-error cleanup to be reported, got: "
            f"{notes!r}"
        )
    finally:
        _emergency_teardown(blocked, engine)


@pytest.mark.parametrize(
    ("expected_label_fragment", "pipe_index", "end_index"),
    [
        ("close handshake_send", 1, 1),
        ("close outcome_send", 2, 1),
        ("close control_recv", 3, 0),
    ],
)
def test_background_statement_reports_a_startup_cleanup_failure_after_a_successful_handshake(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    expected_label_fragment: str,
    pipe_index: int,
    end_index: int,
) -> None:
    """One of the three redundant controller-side pipe-end copies (of the
    ends handed off to the worker, closed immediately after a successful
    `process.start()` since the controller no longer needs them) fails to
    close, even though the handshake and the statement both genuinely
    succeed afterward. Proves that failure is retained rather than
    silently discarded once `__enter__` succeeds (Phase 5 thirteenth exit
    review §4): `__exit__` still reports it."""
    engine = postgres_engine
    ctx = multiprocessing.get_context("spawn")
    real_pipe = ctx.Pipe
    calls = {"count": 0}

    def _pipe(duplex: bool = True) -> Any:
        calls["count"] += 1
        conn1, conn2 = real_pipe(duplex=duplex)
        if calls["count"] == pipe_index:
            target = conn1 if end_index == 0 else conn2
            monkeypatch.setattr(target, "close", _raise_once_then_succeed())
        return conn1, conn2

    monkeypatch.setattr(ctx, "Pipe", _pipe)
    monkeypatch.setattr(multiprocessing, "get_context", lambda method: ctx)

    blocked = _BackgroundStatement(engine, "SELECT 1", {})
    try:
        with (
            pytest.raises(RuntimeError, match="cleanup encountered problems") as excinfo,
            blocked,
        ):
            status, exc = blocked.resume_and_get_outcome("startup-cleanup-failure probe")
            assert status == "committed" and exc is None, (
                "the handshake and statement must genuinely succeed despite the injected "
                "close failure"
            )

        assert expected_label_fragment in str(excinfo.value)
    finally:
        _emergency_teardown(blocked, engine)


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

    try:
        with pytest.raises(_SentinelFailure), blocked:
            monkeypatch.setattr(blocked._process, "terminate", lambda: None)
            raise _SentinelFailure("deliberate failure with terminate() mocked to a no-op")

        assert blocked.worker_confirmed_stopped, "kill() must still have stopped the process"
    finally:
        _emergency_teardown(blocked, engine)


def test_background_statement_reports_a_problem_when_an_ipc_channel_fails_to_close(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One IPC channel's close() is mocked to fail after a fast, successful
    statement. Proves the failure is collected as a problem — reported by
    __exit__ — rather than propagating uncaught, and that cleanup for the
    other channels and the process object still proceeds regardless."""
    engine = postgres_engine
    captured: list[_BackgroundStatement] = []

    def _run() -> None:
        with _BackgroundStatement(engine, "SELECT 1", {}) as blocked:
            captured.append(blocked)
            blocked.resume_and_get_outcome("IPC-channel-close-failure probe")
            monkeypatch.setattr(blocked._outcome_recv, "close", _raise_once_then_succeed())

    try:
        with pytest.raises(RuntimeError, match="close outcome_recv"):
            _run()
    finally:
        if captured:
            _emergency_teardown(captured[0], engine)


def test_background_statement_reports_a_problem_when_the_process_object_fails_to_close(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Process object's own close() is mocked to fail after a fast,
    successful statement. Proves the failure is collected and reported by
    __exit__ rather than propagating uncaught."""
    engine = postgres_engine
    captured: list[_BackgroundStatement] = []

    def _run() -> None:
        with _BackgroundStatement(engine, "SELECT 1", {}) as blocked:
            captured.append(blocked)
            blocked.resume_and_get_outcome("process-close-failure probe")
            monkeypatch.setattr(blocked._process, "close", _raise_once_then_succeed())

    try:
        with pytest.raises(RuntimeError, match="close process object"):
            _run()
    finally:
        if captured:
            _emergency_teardown(captured[0], engine)


@pytest.mark.parametrize("failing_call_number", [2, 3])
def test_background_statement_enter_reports_partial_ipc_construction_failure(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch, failing_call_number: int
) -> None:
    """__enter__ makes three Pipe() calls (handshake, outcome, control).
    The second or third is made to fail after the earlier one(s) genuinely
    succeed — a real OS-level trigger for a Pipe() call failing is
    impractical to construct deterministically, so this substitutes fake
    connections instead. Proves every already-created pipe's ends are
    actually closed (not leaked) — visible here as their own reported
    close failures, since these fakes fail to close too — and that no
    process is ever constructed (Phase 5 twelfth exit review §4)."""
    engine = postgres_engine
    ctx = multiprocessing.get_context("spawn")
    calls = {"count": 0}
    created: list[_FakeConnection] = []

    def _flaky_pipe(duplex: bool = True) -> Any:
        calls["count"] += 1
        if calls["count"] == failing_call_number:
            raise _InjectedFailure(
                f"simulated Pipe() failure on IPC resource #{failing_call_number}"
            )
        conn1 = _FakeConnection(f"pipe{calls['count']}-recv")
        conn2 = _FakeConnection(f"pipe{calls['count']}-send")
        created.extend([conn1, conn2])
        return conn1, conn2

    monkeypatch.setattr(ctx, "Pipe", _flaky_pipe)
    monkeypatch.setattr(multiprocessing, "get_context", lambda method: ctx)

    blocked = _BackgroundStatement(engine, "SELECT 1", {})
    try:
        with pytest.raises(
            RuntimeError, match="failed to construct the background worker's IPC"
        ) as excinfo:
            blocked.__enter__()

        assert blocked._process is None
        assert created, "expected at least the first pipe to have been created before the failure"
        assert all(conn.closed for conn in created), (
            "every already-created pipe's ends must be closed on cleanup, not leaked"
        )
        notes = "\n".join(getattr(excinfo.value, "__notes__", []))
        assert "handshake_recv" in notes and "handshake_send" in notes, (
            f"expected the first pipe's close failures to be reported, got: {notes!r}"
        )
        if failing_call_number == 3:
            assert "outcome_recv" in notes and "outcome_send" in notes, (
                f"expected the second pipe's close failures to also be reported, got: {notes!r}"
            )
    finally:
        _emergency_teardown(blocked, engine)


def test_background_statement_leaves_no_queue_feeder_thread_behind(postgres_engine: Engine) -> None:
    """The Pipe-based IPC redesign (Phase 5 twelfth exit review §4) has no
    background feeder thread at all — unlike multiprocessing.Queue, whose
    feeder thread was the abandonable resource the earlier
    _bounded_join_thread design could only bound, never guarantee gone.
    Proves no QueueFeederThread exists after a normal run, positively
    confirming the mechanism that made that whole class of bug possible is
    no longer present."""
    engine = postgres_engine
    blocked = _BackgroundStatement(engine, "SELECT 1", {})
    try:
        with blocked:
            blocked.resume_and_get_outcome("feeder-thread probe")

        feeder_threads = [t for t in threading.enumerate() if "QueueFeederThread" in t.name]
        assert feeder_threads == [], f"unexpected queue feeder threads survived: {feeder_threads}"
    finally:
        _emergency_teardown(blocked, engine)


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
    blocked: _BackgroundStatement | None = None
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

            blocked = _BackgroundStatement(
                engine,
                "UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e",
                {"t": region_type, "e": dungeon},
            )
            with blocked:
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
        # _emergency_teardown is a genuinely independent backstop, not
        # proof of __exit__'s own correctness (that is what this test's
        # assertions above already establish) — see Phase 5 thirteenth
        # exit review §5.
        if blocked is not None:
            _emergency_teardown(blocked, engine)
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
    blocked: _BackgroundStatement | None = None
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

            blocked = _BackgroundStatement(
                engine,
                "INSERT INTO world.dungeon_areas (dungeon_area_id) VALUES (:a)",
                {"a": area},
            )
            with blocked:
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
        if blocked is not None:
            _emergency_teardown(blocked, engine)
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
    blocked: _BackgroundStatement | None = None
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

            blocked = _BackgroundStatement(
                engine,
                "UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e",
                {"t": region_type, "e": new_dungeon},
            )
            with blocked:
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
        if blocked is not None:
            _emergency_teardown(blocked, engine)
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
    blocked: _BackgroundStatement | None = None
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

            blocked = _BackgroundStatement(
                engine,
                "UPDATE world.locations SET parent_location_id = NULL WHERE location_id = :a",
                {"a": area},
            )
            with blocked:
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
        if blocked is not None:
            _emergency_teardown(blocked, engine)
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
    blocked: _BackgroundStatement | None = None
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

            blocked = _BackgroundStatement(
                engine,
                "INSERT INTO world.dungeon_areas (dungeon_area_id) VALUES (:a)",
                {"a": area},
            )
            with blocked:
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
        if blocked is not None:
            _emergency_teardown(blocked, engine)
        _cleanup_world(engine, slug)
