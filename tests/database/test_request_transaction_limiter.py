"""The request transaction's finalizer does not share FastAPI's handler limiter (P03-A P3 fix).

FastAPI runs every synchronous handler and dependency on AnyIO's default thread limiter. If
handlers waiting on a lock held by a request transaction took every default token, a finalizer that
needed one too could never run its COMMIT or ROLLBACK, the lock would never be released, and nothing
could progress. The finalizer therefore runs on its own bounded limiter (`finalizer_limiter`).

Each case reduces the default limiter to three tokens, has a request transaction hold a row lock,
and lets synchronous handlers (the waiters) block on that row until they hold every default token.
Only then is the holder allowed to finish:

- an app-wide finalizer COMMIT, and the same with a ROLLBACK (the holder is an async handler, so it
  holds no default token while it waits);
- an engine-backed route that ends its transaction early (`end_request_transaction`), which commits
  on its own handler thread and needs no limiter at all.

Every wait is bounded. A `finally` terminates any still-held backend, so a regression fails the test
instead of leaving threads blocked.
"""

import threading
import time
import uuid
from collections.abc import Iterator
from typing import Annotated, Any

import anyio
import anyio.to_thread
import pytest
from fastapi import Depends, FastAPI, Request
from sqlalchemy import Connection, Engine, create_engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.deps import (
    FINALIZER_LIMITER_TOKENS,
    end_request_transaction,
    finalizer_limiter,
    get_connection,
    get_engine,
)
from tests.factories import make_user

pytestmark = pytest.mark.database

_TOKENS = 3  # the reduced default limiter
_BOUND = 15.0
_MARKER = "p3-limiter-committed"

Conn = Annotated[Connection, Depends(get_connection)]


@pytest.fixture
def app_engine(postgres_engine: Engine) -> Iterator[Engine]:
    name = f"p3lim{uuid.uuid4().hex[:8]}"
    engine = create_engine(
        postgres_engine.url, pool_size=12, max_overflow=0, connect_args={"application_name": name}
    )
    engine.application_name = name  # type: ignore[attr-defined]
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def locked_user(postgres_engine: Engine) -> Iterator[tuple[uuid.UUID, str]]:
    with postgres_engine.begin() as connection:
        user_id = make_user(connection, "Limiter Original")
    try:
        yield user_id, "Limiter Original"
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM security.users WHERE user_id = :u"), {"u": user_id}
            )


class _State:
    def __init__(self) -> None:
        self.locked = anyio.Event()
        self.release = anyio.Event()
        self.locked_thread = threading.Event()
        self.release_thread = threading.Event()


def _build_app(engine: Engine, user_id: uuid.UUID, state: _State) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: engine
    lock = "SELECT display_name FROM security.users WHERE user_id = :u FOR UPDATE"
    write = "UPDATE security.users SET display_name = :n WHERE user_id = :u"

    @app.post("/test-configure")
    async def _configure() -> dict[str, int]:
        anyio.to_thread.current_default_thread_limiter().total_tokens = _TOKENS
        return {"tokens": _TOKENS}

    @app.post("/test-holder/{mode}")
    async def _holder(mode: str, connection: Conn) -> dict[str, str]:
        # async: it holds no default token while it waits, so only its finalizer needs a thread
        connection.execute(text(lock), {"u": user_id})
        connection.execute(text(write), {"n": _MARKER, "u": user_id})
        state.locked.set()
        await state.release.wait()
        if mode == "rollback":
            raise ValueError("the holder fails")
        return {"held": "yes"}

    @app.post("/test-waiter")
    def _waiter(connection: Conn) -> dict[str, str]:
        return {"name": str(connection.execute(text(lock), {"u": user_id}).scalar_one())}

    @app.post("/test-engine-route")
    def _engine_route(request: Request, connection: Conn) -> dict[str, str]:
        connection.execute(text(lock), {"u": user_id})
        connection.execute(text(write), {"n": _MARKER, "u": user_id})
        state.locked_thread.set()
        assert state.release_thread.wait(_BOUND), "never released"
        end_request_transaction(request)  # commits here, on this thread
        return {"ended": "early"}

    return app


async def _call(app: FastAPI, path: str, results: list[tuple[str, int, Any]]) -> None:
    body = b"{}"
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("testclient", 1),
        "server": ("testserver", 80),
    }
    status = 0
    chunks: list[bytes] = []
    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        await anyio.sleep_forever()
        raise AssertionError("unreachable")

    async def send(message: dict[str, Any]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    await app(scope, receive, send)
    results.append((path, status, b"".join(chunks)))


def _waiting_on_lock(engine: Engine, name: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE application_name = :n AND wait_event_type = 'Lock'"
                ),
                {"n": name},
            ).scalar_one()
        )


def _terminate(engine: Engine, name: str) -> None:
    with engine.connect() as connection:
        connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE application_name = :n AND pid <> pg_backend_pid()"
            ),
            {"n": name},
        )
        connection.commit()


def _name(engine: Engine, user_id: uuid.UUID) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text("SELECT display_name FROM security.users WHERE user_id = :u"), {"u": user_id}
            ).scalar_one()
        )


async def _wait_for(predicate: Any, what: str) -> None:
    deadline = time.monotonic() + _BOUND
    while time.monotonic() < deadline:
        if predicate():
            return
        await anyio.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


def _run(
    postgres_engine: Engine,
    app_engine: Engine,
    user_id: uuid.UUID,
    *,
    holder_path: str,
    waiters: int,
    engine_route: bool = False,
) -> list[tuple[str, int, Any]]:
    state = _State()
    app = _build_app(app_engine, user_id, state)
    name = app_engine.application_name  # type: ignore[attr-defined]
    results: list[tuple[str, int, Any]] = []

    async def main() -> None:
        with anyio.fail_after(_BOUND * 3):
            await _call(app, "/test-configure", [])
            async with anyio.create_task_group() as group:
                try:
                    group.start_soon(_call, app, holder_path, results)
                    if engine_route:
                        assert await anyio.to_thread.run_sync(state.locked_thread.wait, _BOUND)
                    else:
                        with anyio.fail_after(_BOUND):
                            await state.locked.wait()
                    for _ in range(waiters):
                        group.start_soon(_call, app, "/test-waiter", results)
                    await _wait_for(
                        lambda: _waiting_on_lock(postgres_engine, name) >= waiters,
                        "the waiters to block on the lock",
                    )
                    limiter = anyio.to_thread.current_default_thread_limiter()
                    # every default token is held by a waiter (or the engine route's own handler)
                    assert limiter.total_tokens == _TOKENS
                    assert limiter.borrowed_tokens == _TOKENS
                    assert limiter is not finalizer_limiter()
                    assert finalizer_limiter().total_tokens == FINALIZER_LIMITER_TOKENS
                    state.release.set()
                    state.release_thread.set()
                finally:
                    state.release.set()
                    state.release_thread.set()

    # A regression would leave threads blocked on a lock nobody releases, and AnyIO cannot abandon
    # them. The watchdog terminates the application's backends so the run fails instead of hanging.
    watchdog = threading.Timer(_BOUND * 2, _terminate, args=(postgres_engine, name))
    watchdog.start()
    try:
        anyio.run(main)
    finally:
        watchdog.cancel()
        _terminate(postgres_engine, name)
    return results


def test_the_app_wide_finalizer_commits_while_the_default_limiter_is_exhausted(
    postgres_engine: Engine, app_engine: Engine, locked_user: tuple[uuid.UUID, str]
) -> None:
    user_id, _ = locked_user
    results = _run(
        postgres_engine, app_engine, user_id, holder_path="/test-holder/commit", waiters=_TOKENS
    )
    assert sorted(path for path, _, _ in results) == sorted(
        ["/test-holder/commit"] + ["/test-waiter"] * _TOKENS
    )
    assert all(status == 200 for _, status, _ in results), results
    # The commit released the lock, and each waiter saw the committed value.
    assert all(_MARKER.encode() in body for path, _, body in results if path == "/test-waiter")
    assert _name(postgres_engine, user_id) == _MARKER


def test_the_app_wide_finalizer_rolls_back_while_the_default_limiter_is_exhausted(
    postgres_engine: Engine, app_engine: Engine, locked_user: tuple[uuid.UUID, str]
) -> None:
    user_id, original = locked_user
    results = _run(
        postgres_engine, app_engine, user_id, holder_path="/test-holder/rollback", waiters=_TOKENS
    )
    by_path = {path: status for path, status, _ in results}
    assert by_path["/test-holder/rollback"] == 400  # the holder's own ValueError, mapped as usual
    waiters = [(status, body) for path, status, body in results if path == "/test-waiter"]
    assert len(waiters) == _TOKENS and all(status == 200 for status, _ in waiters)
    assert all(original.encode() in body for _, body in waiters)  # nothing was committed
    assert _name(postgres_engine, user_id) == original


def test_an_engine_backed_route_ends_its_transaction_early_on_its_own_thread(
    postgres_engine: Engine, app_engine: Engine, locked_user: tuple[uuid.UUID, str]
) -> None:
    """The route's handler holds one of the three default tokens; the others are held by waiters.
    `end_request_transaction` commits on the handler's own thread, so it needs no further token."""
    user_id, _ = locked_user
    results = _run(
        postgres_engine,
        app_engine,
        user_id,
        holder_path="/test-engine-route",
        waiters=_TOKENS - 1,
        engine_route=True,
    )
    assert all(status == 200 for _, status, _ in results), results
    assert len(results) == _TOKENS
    assert all(_MARKER.encode() in body for path, _, body in results if path == "/test-waiter")
    assert _name(postgres_engine, user_id) == _MARKER
