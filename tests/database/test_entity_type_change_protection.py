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
import threading
import time
import uuid
from collections.abc import Callable

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
# test below now meets: keep the second statement genuinely alive on its own
# thread while the first transaction commits, confirm via pg_stat_activity
# that it was truly waiting on a lock (not merely slow), join the thread and
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


class _BackgroundStatement:
    """Runs `statement(connection)` on its own connection in a background
    thread, inside an explicit transaction committed on success or rolled
    back on failure.

    Ownership is established synchronously, in the calling thread, before
    any worker thread exists: `__enter__` connects through a private,
    single-use engine (a driver-level `connect_timeout` bounds that connect
    attempt), begins the transaction, sets a bounded `lock_timeout` on it
    (see below), and records the real backend pid — all before starting the
    thread that actually runs `statement`. If any of that fails, `__enter__`
    raises directly and no thread is ever created; there is no interval
    during which a worker of unknown or unowned state could outlive a failed
    context entry, because the entry and the worker's existence are no
    longer racing each other at all.

    `__exit__` guarantees that by the time it returns or raises, the worker
    thread is provably no longer running, via a layered, entirely
    self-contained fallback (nothing here depends on a caller supplying an
    unblock action):

    1. `pg_terminate_backend()`, then `pg_cancel_backend()` — both issued
       through the isolated `_send_signal()` seam, which regression tests
       monkeypatch to inject a false result or a raised exception, proving
       the fallback chain below without ever touching the real, private,
       immutable backend pid this class actually depends on.
    2. Driver-native cancellation via `_cancel_via_driver()` — psycopg's
       `Connection.cancel_safe()`, called directly on the worker's own
       connection handle. This is a resource the helper genuinely owns
       (unlike the SQL signals above, it needs no second connection and no
       privilege to signal an arbitrary pid), and psycopg documents it as
       safe to call from another thread while the connection is busy with a
       blocking operation — confirmed empirically against a genuinely
       blocked worker before relying on it here.
    3. The `lock_timeout` set during `__enter__` — a deterministic backstop
       enforced by PostgreSQL itself, entirely independent of every
       mechanism above and of anything this thread does or fails to do.
       Once a lock-waiting statement has been running longer than that
       bound, PostgreSQL cancels it unconditionally; `__exit__` simply waits
       out that bound (plus margin) rather than taking any further action.
       A statement that is not lock-bound at all (`pg_sleep`, exercised by
       the regression tests below rather than any production statement)
       is the one case this backstop cannot reach — proving that `__exit__`
       still reports rather than hangs or silently returns in that case is
       exactly what those tests are for.

    Each step is followed by a bounded join verifying the worker actually
    stopped, not just that a signal was sent or accepted. Cleanup failures
    are never silently discarded: if an exception was already propagating
    out of the `with` block, the cleanup failure is attached to it via
    `add_note` so the original failure remains the reported cause; if
    nothing was already propagating, the cleanup failure is raised directly
    and becomes the `with` block's failure.
    """

    _CONNECT_TIMEOUT_SECONDS = 3
    _SIGNAL_JOIN_SECONDS = 5.0

    def __init__(
        self,
        engine: Engine,
        statement: Callable[[Connection], None],
        *,
        lock_timeout_seconds: float = 8.0,
    ) -> None:
        self._engine = engine
        self._statement = statement
        self._lock_timeout_seconds = lock_timeout_seconds
        self.outcome: list[tuple[str, Exception | None]] = []
        self._backend_pid_value: int | None = None
        self._connection: Connection | None = None
        self._worker_engine: Engine | None = None
        self._thread: threading.Thread | None = None

    @property
    def backend_pid(self) -> int:
        """The worker's real backend pid — private storage, read-only
        exposure. There is deliberately no way for a caller to overwrite
        this: PHASE5_REMAINING_ISSUES.md's ninth review rejected the earlier
        pattern of tests corrupting a mutable recorded pid to simulate
        signaling failure, since that tested the *caller* breaking an
        ownership contract, not the helper's own containment. Regression
        tests inject failures at the signaling operations themselves
        (`_send_signal`, `_cancel_via_driver`) instead."""
        assert self._backend_pid_value is not None, "backend_pid read before __enter__ completed"
        return self._backend_pid_value

    def _establish_connection(self) -> tuple[Engine, Connection, int]:
        """Synchronously connects, begins the transaction, sets the
        deterministic `lock_timeout` backstop, and reads the real backend
        pid — everything a worker thread needs to safely own before it can
        be started. Isolated as its own method (rather than inlined in
        `__enter__`) so regression tests can monkeypatch *this* seam to
        simulate a slow-then-failing startup deterministically, without
        depending on real network timing/topology."""
        worker_engine = create_engine(
            self._engine.url,
            connect_args={"connect_timeout": self._CONNECT_TIMEOUT_SECONDS},
        )
        try:
            connection = worker_engine.connect()
            connection.begin()
            # SET/SET LOCAL do not accept a bind parameter for their value —
            # PostgreSQL requires a literal there. Safe to interpolate: this
            # is a float this class itself controls, never external input.
            connection.execute(text(f"SET LOCAL lock_timeout = '{self._lock_timeout_seconds}s'"))
            pid = connection.execute(text("SELECT pg_backend_pid()")).scalar()
        except Exception:
            with contextlib.suppress(Exception):
                worker_engine.dispose()
            raise
        return worker_engine, connection, pid

    def __enter__(self) -> "_BackgroundStatement":
        # No thread exists yet, and none is created below unless this
        # succeeds — a `with` block can therefore never be entered with a
        # worker of unknown or unowned state, by construction rather than
        # by racing a startup deadline against a poll loop.
        self._worker_engine, self._connection, self._backend_pid_value = (
            self._establish_connection()
        )
        self._thread = threading.Thread(target=self._run)
        self._thread.start()
        return self

    def _run(self) -> None:
        connection = self._connection
        worker_engine = self._worker_engine
        assert connection is not None
        try:
            self._statement(connection)
        except Exception as exc:  # noqa: BLE001 - reported via self.outcome, not swallowed
            # This connection may have been externally terminated or
            # canceled by __exit__'s cleanup, or the statement may simply
            # have been rejected by a trigger while the connection itself
            # stays healthy — either way, invalidate rather than pool it.
            # Some server-side disconnect conditions (e.g. psycopg's
            # AdminShutdown, raised by pg_terminate_backend) are not always
            # recognized by SQLAlchemy's own disconnect detection, so
            # relying on plain close() risked silently handing a dead
            # connection to a later, unrelated test.
            with contextlib.suppress(Exception):
                connection.invalidate()
            self.outcome.append(("failed", exc))
        else:
            connection.commit()
            self.outcome.append(("committed", None))
        finally:
            with contextlib.suppress(Exception):
                connection.close()
            if worker_engine is not None:
                with contextlib.suppress(Exception):
                    worker_engine.dispose()

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

    def resume_and_get_outcome(self, label: str) -> tuple[str, Exception | None]:
        """Joins the thread (bounded) after the blocker has committed and
        asserts the original waiting statement actually resumed — not a
        substitute retry — then returns its real outcome."""
        assert self._thread is not None
        self._thread.join(timeout=10.0)
        assert not self._thread.is_alive(), (
            f"{label} did not resume within 10s of the blocking transaction's commit"
        )
        assert self.outcome, f"{label} thread reported no outcome"
        return self.outcome[0]

    def _send_signal(self, description: str, sql: str) -> bool:
        """Issues one termination/cancellation SQL signal against the
        tracked (real, immutable) backend pid, via a separate connection.
        Isolated as its own method, not inlined into `_force_stop`, so
        regression tests can monkeypatch this exact seam to inject a false
        result or a raised exception — exercising the fallback chain
        without corrupting `backend_pid` or targeting the wrong backend."""
        canceller = self._engine.connect()
        try:
            sent = canceller.execute(text(sql), {"p": self.backend_pid}).scalar()
            canceller.commit()
            return bool(sent)
        finally:
            with contextlib.suppress(Exception):
                canceller.close()

    def _cancel_via_driver(self) -> None:
        """Driver-native cancellation on the worker's own connection handle
        (psycopg's `Connection.cancel_safe()`) — a resource this helper
        genuinely owns, independent of the SQL-signal path above. Isolated
        as its own method so regression tests can monkeypatch it to inject
        a failure and prove the next fallback layer (the `lock_timeout`
        backstop) takes over."""
        assert self._connection is not None
        dbapi_connection = self._connection.connection.dbapi_connection
        dbapi_connection.cancel_safe(timeout=self._SIGNAL_JOIN_SECONDS)

    def _force_stop(self) -> Exception | None:
        """Layered, verified attempt to make the worker's backend stop —
        see the class docstring for the three-step fallback chain. Returns
        None only once a bounded join has confirmed the thread actually
        stopped; otherwise returns an Exception describing every attempt
        made, including the final `lock_timeout` backstop's own bound."""
        assert self._thread is not None
        attempts: list[str] = []

        for description, sql in (
            ("pg_terminate_backend", "SELECT pg_terminate_backend(:p)"),
            ("pg_cancel_backend", "SELECT pg_cancel_backend(:p)"),
        ):
            try:
                sent = self._send_signal(description, sql)
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                attempts.append(f"{description} raised {type(exc).__name__}: {exc}")
                continue
            if not sent:
                attempts.append(
                    f"{description} reported failure (no signalable backend {self.backend_pid})"
                )
                continue
            self._thread.join(timeout=self._SIGNAL_JOIN_SECONDS)
            if not self._thread.is_alive():
                return None
            attempts.append(f"{description} signal accepted but worker did not stop within 5s")

        try:
            self._cancel_via_driver()
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            attempts.append(f"driver-native cancel_safe raised {type(exc).__name__}: {exc}")
        else:
            self._thread.join(timeout=self._SIGNAL_JOIN_SECONDS)
            if not self._thread.is_alive():
                return None
            attempts.append("driver-native cancel_safe accepted but worker did not stop within 5s")

        # Deterministic backstop: the worker's own transaction was
        # configured with a bounded lock_timeout during __enter__, before it
        # could block on anything, so PostgreSQL itself guarantees a
        # lock-waiting statement cannot wait longer than that — independent
        # of every mechanism above. Wait out that bound (plus margin) before
        # concluding cleanup genuinely failed. This cannot rescue a
        # statement that was never waiting on a lock in the first place
        # (pg_sleep, used only by the regression tests proving this exact
        # limitation) — that is the one case where this method is expected
        # to return a real failure.
        backstop_wait = self._lock_timeout_seconds + self._SIGNAL_JOIN_SECONDS
        self._thread.join(timeout=backstop_wait)
        if not self._thread.is_alive():
            return None
        attempts.append(
            f"worker did not stop even after its {self._lock_timeout_seconds}s lock_timeout "
            "backstop elapsed — it was not blocked on anything lock_timeout governs"
        )

        return RuntimeError(
            f"could not verify backend pid {self.backend_pid} was stopped: " + "; ".join(attempts)
        )

    def __exit__(self, exc_type: object, exc: BaseException | None, tb: object) -> bool:
        cleanup_error: Exception | None = None
        if self._thread is not None and self._thread.is_alive():
            cleanup_error = self._force_stop()
        if cleanup_error is None and self._thread is not None and self._thread.is_alive():
            # Independent final proof point, regardless of what _force_stop
            # believed happened above.
            cleanup_error = RuntimeError(
                "background worker thread is still alive after forced cleanup — a "
                "connection, transaction, or advisory lock may have survived the with block"
            )
        if cleanup_error is None:
            return False
        if exc is not None:
            exc.add_note(f"_BackgroundStatement cleanup also failed: {cleanup_error}")
            return False
        raise cleanup_error


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


class _InjectedFailure(Exception):
    """Marks a deliberately mocked failure in one of `_BackgroundStatement`'s
    fallback seams (`_send_signal`, `_cancel_via_driver`,
    `_establish_connection`), distinguishing it from a genuine PostgreSQL or
    driver error. PHASE5_REMAINING_ISSUES.md's ninth review rejected the
    earlier pattern of corrupting `backend_pid` to simulate signaling
    failure — that tested a caller breaking an ownership contract, not the
    helper's own containment. These tests inject failures at the mechanisms
    themselves instead, leaving `backend_pid` untouched and correct."""


def _lock_statement(key: int) -> Callable[[Connection], None]:
    def _acquire(conn: Connection) -> None:
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})

    return _acquire


def _sleep_statement(seconds: float) -> Callable[[Connection], None]:
    """A statement that blocks for a fixed duration without waiting on any
    lock — used only by the two tests proving `_force_stop`'s final
    reporting path, since the `lock_timeout` backstop every other
    regression test relies on has no effect on a plain sleep."""

    def _sleep(conn: Connection) -> None:
        conn.execute(text("SELECT pg_sleep(:s)"), {"s": seconds})

    return _sleep


def _failing_send_signal(mode: str) -> Callable[[str, str], bool]:
    """A `_send_signal` replacement for monkeypatching onto one instance:
    fails every signal attempt, either by returning `False`
    (`mode="returns_false"`) or by raising (`mode="raises"`) — the two
    failure shapes the ninth review asks be covered for both
    `pg_terminate_backend` and `pg_cancel_backend`."""

    def _send(description: str, sql: str) -> bool:
        if mode == "raises":
            raise _InjectedFailure(f"simulated {description} failure")
        return False

    return _send


def _failing_cancel_via_driver() -> None:
    """A `_cancel_via_driver` replacement for monkeypatching: simulates the
    driver-native cancellation itself failing, so whatever comes after it
    (the `lock_timeout` backstop, or — for the two `pg_sleep`-based tests —
    nothing) is what has to take over."""
    raise _InjectedFailure("simulated cancel_safe failure")


def _assert_backend_eventually_gone(engine: Engine, pid: int, timeout: float = 5.0) -> None:
    """Polls pg_stat_activity from a fresh, independent connection until the
    given backend pid disappears — proof its connection, transaction, and
    any advisory lock it held are actually gone, not merely that a Python
    thread stopped waiting on it. A fresh connection matters because a
    session that itself still holds the lock the pid was queued as a
    *waiter* on can keep reporting that waiter as present in its own view
    of pg_stat_activity until it releases the lock, even though the waiter
    is already fully gone from every other connection's point of view."""
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
                _BackgroundStatement(engine, _lock_statement(lock_key)) as blocked,
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
    seam — `backend_pid` itself is never touched, so this proves the
    fallback chain rather than a caller breaking the tracking contract. The
    real, unmocked driver-native `cancel_safe()` must then take over and
    stop the genuinely blocked worker."""
    engine = postgres_engine
    lock_key = uuid.uuid4().int % (2**63 - 1)

    with engine.connect() as first:
        first.begin()
        first.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key})

        blocked = _BackgroundStatement(engine, _lock_statement(lock_key))
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
    `cancel_safe()` — is mocked to fail, proving the one entirely passive
    layer still works: the `lock_timeout` PostgreSQL itself enforces on the
    worker's own transaction, configured during `__enter__` before the
    worker could block on anything. A short `lock_timeout` keeps this test
    fast while still proving the mechanism deterministically, not by luck —
    PostgreSQL guarantees the cancellation, not a race against it."""
    engine = postgres_engine
    lock_key = uuid.uuid4().int % (2**63 - 1)

    with engine.connect() as first:
        first.begin()
        first.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key})

        blocked = _BackgroundStatement(engine, _lock_statement(lock_key), lock_timeout_seconds=2.0)
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


def test_background_statement_reports_cleanup_failure_without_losing_the_original_exception(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one case `_force_stop` cannot rescue: every active mechanism
    mocked to fail, and the worker is not waiting on a lock at all
    (`pg_sleep`, not `pg_advisory_xact_lock`), so the `lock_timeout`
    backstop every other regression test relies on has nothing to cancel.
    Proves `__exit__` still reports the cleanup failure — via `add_note` —
    rather than hanging or silently returning, and that the with block's
    own sentinel failure remains the primary, reported cause."""
    engine = postgres_engine
    # Longer than _force_stop's own bounded backstop wait
    # (lock_timeout_seconds + _SIGNAL_JOIN_SECONDS = 1.0 + 5.0 = 6.0s), so
    # the worker is still genuinely running when _force_stop gives up and
    # reports failure, but short enough to keep this test's own
    # wait-for-natural-completion bounded afterward.
    sleep_seconds = 9.0
    blocked = _BackgroundStatement(
        engine, _sleep_statement(sleep_seconds), lock_timeout_seconds=1.0
    )
    monkeypatch.setattr(blocked, "_send_signal", _failing_send_signal("raises"))
    monkeypatch.setattr(blocked, "_cancel_via_driver", _failing_cancel_via_driver)

    with pytest.raises(_SentinelFailure) as excinfo, blocked:
        # No wait_until_blocked here: pg_sleep never reports wait_event_type
        # 'Lock' in pg_stat_activity, so there is nothing to poll for — the
        # worker starts sleeping essentially immediately after __enter__
        # returns (which itself only returns once the connection, its
        # lock_timeout, and its backend pid are all established).
        raise _SentinelFailure("deliberate failure while nothing can stop the worker early")

    assert isinstance(excinfo.value, _SentinelFailure), (
        "the original sentinel failure must still be what propagates"
    )
    notes = "\n".join(getattr(excinfo.value, "__notes__", []))
    assert "cleanup" in notes.lower() and "fail" in notes.lower(), (
        f"expected the cleanup failure to be reported on the propagated exception via "
        f"add_note, got notes: {notes!r}"
    )

    # The worker is still genuinely sleeping at this point — only
    # _force_stop's own bounded backstop elapsed above, not the full
    # pg_sleep duration. This is the one scenario in the whole suite where
    # nothing inside _BackgroundStatement itself can end the worker early;
    # wait for it to finish naturally and confirm no thread survives test
    # teardown.
    assert blocked._thread is not None
    blocked._thread.join(timeout=sleep_seconds)
    assert not blocked._thread.is_alive(), (
        "the worker must finish on its own once pg_sleep's fixed duration elapses, even "
        "though nothing could stop it early"
    )


def test_background_statement_cleanup_failure_fails_the_test_when_no_original_exception(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same fault injection as above, but the with block exits normally —
    no exception of its own — while nothing can stop the worker early.
    `__exit__` itself must raise, since there is no already-propagating
    exception for it to attach the cleanup failure to."""
    engine = postgres_engine
    sleep_seconds = 9.0
    blocked = _BackgroundStatement(
        engine, _sleep_statement(sleep_seconds), lock_timeout_seconds=1.0
    )
    monkeypatch.setattr(blocked, "_send_signal", _failing_send_signal("returns_false"))
    monkeypatch.setattr(blocked, "_cancel_via_driver", _failing_cancel_via_driver)

    with pytest.raises(RuntimeError, match="could not verify"), blocked:
        pass  # No exception here: __exit__ not raising is the only way this test can fail.

    assert blocked._thread is not None
    blocked._thread.join(timeout=sleep_seconds)
    assert not blocked._thread.is_alive(), (
        "the worker must finish on its own once pg_sleep's fixed duration elapses"
    )


def test_background_statement_enter_fails_predictably_when_startup_is_slow_and_never_starts_a_worker(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PHASE5_REMAINING_ISSUES.md's ninth review: proves the slow/stalled
    startup branch the review found, deterministically — not by depending on
    real network timing/topology (flaky across environments), but by
    mocking `_establish_connection` to genuinely take measurable wall-clock
    time before failing. Because ownership (connection, `lock_timeout`,
    backend pid) is now established synchronously before any worker thread
    is created, `__enter__` raising here can never leave a thread behind —
    there is no thread object to check, since none was ever constructed."""
    attempt = _BackgroundStatement(postgres_engine, _lock_statement(1))

    def slow_failing_establish() -> tuple[Engine, Connection, int]:
        time.sleep(0.5)
        raise _InjectedFailure("simulated slow, then failed, connection attempt")

    monkeypatch.setattr(attempt, "_establish_connection", slow_failing_establish)

    start = time.monotonic()
    with pytest.raises(_InjectedFailure, match="simulated slow"):
        attempt.__enter__()
    elapsed = time.monotonic() - start

    assert elapsed >= 0.5, "the simulated startup delay must have genuinely elapsed"
    assert elapsed < 5.0, "startup failure must be reported within a bounded interval"
    assert attempt._thread is None, (
        "no worker thread may be created before ownership is established"
    )


def test_background_statement_enter_fails_with_no_thread_when_a_real_connection_is_refused(
    postgres_engine: Engine,
) -> None:
    """Complements the mocked slow-startup test above with a real (not
    mocked) connection failure — a local port nothing listens on, not a
    genuinely stalled one, which would depend on network topology the test
    process doesn't control. Proves the real `_establish_connection` path
    still leaves `__enter__` raising with no thread and no connection ever
    recorded, whatever the exact underlying driver error looks like on the
    platform running the test."""
    unreachable_engine = create_engine(postgres_engine.url.set(host="127.0.0.1", port=1))
    attempt = _BackgroundStatement(unreachable_engine, _lock_statement(1))

    with pytest.raises(Exception):  # noqa: B017 - the exact driver error varies by platform
        attempt.__enter__()

    assert attempt._thread is None, (
        "no worker thread may be created before ownership is established"
    )
    assert attempt._connection is None, "no connection may be recorded when startup failed"


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

        def retype(conn: Connection) -> None:
            conn.execute(
                text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
                {"t": region_type, "e": dungeon},
            )

        with engine.connect() as first:
            first.begin()

            # Transaction 1: insert the subtype row. Still uncommitted.
            first.execute(
                text("INSERT INTO world.dungeons (dungeon_id) VALUES (:d)"), {"d": dungeon}
            )

            with _BackgroundStatement(engine, retype) as blocked:
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

        def insert_area(conn: Connection) -> None:
            conn.execute(
                text("INSERT INTO world.dungeon_areas (dungeon_area_id) VALUES (:a)"),
                {"a": area},
            )

        with engine.connect() as first:
            first.begin()

            # Transaction 1: remove the marker, then retype the dungeon
            # away. Still uncommitted.
            first.execute(text("DELETE FROM world.dungeons WHERE dungeon_id = :d"), {"d": dungeon})
            first.execute(
                text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
                {"t": region_type, "e": dungeon},
            )

            with _BackgroundStatement(engine, insert_area) as blocked:
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

        def retype(conn: Connection) -> None:
            conn.execute(
                text("UPDATE core.entities SET entity_type_id = :t WHERE entity_id = :e"),
                {"t": region_type, "e": new_dungeon},
            )

        with engine.connect() as first:
            first.begin()

            # Transaction 1: reparent the area under new_dungeon. Still
            # uncommitted.
            first.execute(
                text("UPDATE world.locations SET parent_location_id = :d WHERE location_id = :a"),
                {"d": new_dungeon, "a": area},
            )

            with _BackgroundStatement(engine, retype) as blocked:
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

        def clear_parent(conn: Connection) -> None:
            conn.execute(
                text("UPDATE world.locations SET parent_location_id = NULL WHERE location_id = :a"),
                {"a": area},
            )

        with engine.connect() as first:
            first.begin()

            # Transaction 1: insert the pending dungeon_area row. Still
            # uncommitted.
            first.execute(
                text("INSERT INTO world.dungeon_areas (dungeon_area_id) VALUES (:a)"), {"a": area}
            )

            with _BackgroundStatement(engine, clear_parent) as blocked:
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

        def insert_area(conn: Connection) -> None:
            conn.execute(
                text("INSERT INTO world.dungeon_areas (dungeon_area_id) VALUES (:a)"),
                {"a": area},
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

            with _BackgroundStatement(engine, insert_area) as blocked:
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
