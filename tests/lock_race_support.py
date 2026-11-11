"""A context manager for deterministic lock-race tests against real PostgreSQL.

    with LockRace(engine) as race:
        pause = race.pause(thread_name="add", pattern=...)
        add = race.start("add", operation)
        pause.wait_reached(add)
        other = race.start("other", other_operation)
        race.wait_blocked_by(pause, other)
        pause.release()
        race.join_all()

It is used *inside* the test body, so it exits before pytest begins any fixture teardown, whatever
order the fixtures were requested in. On exit, success or failure, in this order:

1. every pause the test did not release is put into abort mode and released (the paused worker
   raises inside its own transaction and rolls back, so no half scenario commits);
2. every held transaction is rolled back and closed;
3. every worker is joined, each bounded by `WAIT_SECONDS`;
4. a worker still alive gets `pg_cancel_backend`, then `pg_terminate_backend`, on its own recorded
   backend pid (never on another session), and is joined again;
5. the listener is removed.

If the body raised, that exception propagates unchanged and any cleanup problem is attached to it
as a note. If the body passed but a pause was left unreleased, or a worker had to be cancelled or
never finished, the exit raises `AssertionError`: a passing scenario with a stuck worker is a
failure. Waits are observed through `pg_blocking_pids` (the intended session, followed along the
queue of waiters); a worker that finishes before blocking is reported as it ended instead of
waiting out the clock. Nothing here lengthens a timeout.
"""

import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any

from sqlalchemy import Connection, Engine, event, text

WAIT_SECONDS = 15.0
STALL_SECONDS = 1.0
MAX_STALL_CREDIT_SECONDS = 120.0


class Budget:
    """A wait budget of `seconds` that is not charged for a long gap between two of its own polls.

    A polling wait asks `expired()` once per iteration, roughly every 20 to 100 ms. What this class
    *measures* is the gap between two asks. A gap longer than `STALL_SECONDS` is *inferred* to be the
    whole process not running (a collection pause, paging under memory pressure, a suspended
    machine): it cannot be told apart from one slow poll, but the inference is the one the observed
    failure supports, since the request being waited for runs in the same process and was stopped
    with the waiter. Charging that time would end the wait the instant the process resumes, before
    the request has been scheduled. The gap is added to the deadline and reported in `note()`.

    The credit is bounded, so slow polls cannot extend a wait indefinitely: the total added to the
    deadline never exceeds `MAX_STALL_CREDIT_SECONDS` (default 120 s), and gaps beyond that are
    counted against the budget as ordinary time. A request hung in a process that keeps running
    (gaps of tens of milliseconds) is never credited and expires at `seconds`; a poll that is slow
    for a reason of its own (a slow database query) is credited at most that cap in total, and the
    wait then expires normally.

    Observed 2026-11 under three concurrent full runs: a 44 second gap right after a hold was
    taken, then the wait failing the moment the process resumed, with the request's first statement
    beginning at that same instant (see docs/PHASE14_15_P03A_IMPLEMENTATION_PLAN)."""

    def __init__(
        self,
        seconds: float,
        clock: Callable[[], float] = time.monotonic,
        max_credit: float = MAX_STALL_CREDIT_SECONDS,
    ) -> None:
        self._clock = clock
        self._last = clock()
        self._max_credit = max_credit
        self.deadline = self._last + seconds
        self.stalled = 0.0  # polling-gap time credited to the deadline

    def expired(self) -> bool:
        now = self._clock()
        gap = now - self._last
        self._last = now
        if gap > STALL_SECONDS:
            credit = min(gap, self._max_credit - self.stalled)
            self.deadline += credit
            self.stalled += credit
        return now >= self.deadline

    def note(self) -> str:
        if not self.stalled:
            return ""
        return (
            f" (the poll did not run for {self.stalled:.1f}s of it; "
            "taken to be the process not running, and not charged to the wait)"
        )


class _Aborted(BaseException):
    """Raised inside a paused worker whose pause was never released by the test."""


@dataclass
class Worker:
    """A command running in its own transaction on its own named thread; it commits on success."""

    name: str
    thread: threading.Thread = field(default_factory=threading.Thread)
    result: object = None
    error: BaseException | None = None
    pid: int | None = None
    finished: threading.Event = field(default_factory=threading.Event)

    @property
    def done(self) -> bool:
        return self.finished.is_set()

    def describe(self) -> str:
        result: object = self.result
        status = getattr(result, "status_code", None)
        if status is not None:  # an HTTP response: say what it was, not its repr
            result = f"HTTP {status} {getattr(result, 'text', '')}"
        return f"{self.name} finished with result={result!r} error={self.error!r}"


class Hold:
    """An uncommitted transaction on its own connection, with its backend pid. `commit` ends it;
    otherwise the race rolls it back on exit."""

    def __init__(self, engine: Engine) -> None:
        self.connection = engine.connect()
        self.transaction = self.connection.begin()
        driver = self.connection.connection.driver_connection
        self.pid: int = driver.info.backend_pid  # type: ignore[union-attr]
        self.ended = False

    def commit(self) -> None:
        self.transaction.commit()
        self.ended = True

    def close(self) -> None:
        if not self.ended and self.transaction.is_active:
            self.transaction.rollback()
        self.ended = True
        self.connection.close()


class Pause:
    """Holds the named thread just before it executes the first statement matching `pattern`
    (after `after` has been seen, when given), with whatever locks it holds by then."""

    def __init__(
        self, race: "LockRace", *, thread_name: str, pattern: str, after: str | None = None
    ) -> None:
        self.race = race
        self.thread_name = thread_name
        self.pattern = re.compile(pattern)
        self.after = re.compile(after) if after is not None else None
        self.reached = threading.Event()
        self.resume = threading.Event()
        self.aborted = False
        self.released_by_test = False
        self.pid = 0
        self._seen_after = after is None
        self._fired = False

    def _maybe_pause(self, connection: Connection, flat: str) -> None:
        if self._fired:
            return
        if not self._seen_after:
            assert self.after is not None
            self._seen_after = bool(self.after.search(flat))
            return
        if self.pattern.search(flat):
            self._fired = True
            self.pid = connection.connection.driver_connection.info.backend_pid  # type: ignore[union-attr]
            self.reached.set()
            if not self.resume.wait(WAIT_SECONDS) or self.aborted:
                raise _Aborted(f"pause on {self.thread_name} was never released by the test")

    def wait_reached(self, worker: Worker) -> None:
        """Waits until the paused thread is at the pause point; a worker that ended first is
        reported as it ended."""
        budget = Budget(WAIT_SECONDS)
        while not budget.expired():
            if self.reached.wait(0.02):
                return
            if worker.done:
                raise AssertionError(f"ended before the pause point: {worker.describe()}")
        if self.reached.is_set():  # the last look is after expiry, as in the other waits
            return
        if worker.done:
            raise AssertionError(f"ended before the pause point: {worker.describe()}")
        raise AssertionError(
            f"{worker.name} never reached the pause point{budget.note()}; waiting sessions: "
            f"{self.race.waiting_sessions()}"
        )

    def release(self) -> None:
        self.released_by_test = True
        self.resume.set()


class LockRace:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.workers: list[Worker] = []
        self.pauses: list[Pause] = []
        self.holds: list[Hold] = []
        self._by_thread: dict[str, Worker] = {}
        event.listen(engine, "before_cursor_execute", self._hook)
        self._listening = True

    # -- the listener ---------------------------------------------------------------------------

    def _hook(
        self,
        conn: Connection,
        cursor: Any,
        statement: Any,
        parameters: Any,
        context: Any,
        executemany: Any,
    ) -> None:
        worker = self._by_thread.get(threading.current_thread().name)
        if worker is None:
            return
        if worker.pid is None:
            worker.pid = conn.connection.driver_connection.info.backend_pid  # type: ignore[union-attr]
        flat = " ".join(str(statement).split())
        for pause in self.pauses:
            if pause.thread_name == worker.name:
                pause._maybe_pause(conn, flat)

    # -- the test's API -------------------------------------------------------------------------

    def pause(self, *, thread_name: str, pattern: str, after: str | None = None) -> Pause:
        pause = Pause(self, thread_name=thread_name, pattern=pattern, after=after)
        self.pauses.append(pause)
        return pause

    def hold(self, operation: Callable[[Connection], object]) -> Hold:
        """Runs `operation` in an uncommitted transaction on its own connection."""
        hold = Hold(self.engine)
        self.holds.append(hold)
        operation(hold.connection)
        return hold

    def start(self, name: str, operation: Callable[[Connection], object]) -> Worker:
        worker = Worker(name=name)
        self._by_thread[name] = worker

        def run() -> None:
            try:
                with self.engine.begin() as connection:
                    worker.result = operation(connection)
            except BaseException as exc:  # noqa: BLE001 - surfaced to the test
                worker.error = exc
            finally:
                worker.finished.set()

        worker.thread = threading.Thread(target=run, name=name, daemon=True)
        self.workers.append(worker)
        worker.thread.start()
        return worker

    def wait_blocked_by(
        self, blocker: Pause | Hold | Worker, *workers: Worker, expected: int | None = None
    ) -> None:
        """Waits until `expected` sessions (default: as many as `workers`) are blocked, directly or
        along the queue of waiters, by `blocker`'s session."""
        wanted = expected if expected is not None else len(workers)
        budget = Budget(WAIT_SECONDS)
        while not budget.expired():
            for worker in workers:
                if worker.done:
                    raise AssertionError(
                        f"ended before blocking on the holder: {worker.describe()}"
                    )
            pid = blocker.pid
            if pid and self.blocked_by(pid) >= wanted:
                return
            time.sleep(0.02)
        if blocker.pid and self.blocked_by(blocker.pid) >= wanted:  # the last look is after expiry
            return
        raise AssertionError(
            f"expected {wanted} session(s) blocked by pid {blocker.pid}; "
            f"{self.blocked_by(blocker.pid) if blocker.pid else 0} were{budget.note()}. "
            f"Waiting sessions: {self.waiting_sessions()}"
        )

    def wait_done(self, worker: Worker, *, why: str) -> None:
        """Waits for `worker` to finish on its own (it must not need the pause released)."""
        snapshot: list[tuple[object, ...]] = []
        deadline = time.monotonic() + WAIT_SECONDS
        while time.monotonic() < deadline and not worker.done:
            worker.thread.join(timeout=0.02)
            if not snapshot and time.monotonic() > deadline - WAIT_SECONDS + 1.0:
                snapshot = self.waiting_sessions()
        if not worker.done:
            raise AssertionError(f"{why}; waiting sessions: {snapshot}")

    def join_all(self) -> None:
        for worker in self.workers:
            worker.thread.join(timeout=WAIT_SECONDS)
            assert worker.done, f"did not finish: {worker.name}; {self.waiting_sessions()}"

    # -- observation ----------------------------------------------------------------------------

    def blocked_by(self, holder_pid: int) -> int:
        with self.engine.connect() as connection:
            return int(
                connection.execute(
                    text("""
                        WITH RECURSIVE chain(pid, blocker) AS (
                            SELECT a.pid, b.blocker
                            FROM pg_stat_activity a, unnest(pg_blocking_pids(a.pid)) AS b(blocker)
                            WHERE a.datname = current_database() AND a.wait_event_type = 'Lock'
                          UNION
                            SELECT chain.pid, b.blocker
                            FROM chain, unnest(pg_blocking_pids(chain.blocker)) AS b(blocker)
                        )
                        SELECT count(DISTINCT pid) FROM chain WHERE blocker = :holder
                    """),
                    {"holder": holder_pid},
                ).scalar_one()
            )

    def waiting_sessions(self) -> list[tuple[object, ...]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(r"""
                    SELECT pid, pg_blocking_pids(pid),
                           left(regexp_replace(query, '\s+', ' ', 'g'), 110)
                    FROM pg_stat_activity
                    WHERE datname = current_database() AND wait_event_type = 'Lock'
                """)
            ).all()
        return [tuple(row) for row in rows]

    # -- cleanup --------------------------------------------------------------------------------

    def __enter__(self) -> "LockRace":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        problems: list[str] = []
        try:
            for pause in self.pauses:
                if not pause.released_by_test and not pause.resume.is_set():
                    if pause.reached.is_set() or exc_type is None:
                        problems.append(f"pause on {pause.thread_name} was never released")
                    pause.aborted = True
                    pause.resume.set()
            for hold in self.holds:
                try:
                    hold.close()
                except Exception as error:  # noqa: BLE001
                    problems.append(f"closing a held transaction failed: {error!r}")
            for worker in self.workers:
                worker.thread.join(timeout=WAIT_SECONDS)
            for worker in self.workers:
                if worker.done:
                    continue
                problems.append(f"{worker.name} did not finish; cancelling backend {worker.pid}")
                self._stop_backend(worker)
                worker.thread.join(timeout=WAIT_SECONDS)
                if not worker.done:
                    problems.append(f"{worker.name} still alive after terminate")
        finally:
            if self._listening:
                event.remove(self.engine, "before_cursor_execute", self._hook)
                self._listening = False
        if exc is not None:
            for problem in problems:
                exc.add_note(f"LockRace cleanup: {problem}")
            return False
        if problems:
            raise AssertionError("LockRace cleanup: " + "; ".join(problems))
        return False

    def _stop_backend(self, worker: Worker) -> None:
        """Cancels, then terminates, the backend of a worker this race started. Only that pid."""
        if worker.pid is None:
            return
        for function in ("pg_cancel_backend", "pg_terminate_backend"):
            with self.engine.connect() as connection:
                connection.execute(
                    text(f"SELECT {function}(:pid)"),  # noqa: S608
                    {"pid": worker.pid},
                )
            worker.thread.join(timeout=2.0)
            if worker.done:
                return


def new_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"
