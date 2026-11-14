"""Synchronization for real HTTP races (P03-A A5a RA1 and A5b R1/R2).

`tests/lock_race_support.py::LockRace.pause` stops a worker by *thread name*, which cannot name a
`TestClient` request: the route runs on the client's portal and a thread-pool thread. `StatementGate`
keys on the SQL instead. It stops the first request statement that matches `pattern`, on whichever
thread runs it, *before* the statement executes, so the request still holds every lock it took earlier
and none it would take next. It records the stopped request's backend pid so a test can observe, through
`pg_blocking_pids`, that a second request is genuinely waiting on it before anything is released.

The gate fires once, is removed on exit, and releases an unreleased request on exit so nothing is left
stuck. Arm one gate, wait for it to be reached, then start the competing request: the competitor must
not match the pattern.
"""

import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import Engine, event, text

WAIT_SECONDS = 15.0


def activity_report(engine: Engine) -> str:
    """What every non-idle backend of this database is doing, for a failed wait's message: pid, state,
    wait event, transaction and state age, blockers and the statement. A diagnostic only; a failure to
    take it is reported, never raised."""
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT pid, state, wait_event_type, wait_event, "
                    "round(extract(epoch FROM now() - xact_start)::numeric, 2) AS xact_s, "
                    "round(extract(epoch FROM now() - state_change)::numeric, 2) AS state_s, "
                    "pg_blocking_pids(pid) AS blockers, "
                    "left(regexp_replace(query, '[[:space:]]+', ' ', 'g'), 150) AS q "
                    "FROM pg_stat_activity WHERE datname = current_database() "
                    "AND pid <> pg_backend_pid() AND state <> 'idle' ORDER BY xact_start NULLS LAST"
                )
            ).all()
    except Exception as exc:  # noqa: BLE001 - diagnostics must not mask the failure
        return f"[activity report unavailable: {exc!r}]"
    lines = [
        f"  pid={r.pid} {r.state} wait={r.wait_event_type}/{r.wait_event} xact={r.xact_s}s "
        f"state={r.state_s}s blockers={list(r.blockers)} q={r.q!r}"
        for r in rows
    ]
    return "backends:\n" + ("\n".join(lines) if lines else "  (none non-idle)")


class StatementGate:
    def __init__(self, engine: Engine, pattern: str) -> None:
        import re

        self.engine = engine
        self.pattern = re.compile(pattern)
        self.reached = threading.Event()
        self.resume = threading.Event()
        self.pid: int | None = None
        self.matched: str | None = None
        self.armed_at = time.monotonic()
        self.reached_at: float | None = None
        self._fired = False

    def describe(self) -> str:
        reached = (
            f"reached after {self.reached_at - self.armed_at:.2f}s on pid {self.pid}"
            if self.reached_at is not None
            else f"not reached after {time.monotonic() - self.armed_at:.2f}s"
        )
        return f"gate {self.pattern.pattern!r}: {reached}; statement={self.matched!r}"

    def _hook(self, conn: Any, cursor: Any, statement: Any, *_: Any) -> None:
        if self._fired or not self.pattern.search(" ".join(str(statement).split())):
            return
        self._fired = True
        self.pid = conn.connection.driver_connection.info.backend_pid
        self.matched = " ".join(str(statement).split())[:150]
        self.reached_at = time.monotonic()
        self.reached.set()
        self.resume.wait(WAIT_SECONDS)

    def __enter__(self) -> "StatementGate":
        event.listen(self.engine, "before_cursor_execute", self._hook)
        return self

    def __exit__(self, *_: object) -> None:
        self.resume.set()
        event.remove(self.engine, "before_cursor_execute", self._hook)

    def wait_reached(self) -> None:
        assert self.reached.wait(WAIT_SECONDS), (
            "the request never reached the gated statement; "
            f"{self.describe()}\n{activity_report(self.engine)}"
        )

    def release(self) -> None:
        self.resume.set()


def sessions_blocked_by(engine: Engine, holder_pid: int) -> int:
    """How many sessions wait, directly or along the queue of waiters, on `holder_pid`."""
    with engine.connect() as connection:
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


def wait_until_blocked(engine: Engine, gate: StatementGate, *, expected: int = 1) -> None:
    """Waits until `expected` sessions are blocked by the gated request's session."""
    assert gate.pid is not None
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        if sessions_blocked_by(engine, gate.pid) >= expected:
            return
        time.sleep(0.02)
    raise AssertionError(
        f"expected {expected} session(s) blocked by pid {gate.pid}; "
        f"{sessions_blocked_by(engine, gate.pid)} were; {gate.describe()}\n{activity_report(engine)}"
    )


def run_in_thread(name: str, operation: Callable[[], Any]) -> "Request":
    """Runs `operation` (an HTTP call) on its own named thread and returns a handle to its result."""
    request = Request(name)

    def run() -> None:
        try:
            request.result = operation()
        except BaseException as exc:  # noqa: BLE001 - surfaced to the test
            request.error = exc
        finally:
            request.ended = time.monotonic()
            request.done.set()

    request.thread = threading.Thread(target=run, name=name, daemon=True)
    request.thread.start()
    return request


class Request:
    def describe(self) -> str:
        """The request's outcome so far, for a failed wait's message."""
        if not self.done.is_set():
            return f"{self.name}: still running after {time.monotonic() - self.started:.2f}s"
        took = (self.ended or time.monotonic()) - self.started
        if self.error is not None:
            return f"{self.name}: raised {self.error!r} after {took:.2f}s"
        status = getattr(self.result, "status_code", None)
        text_ = str(getattr(self.result, "text", self.result))[:200]
        return f"{self.name}: finished {status} {text_!r} after {took:.2f}s"

    def __init__(self, name: str) -> None:
        self.started = time.monotonic()
        self.ended: float | None = None
        self.name = name
        self.result: Any = None
        self.error: BaseException | None = None
        self.done = threading.Event()
        self.thread = threading.Thread()

    def wait(self, why: str) -> Any:
        assert self.done.wait(WAIT_SECONDS), f"{self.name} did not finish: {why}"
        assert self.error is None, f"{self.name} raised {self.error!r}"
        return self.result

    def finished(self) -> bool:
        return self.done.is_set()


def new_key() -> str:
    return f"race-{uuid.uuid4().hex[:12]}"


def wait_until_pid_blocks(engine: Engine, holder_pid: int, *, expected: int = 1) -> None:
    """Waits until `expected` sessions are blocked by `holder_pid` (a session the test holds open
    itself, e.g. the fixture helper's transaction, rather than a gated request)."""
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        if sessions_blocked_by(engine, holder_pid) >= expected:
            return
        time.sleep(0.02)
    raise AssertionError(
        f"expected {expected} session(s) blocked by pid {holder_pid}; "
        f"{sessions_blocked_by(engine, holder_pid)} were\n{activity_report(engine)}"
    )


def deadlock_count(engine: Engine) -> int:
    """The database's cumulative deadlock counter: a 40P01 abort increments it, so a 5xx loser can
    be told apart from an arbitrary error."""
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT deadlocks FROM pg_stat_database WHERE datname = current_database()")
            ).scalar_one()
        )


def wait_for_deadlock_count(engine: Engine, at_least: int) -> int:
    """Polls (the statistics are flushed asynchronously) until the counter reaches `at_least`."""
    deadline = time.monotonic() + WAIT_SECONDS
    count = deadlock_count(engine)
    while count < at_least and time.monotonic() < deadline:
        time.sleep(0.1)
        count = deadlock_count(engine)
    return count
