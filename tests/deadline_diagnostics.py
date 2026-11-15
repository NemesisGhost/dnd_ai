"""Persistent deadline diagnostics for the HTTP race harness (R01 S5-E2 E10 correction, design section 10).

Why this exists. Four-shard runs have stalled on a race test whose gated statement was never reached, with **no
non-idle backend** in `pg_stat_activity`, the request still running client-side, a different test each time, and
the file green when run alone. The old `activity_report` filters `state <> 'idle'`, so it cannot show a request that is
between transactions, waiting for a pool connection, or stuck in application code or the event loop. Those stalls are
**not** classified as flakes: their cause is unresolved, and this module only makes the next one diagnosable.

What it does. `deadline_message()` is called at every harness deadline *before* the assertion is raised (so while the
parked requests, the gate listeners and the pool are all still alive, before any teardown), and returns the text that
goes into the assertion message. It captures, each in its own best-effort collector:

* request completion and exception state (`Request`), per-request progress markers (checkout, last statements, commit,
  rollback) recorded by class-level SQLAlchemy listeners installed by `install()`;
* every thread's stack (test threads, the TestClient portal, anyio workers) and, where reachable, every asyncio
  task's stack;
* the connection pool's status, which connections are checked out and by which thread, and the recent event tail;
* every live `StatementGate`: pattern, reached/released, backend pid, hit count, and whether its listener is still
  registered;
* the database: **all** backends of this database including idle and idle-in-transaction (state and transaction age,
  wait event, xid, blockers, query), their locks, and the deadlock counter, read through a **separate** direct
  connection (never the pool, which may be the thing that is exhausted);
* machine context: shard, CPU count, load sample, wall time since the session began.

The report is written to `$RUNNER_DEADLINE_DIAG_DIR` (the four-shard runner sets it per shard, inside the kept run
directory) or `<tempdir>/deadline-diagnostics/`, and its path is in the assertion message.

What it does not do. It never extends or retries a deadline, never skips, never reruns, and never raises: a collector
that fails is reported as failed and the others still run. The original assertion is raised unchanged.
"""

import asyncio
import collections
import gc
import os
import re
import sys
import tempfile
import threading
import time
import traceback
import weakref
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, event
from sqlalchemy.pool import Pool as _PoolClass

_SESSION_START = time.monotonic()
_EVENTS: collections.deque[tuple[float, str, str, int | None, str]] = collections.deque(maxlen=4000)
_CHECKED_OUT: dict[int, dict[str, Any]] = {}
_LOCK = threading.Lock()
_INSTALLED = False

#: Live harness objects, registered by their constructors (weakly: a finished test drops out).
LIVE_GATES: "weakref.WeakSet[Any]" = weakref.WeakSet()
LIVE_REQUESTS: "weakref.WeakSet[Any]" = weakref.WeakSet()
LIVE_ENGINES: "weakref.WeakSet[Engine]" = weakref.WeakSet()


def _pid(dbapi_connection: Any) -> int | None:
    try:
        return int(dbapi_connection.info.backend_pid)
    except Exception:  # noqa: BLE001 - a diagnostic never raises
        return None


def _record(kind: str, pid: int | None, detail: str = "") -> None:
    _EVENTS.append((time.monotonic(), kind, threading.current_thread().name, pid, detail))


def _on_checkout(dbapi_connection: Any, record: Any, proxy: Any) -> None:
    pid = _pid(dbapi_connection)
    with _LOCK:
        _CHECKED_OUT[id(record)] = {
            "pid": pid,
            "thread": threading.current_thread().name,
            "since": time.monotonic(),
            "last": "",
        }
    _record("checkout", pid)


def _on_checkin(dbapi_connection: Any, record: Any) -> None:
    with _LOCK:
        _CHECKED_OUT.pop(id(record), None)
    _record("checkin", _pid(dbapi_connection) if dbapi_connection is not None else None)


def _on_execute(conn: Any, cursor: Any, statement: Any, *rest: Any) -> None:
    head = " ".join(str(statement).split())[:120]
    pid = None
    try:
        pid = _pid(conn.connection.driver_connection)
        with _LOCK:
            entry = _CHECKED_OUT.get(id(conn.connection._connection_record))
            if entry is not None:
                entry["last"] = head
    except Exception:  # noqa: BLE001
        pass
    _record("execute", pid, head)


def _on_commit(conn: Any) -> None:
    _record("commit", None)


def _on_rollback(conn: Any) -> None:
    _record("rollback", None)


def install() -> None:
    """Install the class-level progress listeners once per process (idempotent; cheap: bounded ring buffer)."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    event.listen(_PoolClass, "checkout", _on_checkout)
    event.listen(_PoolClass, "checkin", _on_checkin)
    event.listen(Engine, "before_cursor_execute", _on_execute)
    event.listen(Engine, "commit", _on_commit)
    event.listen(Engine, "rollback", _on_rollback)


# -- collectors (each returns text; any exception is caught by `deadline_report`) -----------------------------------


def _requests_section(requests: Iterable[Any]) -> str:
    seen = list(requests) or sorted(LIVE_REQUESTS, key=lambda r: r.started)
    now = time.monotonic()
    frames = sys._current_frames()
    lines: list[str] = []
    for r in seen:
        lines.append(
            f"- {r.name}: done={r.done.is_set()} started={now - r.started:.2f}s ago "
            f"ended={(now - r.ended):.2f}s ago error={r.error!r} result={getattr(r.result, 'status_code', r.result)!r}"
            if r.ended is not None
            else f"- {r.name}: done={r.done.is_set()} started={now - r.started:.2f}s ago, STILL RUNNING "
            f"error={r.error!r}"
        )
        ident = getattr(r, "thread_ident", None)
        if ident is not None and ident in frames and not r.done.is_set():
            lines.append(
                "    stack:\n"
                + _indent("".join(traceback.format_stack(frames[ident], limit=30)), 6)
            )
    return "\n".join(lines) or "(no live requests registered)"


def _indent(text: str, n: int) -> str:
    pad = " " * n
    return "\n".join(pad + line for line in text.rstrip().splitlines())


def _threads_section() -> str:
    frames = sys._current_frames()
    lines = []
    for t in threading.enumerate():
        lines.append(f"- thread {t.name!r} ident={t.ident} daemon={t.daemon} alive={t.is_alive()}")
        frame = frames.get(t.ident) if t.ident is not None else None
        if frame is not None:
            lines.append(_indent("".join(traceback.format_stack(frame, limit=25)), 6))
    return "\n".join(lines)


def _tasks_section() -> str:
    lines: list[str] = []
    for obj in gc.get_objects():
        if isinstance(obj, asyncio.AbstractEventLoop) and not obj.is_closed():
            try:
                tasks = list(asyncio.all_tasks(obj))
            except Exception as exc:  # noqa: BLE001 - another thread's loop: best effort
                lines.append(
                    f"- loop {id(obj):#x} running={obj.is_running()}: tasks unavailable ({exc!r})"
                )
                continue
            lines.append(f"- loop {id(obj):#x} running={obj.is_running()} tasks={len(tasks)}")
            for task in tasks[:40]:
                lines.append(f"    {task!r}")
                for frame in task.get_stack(limit=6):
                    lines.append(
                        f"      at {frame.f_code.co_filename}:{frame.f_lineno} in {frame.f_code.co_name}"
                    )
    return "\n".join(lines) or "(no open asyncio event loop reachable)"


def _engines(engine: Engine | None) -> list[Engine]:
    found: list[Engine] = [engine] if engine is not None else []
    for gate in list(LIVE_GATES):
        e = getattr(gate, "engine", None)
        if e is not None and e not in found:
            found.append(e)
    return found


def _pool_section(engines: list[Engine]) -> str:
    now = time.monotonic()
    lines = []
    for e in engines:
        lines.append(f"- engine {e.url.render_as_string(hide_password=True)}: {e.pool.status()}")
    with _LOCK:
        held = list(_CHECKED_OUT.values())
    lines.append(f"- {len(held)} connection(s) checked out (process-wide):")
    for h in held:
        lines.append(
            f"    pid={h['pid']} thread={h['thread']!r} held {now - h['since']:.2f}s last={h['last']!r}"
        )
    lines.append("- recent events (oldest first):")
    for stamp, kind, thread, pid, detail in list(_EVENTS)[-40:]:
        lines.append(f"    -{now - stamp:7.2f}s {kind:<8} thread={thread!r} pid={pid} {detail}")
    return "\n".join(lines)


def _gates_section() -> str:
    now = time.monotonic()
    lines = []
    for g in list(LIVE_GATES):
        try:
            registered = event.contains(g.engine, "before_cursor_execute", g._hook)
        except Exception as exc:  # noqa: BLE001
            registered = f"unknown ({exc!r})"
        lines.append(
            f"- {type(g).__name__} pattern={g.pattern.pattern!r} reached={g.reached.is_set()} "
            f"released={g.resume.is_set()} pid={g.pid} fired={g._fired} seen={getattr(g, 'seen', None)}/"
            f"{getattr(g, 'n', getattr(g, 'expected', None))} armed {now - g.armed_at:.2f}s ago "
            f"matched={g.matched!r} listener_registered={registered}"
        )
    return "\n".join(lines) or "(no live gates)"


_ACTIVITY = """
SELECT pid, state, wait_event_type, wait_event, backend_xid::text AS xid,
       round(extract(epoch FROM now() - xact_start)::numeric, 2) AS xact_s,
       round(extract(epoch FROM now() - state_change)::numeric, 2) AS state_s,
       pg_blocking_pids(pid) AS blockers, application_name,
       left(regexp_replace(query, '[[:space:]]+', ' ', 'g'), 200) AS q
FROM pg_stat_activity
WHERE datname = current_database() AND pid <> pg_backend_pid()
ORDER BY xact_start NULLS LAST, pid
"""
_LOCKS = """
SELECT l.pid, l.locktype, l.mode, l.granted, COALESCE(l.relation::regclass::text, l.transactionid::text, l.objid::text) AS what
FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid
WHERE a.datname = current_database() AND a.pid <> pg_backend_pid() AND l.locktype <> 'virtualxid'
ORDER BY l.pid, l.granted DESC LIMIT 300
"""


def _database_section(engines: list[Engine]) -> str:
    import psycopg

    if not engines:
        return "(no engine known: nothing to ask the database)"
    url = engines[0].url.set(drivername="postgresql").render_as_string(hide_password=False)
    out: list[str] = []
    # a direct connection: never the pool (it may be exhausted), never longer than a few seconds
    with psycopg.connect(
        url, connect_timeout=5, options="-c statement_timeout=5000", autocommit=True
    ) as c:
        out.append("backends (ALL states, including idle and idle in transaction):")
        for r in c.execute(_ACTIVITY):
            out.append(
                f"  pid={r[0]} {r[1]} wait={r[2]}/{r[3]} xid={r[4]} xact={r[5]}s state={r[6]}s "
                f"blockers={list(r[7])} app={r[8]!r} q={r[9]!r}"
            )
        out.append("locks:")
        for r in c.execute(_LOCKS):
            out.append(f"  pid={r[0]} {r[1]} {r[2]} granted={r[3]} {r[4]}")
        deadlocks = c.execute(
            "SELECT deadlocks FROM pg_stat_database WHERE datname = current_database()"
        ).fetchone()
        out.append(f"deadlock counter: {deadlocks[0] if deadlocks else None}")
    return "\n".join(out)


def _machine_section() -> str:
    try:
        load: Any = os.getloadavg()
    except (AttributeError, OSError):
        try:
            import psutil  # type: ignore[import-not-found]

            load = f"cpu_percent={psutil.cpu_percent(interval=0.2)}"
        except Exception:  # noqa: BLE001
            load = "unavailable on this platform"
    return (
        f"shard={os.environ.get('CI_TEST_SHARD')} cpus={os.cpu_count()} load={load} "
        f"since_session_start={time.monotonic() - _SESSION_START:.1f}s "
        f"test={os.environ.get('PYTEST_CURRENT_TEST')}"
    )


# -- the report ----------------------------------------------------------------------------------------------------


def diagnostics_dir() -> Path:
    configured = os.environ.get("RUNNER_DEADLINE_DIAG_DIR")
    return Path(configured) if configured else Path(tempfile.gettempdir()) / "deadline-diagnostics"


def deadline_report(
    reason: str, *, engine: Engine | None = None, requests: Iterable[Any] = ()
) -> tuple[str, Path | None]:
    """Collect everything, write it to a file, return (text, path). Never raises; a failed collector is reported."""
    engines = _engines(engine)
    collectors: list[tuple[str, Callable[[], str]]] = [
        ("request completion and exception state", lambda: _requests_section(requests)),
        (
            "database activity (all backends, locks, deadlock counter)",
            lambda: _database_section(engines),
        ),
        ("gate and listener state", _gates_section),
        ("connection pool and checkout state", lambda: _pool_section(engines)),
        ("thread stacks", _threads_section),
        ("asyncio tasks", _tasks_section),
        ("machine context", _machine_section),
    ]
    parts = [f"DEADLINE DIAGNOSTICS: {reason}", f"test: {os.environ.get('PYTEST_CURRENT_TEST')}"]
    for title, collect in collectors:
        try:
            body = collect()
        except BaseException as exc:  # noqa: BLE001 - the report must survive any single collector
            body = f"[collector failed: {exc!r}]\n{traceback.format_exc(limit=3)}"
        parts.append(f"== {title} ==\n{body}")
    text = "\n\n".join(parts) + "\n"
    path: Path | None = None
    try:
        directory = diagnostics_dir()
        directory.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = re.sub(
            r"[^A-Za-z0-9._-]+",
            "_",
            (os.environ.get("PYTEST_CURRENT_TEST") or "no-test").split(" ")[0],
        )
        path = directory / f"{stamp}-{name[:150]}-{os.getpid()}-{threading.get_ident() % 10000}.txt"
        path.write_text(text, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        text += f"\n[report could not be written: {exc!r}]\n"
    return text, path


def deadline_message(
    reason: str, *, engine: Engine | None = None, requests: Iterable[Any] = ()
) -> str:
    """The text appended to a harness assertion: the report's path and its most useful sections inline."""
    try:
        text, path = deadline_report(reason, engine=engine, requests=requests)
    except BaseException as exc:  # noqa: BLE001 - belt and braces: never mask the real failure
        return f"[deadline diagnostics unavailable: {exc!r}]"
    inline = text if path is None else text[:6000]
    where = f"report file: {path}" if path is not None else "report file: (not written)"
    return f"\n{where}\n{inline}"
