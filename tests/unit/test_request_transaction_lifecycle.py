"""Request-transaction lifecycle without a database (P03-A prerequisite P3, DEF-022).

- T11b: `commit_request_transaction` driven directly with a fake connection and the barrier
  protocol: the COMMIT or ROLLBACK is held in the worker thread, a cancellation is delivered while
  it is held, and the recorded order and the escaping exception are asserted. These prove lifecycle
  ordering and exception preservation only; the PostgreSQL outcome is `test_request_transaction*`.
- T13: wiring over every effective route of `create_app()`.
- T15: the FastAPI and anyio behaviours P3 relies on, so an upgrade that changes them fails here.
- T16: the lockfile agrees with `pyproject.toml`.
"""

import ast
import asyncio
import inspect
import logging
import shutil
import subprocess
import threading
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anyio
import anyio.lowlevel
import anyio.to_thread
import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

import dnd_ai.api.deps as deps
from dnd_ai.api.app import create_app
from dnd_ai.api.deps import (
    commit_request_transaction,
    end_request_transaction,
    get_connection,
    get_engine,
)

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "src" / "dnd_ai" / "api"
_BOUND = 10.0


# --- the barrier protocol ------------------------------------------------------------------------


class _Events:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.items: list[str] = []

    def add(self, name: str) -> None:
        with self._lock:
            self.items.append(name)

    def snapshot(self) -> list[str]:
        with self._lock:
            return list(self.items)


class _FakeConnection:
    def __init__(self, events: _Events) -> None:
        self.events = events
        self.open = True

    def in_transaction(self) -> bool:
        return self.open

    def commit(self) -> None:
        self.open = False

    def rollback(self) -> None:
        self.open = False

    def invalidate(self) -> None:
        self.events.add("invalidate")

    def close(self) -> None:
        self.events.add("close")


class _Barrier:
    """Wraps a seam: records `<op>-enter`, optionally waits for `release`, runs the real
    operation (or raises), records `<op>-exit` in a `finally`. Never runs unreleased."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, op: str, events: _Events, *, hold: bool, fail: bool
    ) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        real = getattr(deps, f"_{op}")

        def wrapper(connection: Any) -> None:
            events.add(f"{op}-enter")
            self.entered.set()
            try:
                if hold and not self.release.wait(timeout=_BOUND):
                    events.add(f"{op}-timeout")
                    raise TimeoutError(f"{op} was never released")
                if fail:
                    raise OperationalError(op.upper(), {}, Exception("secret detail"))
                real(connection)
            finally:
                events.add(f"{op}-exit")

        monkeypatch.setattr(deps, f"_{op}", wrapper)


def _request() -> Any:
    return SimpleNamespace(state=SimpleNamespace())


def _drive(
    body: Callable[[Any], Any],
    *,
    during: Callable[[anyio.CancelScope, _Events], Any],
    events: _Events,
) -> dict[str, Any]:
    """Runs one request through the commit dependency as a task with its own cancel scope, and the
    `during` coroutine alongside it. `body(slot)` is the request's handler phase."""
    outcome: dict[str, Any] = {"escaped": None, "cancel_caught": None}

    async def main() -> None:
        scope_holder: dict[str, anyio.CancelScope] = {}
        started = anyio.Event()

        async def request_task() -> None:
            request = _request()
            with anyio.CancelScope() as scope:
                scope_holder["scope"] = scope
                started.set()
                try:
                    async with asynccontextmanager(commit_request_transaction)(request):
                        slot = request.state.dnd_ai_request_transaction
                        slot.connection = _FakeConnection(events)
                        await body(slot)
                except BaseException as exc:  # noqa: BLE001 - what escapes is what we assert on
                    outcome["escaped"] = exc
                    if not isinstance(exc, anyio.get_cancelled_exc_class()):
                        return
                    raise
            outcome["cancel_caught"] = scope.cancelled_caught

        with anyio.fail_after(_BOUND * 3):
            async with anyio.create_task_group() as group:
                group.start_soon(request_task)
                await started.wait()
                await during(scope_holder["scope"], events)

    anyio.run(main)
    return outcome


async def _no_handler_work(slot: Any) -> None:
    return None


async def _wait_entered(barrier: _Barrier) -> None:
    assert await anyio.to_thread.run_sync(barrier.entered.wait, _BOUND), "operation never entered"


async def _hold_then_cancel_then_release(
    barrier: _Barrier, events: _Events, observed: list[list[str]]
) -> None:
    await _wait_entered(barrier)
    await anyio.sleep(0)
    observed.append(events.snapshot())
    barrier.release.set()


def test_t11b_1_a_cancellation_during_commit_waits_for_the_commit_then_stops_the_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = _Events()
    barrier = _Barrier(monkeypatch, "commit", events, hold=True, fail=False)
    observed: list[list[str]] = []

    async def during(scope: anyio.CancelScope, events: _Events) -> None:
        try:
            await _wait_entered(barrier)
            scope.cancel()
            await anyio.sleep(0.25)  # a settle period: a wrongly eager close would have happened
            observed.append(events.snapshot())
        finally:
            barrier.release.set()

    outcome = _drive(_no_handler_work, during=during, events=events)
    assert observed == [["commit-enter"]]  # still not closed while the COMMIT is held
    assert events.snapshot() == ["commit-enter", "commit-exit", "close"]
    assert outcome["cancel_caught"] is True  # the checkpoint surfaced the cancellation
    assert isinstance(outcome["escaped"], asyncio.CancelledError)


def test_t11b_2_a_cancellation_during_rollback_keeps_the_handlers_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = _Events()
    barrier = _Barrier(monkeypatch, "rollback", events, hold=True, fail=False)
    observed: list[list[str]] = []
    boom = ValueError("handler failed")

    async def body(slot: Any) -> None:
        raise boom

    async def during(scope: anyio.CancelScope, events: _Events) -> None:
        try:
            await _wait_entered(barrier)
            scope.cancel()
            await anyio.sleep(0.25)
            observed.append(events.snapshot())
        finally:
            barrier.release.set()

    outcome = _drive(body, during=during, events=events)
    assert observed == [["rollback-enter"]]
    assert events.snapshot() == ["rollback-enter", "rollback-exit", "close"]
    assert outcome["escaped"] is boom  # identity, not type


def test_t11b_3_a_failed_rollback_after_a_handler_error_is_logged_and_never_replaces_it(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    events = _Events()
    _Barrier(monkeypatch, "rollback", events, hold=False, fail=True)
    boom = ValueError("handler failed")

    async def body(slot: Any) -> None:
        raise boom

    async def during(scope: anyio.CancelScope, events: _Events) -> None:
        return None

    with caplog.at_level(logging.ERROR, logger="dnd_ai.api.deps"):
        outcome = _drive(body, during=during, events=events)
    assert events.snapshot() == ["rollback-enter", "rollback-exit", "invalidate", "close"]
    assert outcome["escaped"] is boom
    messages = [r.getMessage() for r in caplog.records if r.name == "dnd_ai.api.deps"]
    assert messages == ["request transaction rollback failed: OperationalError"]
    assert "secret" not in messages[0]


def test_t11b_4_a_failed_rollback_after_a_cancellation_does_not_replace_the_cancellation(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    events = _Events()
    _Barrier(monkeypatch, "rollback", events, hold=False, fail=True)

    async def body(slot: Any) -> None:
        await anyio.sleep_forever()  # the handler awaits; the cancellation arrives here

    async def during(scope: anyio.CancelScope, events: _Events) -> None:
        await anyio.sleep(0.05)
        events.add("cancel")
        scope.cancel()

    with caplog.at_level(logging.ERROR, logger="dnd_ai.api.deps"):
        outcome = _drive(body, during=during, events=events)
    assert events.snapshot() == [
        "cancel",
        "rollback-enter",
        "rollback-exit",
        "invalidate",
        "close",
    ]
    assert outcome["cancel_caught"] is True
    assert isinstance(outcome["escaped"], asyncio.CancelledError)
    assert "OperationalError" not in repr(outcome["escaped"])
    messages = [r.getMessage() for r in caplog.records if r.name == "dnd_ai.api.deps"]
    assert messages == ["request transaction rollback failed: OperationalError"]


def test_a_request_with_no_connection_does_no_work_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    events = _Events()
    _Barrier(monkeypatch, "commit", events, hold=False, fail=False)

    async def main() -> None:
        request = _request()
        async with asynccontextmanager(commit_request_transaction)(request):
            pass
        end_request_transaction(request)  # no connection: a no-op

    anyio.run(main)
    assert events.snapshot() == []


# --- T15: the framework behaviour P3 relies on --------------------------------------------------


def _scope(path: str) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 1),
        "server": ("testserver", 80),
    }


def test_t15_1_a_function_scoped_generator_exits_before_the_response_start() -> None:
    order: list[str] = []
    app = FastAPI()

    def function_scoped() -> Iterator[None]:
        yield
        order.append("function-exit")

    def request_scoped() -> Iterator[None]:
        yield
        order.append("request-exit")

    @app.get("/x")
    def _route(
        _a: None = Depends(function_scoped, scope="function"),  # noqa: B008
        _b: None = Depends(request_scoped),  # noqa: B008
    ) -> dict[str, int]:
        return {"ok": 1}

    async def observed_call() -> None:
        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                order.append("response-start")

        await app(_scope("/x"), receive, send)

    anyio.run(observed_call)
    assert order == ["function-exit", "response-start", "request-exit"]


def _run_blocked_request(app: FastAPI, path: str) -> None:
    """Calls the app directly, with a handler that blocks, and cancels the request's scope."""

    async def main() -> None:
        disconnect = anyio.Event()

        async def receive() -> dict[str, Any]:
            await disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            return None

        with anyio.CancelScope() as scope:

            async def cancel_soon() -> None:
                await anyio.sleep(0.2)
                scope.cancel()

            async with anyio.create_task_group() as group:
                group.start_soon(cancel_soon)
                await app(_scope(path), receive, send)

    anyio.run(main)


def test_t15_2_an_async_generator_dependency_receives_a_cancellation() -> None:
    seen: list[str] = []
    app = FastAPI()

    async def dep() -> Any:
        try:
            yield
        except BaseException as exc:  # noqa: BLE001
            seen.append(type(exc).__name__)
            raise

    @app.get("/x")
    async def _route(_d: None = Depends(dep, scope="function")) -> None:  # noqa: B008
        await anyio.sleep_forever()

    _run_blocked_request(app, "/x")
    assert seen and seen[0] in {"CancelledError", "Cancelled"}


def test_t15_3_a_sync_generator_dependencys_exit_is_not_run_for_a_cancellation() -> None:
    after: list[str] = []
    app = FastAPI()

    def dep() -> Iterator[None]:
        yield
        after.append("exit")  # plain code after the yield: runs on a normal exit only

    @app.get("/blocked")
    async def _blocked(_d: None = Depends(dep, scope="function")) -> None:  # noqa: B008
        await anyio.sleep_forever()

    @app.get("/fine")
    async def _fine(_d: None = Depends(dep, scope="function")) -> dict[str, int]:  # noqa: B008
        return {"ok": 1}

    _run_blocked_request(app, "/blocked")
    assert after == []  # documents why the commit dependency is an async generator
    with TestClient(app) as client:
        assert client.get("/fine").status_code == 200
    assert after == ["exit"]


def test_t15_4_a_shielded_worker_thread_call_finishes_and_then_the_cancellation_surfaces() -> None:
    entered, release = threading.Event(), threading.Event()
    log: list[str] = []

    def work() -> None:
        log.append("enter")
        entered.set()
        assert release.wait(_BOUND)
        log.append("exit")

    async def main() -> bool:
        holder: dict[str, Any] = {}

        async def request() -> None:
            with anyio.CancelScope() as scope:
                holder["scope"] = scope
                with anyio.CancelScope(shield=True):
                    await anyio.to_thread.run_sync(work)
                log.append("after-shield")
                await anyio.lowlevel.checkpoint_if_cancelled()
                log.append("not reached")
            holder["caught"] = scope.cancelled_caught

        try:
            async with anyio.create_task_group() as group:
                group.start_soon(request)
                assert await anyio.to_thread.run_sync(entered.wait, _BOUND)
                holder["scope"].cancel()
                await anyio.sleep(0.2)
                assert log == ["enter"]  # the cancellation did not abandon the call
                release.set()
        finally:
            release.set()
        return bool(holder["caught"])

    assert anyio.run(main) is True
    assert log == ["enter", "exit", "after-shield"]


# --- T13: wiring --------------------------------------------------------------------------------


def _api_contexts() -> list[Any]:
    return [c for c in iter_route_contexts(create_app().routes) if isinstance(c.route, APIRoute)]


def _walk(dependant: Any) -> Iterator[Any]:
    for child in dependant.dependencies:
        yield child
        yield from _walk(child)


def test_t13_every_route_starts_with_the_commit_dependency_and_one_connection_entry() -> None:
    contexts = _api_contexts()
    assert len(contexts) > 300  # the effective routes of every included router
    for context in contexts:
        first = context.dependant.dependencies[0]
        assert first.call is commit_request_transaction, context.path
        assert first.scope == "function", context.path
        for dependency in _walk(context.dependant):
            if dependency.call is get_connection:
                assert dependency.scope is None and dependency.use_cache, context.path


_ENGINE_BACKED = {
    "request_npc_conversation_turn_endpoint",
    "review_proposed_change_endpoint",
    "request_campaign_synthesis_endpoint",
    "apply_foundry_combat_sync_endpoint",
    "ingest_reference_passages_endpoint",
    "grant_source_to_campaign_endpoint",
    "revoke_source_campaign_grant_endpoint",
    "retrieve_cited_passages_endpoint",
}


def test_t13_the_engine_backed_routes_are_exactly_the_eight_and_each_ends_its_transaction() -> None:
    found: dict[str, Any] = {}
    for context in _api_contexts():
        direct_engine = any(d.call is get_engine for d in context.dependant.dependencies)
        has_connection = any(d.call is get_connection for d in _walk(context.dependant))
        if direct_engine and has_connection:
            found[context.endpoint.__name__] = context.endpoint
    assert set(found) == _ENGINE_BACKED

    for name, endpoint in found.items():
        tree = ast.parse(inspect.getsource(endpoint).lstrip())
        function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        ends = [
            n.lineno
            for n in ast.walk(function)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "end_request_transaction"
        ]
        assert len(ends) == 1, name
        uses = [
            (n.lineno, n.id)
            for n in ast.walk(function)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
        ]
        engine_lines = [line for line, ident in uses if ident == "engine"]
        connection_lines = [line for line, ident in uses if ident == "connection"]
        assert engine_lines and min(engine_lines) > ends[0], name  # no engine use before the end
        assert all(line < ends[0] for line in connection_lines), name  # none after it


def test_t13_get_connection_is_the_only_sync_generator_dependency() -> None:
    sync_generators = {
        d.call
        for context in _api_contexts()
        for d in _walk(context.dependant)
        if inspect.isgeneratorfunction(d.call)
    }
    assert sync_generators == {get_connection}


def test_t13_no_api_module_uses_deferred_or_streamed_responses() -> None:
    banned = ("BackgroundTasks", "StreamingResponse", "FileResponse", "EventSourceResponse")
    offenders = [
        f"{path.name}: {word}"
        for path in API.rglob("*.py")
        for word in banned
        if word in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


# --- T16: the lockfile --------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
def test_t16_the_lockfile_agrees_with_the_fastapi_floor() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"fastapi>=0.141.1"' in pyproject
    result = subprocess.run(  # noqa: S603
        ["uv", "lock", "--check", "--offline"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
