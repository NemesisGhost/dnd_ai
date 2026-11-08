# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""A cancelled request and the request transaction (P03-A prerequisite P3, DEF-022).

The real membership-end route on `create_app()` is called directly under anyio (not through
`TestClient`), with a one-connection application pool whose pool and connection events are
recorded. The COMMIT or ROLLBACK is held in the worker thread by the barrier protocol, and a
cancellation is delivered while it is held.

- T11a: cancelled during the handler, no seam held, the garbage collector disabled.
- T11c: (1) COMMIT held; (2) ROLLBACK held after a handler error; (3) the handler blocked on a held
  row, cancelled, the row released, ROLLBACK held; (4) as (3) with the rollback raising.

While held, a separate connection proves the request connection is not closed, one is checked out,
nothing was returned to the pool, the backend is `idle in transaction` and the P2 key lock is still
granted. After release: the operation's exit precedes the pool check-in (and the invalidate precedes
both in the failing case), no ASGI message was sent, and the key lock and the session are gone.
"""

import gc
import logging
import time
import uuid
from collections.abc import Iterator
from typing import Any

import anyio
import pytest
from sqlalchemy import Engine, create_engine, event, text

import dnd_ai.api.deps as deps
import dnd_ai.api.memberships as memberships_api
from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from tests.database.test_campaign_owner_gate import Gate, g  # noqa: F401 - fixture used by name
from tests.database.test_campaign_owner_lock_order import (  # noqa: F401 - autouse fixture
    _release_everything,
)
from tests.database.test_character_reveal_delegation_deadlocks import _blocked_by
from tests.database.test_idempotency_key_lock import (
    _advisory_locks_held,
    _audit,
    _fresh_key,
    _hold_membership,
    _key_lock_ids,
    _key_lock_state,
    _open,
    _receipts,
    _urls,
)
from tests.factories import oidc_principal
from tests.unit.test_request_transaction_lifecycle import _Barrier, _Events

pytestmark = pytest.mark.database

_BOUND = 30.0


@pytest.fixture
def small_engine(postgres_engine: Engine) -> Iterator[Engine]:
    name = f"p3cx{uuid.uuid4().hex[:8]}"
    engine = create_engine(
        postgres_engine.url,
        pool_size=1,
        max_overflow=0,
        pool_timeout=5,
        connect_args={"application_name": name},
    )
    engine.application_name = name  # type: ignore[attr-defined]
    try:
        yield engine
    finally:
        engine.dispose()


class _Instrument:
    """Records the pool's `checkin` and `invalidate` into the shared event list and captures the
    request's `Connection`."""

    def __init__(self, engine: Engine, events: _Events) -> None:
        self.connections: list[Any] = []
        event.listen(
            engine, "engine_connect", lambda connection: self.connections.append(connection)
        )
        event.listen(engine, "checkin", lambda *_: events.add("checkin"))
        event.listen(engine, "invalidate", lambda *_: events.add("invalidate"))


def _sessions(engine: Engine, name: str) -> list[tuple[str, int]]:
    with engine.connect() as connection:
        return [
            (str(r[0]), int(r[1]))
            for r in connection.execute(
                text("SELECT state, pid FROM pg_stat_activity WHERE application_name = :n"),
                {"n": name},
            )
        ]


class _Call:
    """One ASGI request to the real app, called directly."""

    def __init__(self, engine: Engine, app_engine: Engine, g: Gate, url: str, key: str) -> None:
        self.app = create_app()
        self.app.dependency_overrides[get_engine] = lambda: app_engine
        self.app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(
            g.o1_user_id
        )
        self.url = url
        self.key = key
        self.sent: list[str] = []
        self.scope: anyio.CancelScope | None = None
        self.finished = False

    async def run(self) -> None:
        body = b"{}"
        asgi_scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "path": self.url,
            "raw_path": self.url.encode(),
            "root_path": "",
            "scheme": "http",
            "query_string": b"",
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"idempotency-key", self.key.encode()),
            ],
            "client": ("testclient", 1),
            "server": ("testserver", 80),
        }
        delivered = False

        async def receive() -> dict[str, Any]:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            await anyio.sleep_forever()
            raise AssertionError("unreachable")

        async def send(message: dict[str, Any]) -> None:
            self.sent.append(message["type"])

        try:
            with anyio.CancelScope() as scope:
                self.scope = scope
                await self.app(asgi_scope, receive, send)
        finally:
            self.finished = True


async def _until(predicate: Any, what: str) -> None:
    deadline = time.monotonic() + _BOUND
    while time.monotonic() < deadline:
        if predicate():
            return
        await anyio.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


def _assert_held_state(
    engine: Engine,
    small: Engine,
    instrument: _Instrument,
    events: _Events,
    ids: tuple[int, int],
) -> int:
    """The request connection is neither closed nor returned, its backend is idle in transaction and
    holds the key lock."""
    name = small.application_name  # type: ignore[attr-defined]
    assert len(instrument.connections) == 1
    assert instrument.connections[0].closed is False
    assert small.pool.checkedout() == 1  # type: ignore[attr-defined]
    assert "checkin" not in events.snapshot()
    sessions = _sessions(engine, name)
    assert len(sessions) == 1 and sessions[0][0] == "idle in transaction", sessions
    state = _key_lock_state(engine, ids)
    assert [(pid, granted) for pid, granted, _ in state] == [(sessions[0][1], True)]
    return sessions[0][1]


def _assert_released(engine: Engine, small: Engine, call: _Call, ids: tuple[int, int]) -> None:
    assert call.sent == []  # no response, not even a start
    assert _key_lock_state(engine, ids) == []
    assert _advisory_locks_held(engine) == 0
    assert _sessions(engine, small.application_name) == [] or all(  # type: ignore[attr-defined]
        state != "idle in transaction"
        for state, _ in _sessions(engine, small.application_name)  # type: ignore[attr-defined]
    )
    assert small.pool.checkedout() == 0  # type: ignore[attr-defined]


def _case(
    postgres_engine: Engine,
    small: Engine,
    g: Gate,
    monkeypatch: pytest.MonkeyPatch,
    *,
    op: str,
    fail: bool = False,
    handler_error: bool = False,
    block_handler: bool = False,
) -> tuple[_Call, _Events, str]:
    """Runs one case to completion and returns the call, the event list and the key."""
    key = _fresh_key("cx")
    events = _Events()
    instrument = _Instrument(small, events)
    barrier = _Barrier(monkeypatch, op, events, hold=True, fail=fail)
    if handler_error:

        def broken(*args: Any, **kwargs: Any) -> Any:
            raise ValueError("deliberate failure after the reservation")

        monkeypatch.setattr(memberships_api, "record_change_log", broken)
    call = _Call(postgres_engine, small, g, _urls(g)["end_player"], key)
    ids = _key_lock_ids(postgres_engine, g, key)
    hold = _hold_membership(postgres_engine, g.player) if block_handler else None

    async def main() -> None:
        try:
            with anyio.fail_after(_BOUND * 3):
                async with anyio.create_task_group() as group:
                    group.start_soon(call.run)
                    if hold is not None:
                        await _until(
                            lambda: _blocked_by(postgres_engine, hold.pid) >= 1,
                            "the handler to block on the held row",
                        )
                        assert call.scope is not None
                        call.scope.cancel()
                        await anyio.sleep(0.25)
                        hold.release()
                    assert await anyio.to_thread.run_sync(barrier.entered.wait, _BOUND), (
                        f"{op} never started"
                    )
                    if hold is None:
                        assert call.scope is not None
                        call.scope.cancel()
                    await anyio.sleep(0.3)  # settle: an eager close would have happened by now
                    _assert_held_state(postgres_engine, small, instrument, events, ids)
                    barrier.release.set()
        finally:
            barrier.release.set()
            if hold is not None:
                hold.release()

    anyio.run(main)
    assert call.finished
    _assert_released(postgres_engine, small, call, ids)
    return call, events, key


def test_t11c_1_a_cancellation_during_commit_lets_the_commit_finish_and_sends_nothing(
    postgres_engine: Engine, small_engine: Engine, g: Gate, monkeypatch: pytest.MonkeyPatch
) -> None:
    call, events, key = _case(postgres_engine, small_engine, g, monkeypatch, op="commit")
    order = events.snapshot()
    assert order == ["commit-enter", "commit-exit", "checkin"], order
    # The COMMIT ran to completion: the end, its audit row and its receipt are committed.
    assert not _open(postgres_engine, g.player)
    assert _audit(postgres_engine, g).get("end_campaign_membership") == 1
    assert _receipts(postgres_engine, g, key) == [(200, True)]


def test_t11c_2_a_cancellation_during_rollback_after_a_handler_error_sends_no_error_response(
    postgres_engine: Engine, small_engine: Engine, g: Gate, monkeypatch: pytest.MonkeyPatch
) -> None:
    call, events, key = _case(
        postgres_engine, small_engine, g, monkeypatch, op="rollback", handler_error=True
    )
    assert events.snapshot() == ["rollback-enter", "rollback-exit", "checkin"]
    assert _open(postgres_engine, g.player)
    assert "end_campaign_membership" not in _audit(postgres_engine, g)
    assert _receipts(postgres_engine, g, key) == []


def test_t11c_3_a_cancelled_blocked_handler_is_rolled_back_after_the_row_is_released(
    postgres_engine: Engine, small_engine: Engine, g: Gate, monkeypatch: pytest.MonkeyPatch
) -> None:
    call, events, key = _case(
        postgres_engine, small_engine, g, monkeypatch, op="rollback", block_handler=True
    )
    assert events.snapshot() == ["rollback-enter", "rollback-exit", "checkin"]
    assert _open(postgres_engine, g.player)
    assert "end_campaign_membership" not in _audit(postgres_engine, g)
    assert _receipts(postgres_engine, g, key) == []


def test_t11c_4_a_failing_rollback_invalidates_the_connection_before_it_is_returned(
    postgres_engine: Engine,
    small_engine: Engine,
    g: Gate,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR, logger="dnd_ai.api.deps"):
        call, events, key = _case(
            postgres_engine,
            small_engine,
            g,
            monkeypatch,
            op="rollback",
            fail=True,
            block_handler=True,
        )
    assert events.snapshot() == ["rollback-enter", "rollback-exit", "invalidate", "checkin"]
    # The session ended, so PostgreSQL aborted the transaction and released its locks.
    assert _sessions(postgres_engine, small_engine.application_name) == []  # type: ignore[attr-defined]
    assert _open(postgres_engine, g.player)
    assert "end_campaign_membership" not in _audit(postgres_engine, g)
    assert _receipts(postgres_engine, g, key) == []
    messages = [r.getMessage() for r in caplog.records if r.name == "dnd_ai.api.deps"]
    assert messages == ["request transaction rollback failed: OperationalError"]


# --- T11a: a cancellation during the handler cleans up without the garbage collector ----------------


def test_t11a_a_cancellation_during_the_handler_is_rolled_back_by_the_commit_dependency(
    postgres_engine: Engine,
    small_engine: Engine,
    g: Gate,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    key = _fresh_key("t11a")
    rollbacks: list[str] = []
    real_rollback = deps._rollback

    def counting_rollback(connection: Any) -> None:
        rollbacks.append("rollback")
        real_rollback(connection)

    monkeypatch.setattr(deps, "_rollback", counting_rollback)
    call = _Call(postgres_engine, small_engine, g, _urls(g)["end_player"], key)
    ids = _key_lock_ids(postgres_engine, g, key)
    hold = _hold_membership(postgres_engine, g.player)

    async def main() -> None:
        try:
            with anyio.fail_after(_BOUND * 2):
                async with anyio.create_task_group() as group:
                    group.start_soon(call.run)
                    await _until(
                        lambda: _blocked_by(postgres_engine, hold.pid) >= 1,
                        "the handler to block on the held row",
                    )
                    assert call.scope is not None
                    call.scope.cancel()
                    await anyio.sleep(0.25)
                    hold.release()
        finally:
            hold.release()

    gc.collect()
    gc.disable()
    try:
        with caplog.at_level(logging.ERROR, logger="dnd_ai.api.deps"):
            anyio.run(main)
        # Checked without running the collector: a suspended generator's finalization is not
        # what cleaned up.
        assert call.finished
        _assert_released(postgres_engine, small_engine, call, ids)
    finally:
        gc.enable()
    assert rollbacks == ["rollback"]  # once, by the commit dependency
    assert not any("was not ended by its owner" in r.getMessage() for r in caplog.records)
    assert _open(postgres_engine, g.player)
    assert _receipts(postgres_engine, g, key) == []
    assert "end_campaign_membership" not in _audit(postgres_engine, g)
