# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""The request transaction ends before the response (P03-A prerequisite P3, DEF-022).

`commit_request_transaction` is an app-wide, function-scoped dependency: it commits (or rolls back)
the request's transaction after the handler's result is serialized and before the response is
sent. These tests drive `create_app()` with the real `get_connection`, so the real request
transaction, P2 key lock, reservation, command, audit row and receipt are all in play.

- Commit-time failures come from a test-only `DEFERRABLE INITIALLY DEFERRED` trigger on
  `audit.change_log`, keyed by the request's correlation id.
- State at `http.response.start` is read by an outermost ASGI wrapper through a separate connection.
- The only seams replaced are `dnd_ai.api.deps._commit` and `._rollback`.

Every test asserts persisted state as well as the response.
"""

import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.exc import OperationalError

import dnd_ai.api.deps as deps
import dnd_ai.api.memberships as memberships_api
from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_connection, get_engine
from dnd_ai.api.errors import install_error_handlers
from tests.database.test_campaign_owner_gate import Gate, g  # noqa: F401 - fixture used by name
from tests.database.test_campaign_owner_lock_order import (  # noqa: F401 - autouse fixture
    _WAIT_SECONDS,
    _audit,
    _release_everything,
    _status,
)
from tests.database.test_character_reveal_delegation_deadlocks import _blocked_by
from tests.database.test_idempotency_key_lock import (
    _advisory_locks_held,
    _fresh_key,
    _hold_membership,
    _open,
    _receipts,
    _role_active,
    _urls,
)
from tests.factories import make_user, oidc_principal

pytestmark = pytest.mark.database

# --- the commit-failure trigger ------------------------------------------------------------------

# A correlation id whose text starts with this marker fails at COMMIT; the next four hex digits pick
# the SQLSTATE. The ids are valid UUIDs, as the correlation header requires.
_FAIL_PREFIX = "fa11ed00"
_CODES = {"0001": "23000", "0002": "23505", "0003": "23514", "0004": "40P01"}


def _failing_correlation_id(code: str) -> str:
    assert code in _CODES
    return f"{_FAIL_PREFIX}-{code}-4000-8000-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def commit_failures(postgres_engine: Engine) -> Iterator[None]:
    function_body = "\n".join(
        [
            "CREATE FUNCTION audit.p3_test_commit_failure() RETURNS trigger LANGUAGE plpgsql AS $$",
            "DECLARE code text;",
            "BEGIN",
            f"  IF NEW.correlation_id::text LIKE '{_FAIL_PREFIX}-%' THEN",
            "    code := CASE substr(NEW.correlation_id::text, 10, 4)",
            "      WHEN '0001' THEN '23000' WHEN '0002' THEN '23505'",
            "      WHEN '0003' THEN '23514' ELSE '40P01' END;",
            "    RAISE EXCEPTION 'p3 test commit failure' USING ERRCODE = code;",
            "  END IF;",
            "  RETURN NULL;",
            "END $$",
        ]
    )
    with postgres_engine.begin() as connection:
        connection.execute(text(function_body))
        connection.execute(
            text("""
                CREATE CONSTRAINT TRIGGER p3_test_commit_failure
                AFTER INSERT ON audit.change_log
                DEFERRABLE INITIALLY DEFERRED
                FOR EACH ROW EXECUTE FUNCTION audit.p3_test_commit_failure()
            """)
        )
    try:
        yield
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                text("DROP TRIGGER IF EXISTS p3_test_commit_failure ON audit.change_log")
            )
            connection.execute(text("DROP FUNCTION IF EXISTS audit.p3_test_commit_failure()"))


# --- observing the response start ----------------------------------------------------------------


class _Observer:
    """An outermost ASGI wrapper: runs `probe` when the response starts, and records every message
    type that was sent."""

    def __init__(self, app: Any, probe: Callable[[], dict[str, Any]]) -> None:
        self.app = app
        self.probe = probe
        self.at_start: list[dict[str, Any]] = []
        self.sent: list[str] = []

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        async def observed(message: Any) -> None:
            self.sent.append(message["type"])
            if message["type"] == "http.response.start":
                self.at_start.append(self.probe())
            await send(message)

        await self.app(scope, receive, observed)


def _probe(engine: Engine, g: Gate, *, key: str | None, correlation_id: str | None = None):  # type: ignore[no-untyped-def]
    def run() -> dict[str, Any]:
        with engine.connect() as connection:
            audit = 0
            if correlation_id is not None:
                audit = int(
                    connection.execute(
                        text("SELECT count(*) FROM audit.change_log WHERE correlation_id = :c"),
                        {"c": correlation_id},
                    ).scalar_one()
                )
        return {
            "player_open": _open(engine, g.player),
            "role_active": _role_active(engine, g.player_role),
            "audit": audit,
            "receipt": _receipts(engine, g, key) if key else [],
            "advisory_locks": _advisory_locks_held(engine),
        }

    return run


def _client(
    engine: Engine,
    user_id: uuid.UUID,
    *,
    app_engine: Engine | None = None,
    observer: Callable[[Any], _Observer] | None = None,
    configure: Callable[[FastAPI], None] | None = None,
) -> tuple[TestClient, list[_Observer]]:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: app_engine or engine
    app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
    if configure is not None:
        configure(app)
    observers: list[_Observer] = []
    asgi: Any = app
    if observer is not None:
        wrapper = observer(app)
        observers.append(wrapper)
        asgi = wrapper
    return TestClient(asgi, raise_server_exceptions=False), observers


def _post(
    client: TestClient, url: str, *, key: str | None = None, correlation_id: str | None = None
) -> Any:
    headers: dict[str, str] = {}
    if key:
        headers["Idempotency-Key"] = key
    if correlation_id:
        headers["X-Correlation-Id"] = correlation_id
    return client.post(url, json={}, headers=headers)


def _audit_for(engine: Engine, correlation_id: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM audit.change_log WHERE correlation_id = :c"),
                {"c": correlation_id},
            ).scalar_one()
        )


def _observed_end(
    engine: Engine, g: Gate, url: str, key: str | None, correlation_id: str
) -> tuple[Any, dict[str, Any]]:
    client, observers = _client(
        engine,
        g.o1_user_id,
        observer=lambda app: _Observer(
            app, _probe(engine, g, key=key, correlation_id=correlation_id)
        ),
    )
    with client:
        response = _post(client, url, key=key, correlation_id=correlation_id)
    assert len(observers[0].at_start) == 1
    return response, observers[0].at_start[0]


# --- T1: a commit failure is non-success and nothing persists --------------------------------------


@pytest.mark.parametrize(
    ("code", "status"), [("0001", 500), ("0002", 409), ("0003", 400), ("0004", 500)]
)
def test_a_commit_time_failure_is_never_a_success_and_persists_nothing(
    postgres_engine: Engine, commit_failures: None, g: Gate, code: str, status: int
) -> None:
    key = _fresh_key("t1")
    correlation_id = _failing_correlation_id(code)
    response, at_start = _observed_end(
        postgres_engine, g, _urls(g)["end_player"], key, correlation_id
    )
    assert response.status_code == status, response.text
    assert not (200 <= response.status_code < 300)
    for state in (
        at_start,
        _probe(postgres_engine, g, key=key, correlation_id=correlation_id)(),
    ):
        assert state["player_open"] and state["role_active"]
        assert state["audit"] == 0
        assert state["receipt"] == []
    assert "end_campaign_membership" not in _audit(postgres_engine, g)


def test_an_unkeyed_commit_time_deadlock_error_is_not_a_success(
    postgres_engine: Engine, commit_failures: None, g: Gate
) -> None:
    correlation_id = _failing_correlation_id("0004")
    response, at_start = _observed_end(
        postgres_engine, g, _urls(g)["end_player"], None, correlation_id
    )
    assert response.status_code == 500
    assert at_start["player_open"] and at_start["audit"] == 0
    assert _open(postgres_engine, g.player) and "end_campaign_membership" not in _audit(
        postgres_engine, g
    )


# --- T2 and T4: visible before the response, and the key lock is released ---------------------------


@pytest.mark.parametrize("which", ["end_player", "revoke_player"])
def test_a_2xx_is_sent_only_after_the_commit_and_the_key_lock_is_free(
    postgres_engine: Engine, g: Gate, which: str
) -> None:
    key = _fresh_key("t2")
    correlation_id = str(uuid.uuid4())
    response, at_start = _observed_end(postgres_engine, g, _urls(g)[which], key, correlation_id)
    assert response.status_code == 200, response.text
    if which == "end_player":
        assert not at_start["player_open"]
    else:
        assert not at_start["role_active"]
    assert at_start["audit"] == 1
    assert at_start["receipt"] == [(200, True)]
    assert at_start["advisory_locks"] == 0  # P2's key lock was released by the commit
    with postgres_engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT response_status_code, response_body FROM security.idempotent_requests "
                "WHERE campaign_id = :c AND idempotency_key = :k"
            ),
            {"c": g.campaign_id, "k": key},
        ).one()
    assert stored[0] == 200 and stored[1] == response.json()


# --- T3: a keyed retry after a failure ------------------------------------------------------------


def test_a_keyed_retry_after_a_commit_failure_succeeds_once_and_then_replays(
    postgres_engine: Engine, commit_failures: None, g: Gate
) -> None:
    key = _fresh_key("t3")
    url = _urls(g)["end_player"]
    first, _ = _observed_end(postgres_engine, g, url, key, _failing_correlation_id("0001"))
    assert first.status_code == 500
    assert _receipts(postgres_engine, g, key) == []
    client, _ = _client(postgres_engine, g.o1_user_id)
    with client:
        retry = _post(client, url, key=key)
        again = _post(client, url, key=key)
    assert retry.status_code == 200 and again.status_code == 200
    assert again.json() == retry.json()
    assert not _open(postgres_engine, g.player)
    assert _audit(postgres_engine, g).get("end_campaign_membership") == 1
    assert _receipts(postgres_engine, g, key) == [(200, True)]


def test_a_handler_failure_rolls_back_and_the_key_then_works_on_another_target(
    postgres_engine: Engine, g: Gate, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = _fresh_key("r1")
    urls = _urls(g)
    real = memberships_api.record_change_log
    calls = {"n": 0}

    def fail_once(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("deliberate failure after the reservation")
        return real(*args, **kwargs)

    monkeypatch.setattr(memberships_api, "record_change_log", fail_once)
    correlation_id = str(uuid.uuid4())
    response, at_start = _observed_end(postgres_engine, g, urls["end_player"], key, correlation_id)
    assert response.status_code == 400
    assert at_start["player_open"] and at_start["receipt"] == [] and at_start["audit"] == 0
    assert at_start["advisory_locks"] == 0  # rolled back: the key lock is free
    assert _open(postgres_engine, g.player)

    client, _ = _client(postgres_engine, g.o1_user_id)
    with client:
        other = _post(client, urls["end_o2"], key=key)
    assert other.status_code == 200
    assert not _open(postgres_engine, g.o2) and _open(postgres_engine, g.player)
    assert _receipts(postgres_engine, g, key) == [(200, True)]


# --- T10: an uncertain commit ---------------------------------------------------------------------


def test_an_uncertain_commit_is_a_500_and_a_keyed_retry_replays_the_stored_receipt(
    postgres_engine: Engine, g: Gate, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = _fresh_key("t10")
    url = _urls(g)["end_player"]
    real_commit = deps._commit

    def lost_acknowledgement(connection: Connection) -> None:
        real_commit(connection)  # PostgreSQL commits ...
        connection.invalidate()  # ... then the acknowledgement is lost
        raise OperationalError("COMMIT", {}, Exception("connection lost"))

    monkeypatch.setattr(deps, "_commit", lost_acknowledgement)
    correlation_id = str(uuid.uuid4())
    response, at_start = _observed_end(postgres_engine, g, url, key, correlation_id)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error" or "internal_error" in response.text
    # The transaction did commit, and the key lock was released by that commit.
    assert not at_start["player_open"]
    assert at_start["audit"] == 1 and at_start["receipt"] == [(200, True)]
    assert at_start["advisory_locks"] == 0
    with postgres_engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT response_body FROM security.idempotent_requests "
                "WHERE campaign_id = :c AND idempotency_key = :k"
            ),
            {"c": g.campaign_id, "k": key},
        ).scalar_one()

    monkeypatch.setattr(deps, "_commit", real_commit)
    client, _ = _client(postgres_engine, g.o1_user_id)
    with client:
        retry = _post(client, url, key=key)
    assert retry.status_code == 200 and retry.json() == stored
    assert _audit(postgres_engine, g).get("end_campaign_membership") == 1
    assert _receipts(postgres_engine, g, key) == [(200, True)]
    assert _advisory_locks_held(postgres_engine) == 0


# --- T5 and T7: cleanup with a one-connection pool, and a failed rollback ---------------------------


class _PoolLog:
    """Pool `invalidate` and `checkin` events, in the order they happened."""

    def __init__(self, engine: Engine) -> None:
        self.events: list[str] = []
        event.listen(engine, "checkin", lambda *_: self.events.append("checkin"))
        event.listen(engine, "invalidate", lambda *_: self.events.append("invalidate"))


@pytest.fixture
def small_engine(postgres_engine: Engine) -> Iterator[Engine]:
    """The application's own pool: one connection, a named application, so its sessions can be told
    from the test's."""
    name = f"p3app{uuid.uuid4().hex[:8]}"
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


def _app_sessions(engine: Engine, application_name: str) -> list[tuple[str, str]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT state, coalesce(wait_event_type, '') FROM pg_stat_activity "
                "WHERE application_name = :n"
            ),
            {"n": application_name},
        ).all()
    return [(r[0], r[1]) for r in rows]


def test_a_one_connection_pool_is_returned_after_every_kind_of_ending(
    postgres_engine: Engine,
    small_engine: Engine,
    commit_failures: None,
    g: Gate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = _urls(g)
    client, _ = _client(postgres_engine, g.o1_user_id, app_engine=small_engine)
    with client:
        # a success
        assert _post(client, urls["end_player"], key=_fresh_key("a")).status_code == 200
        assert small_engine.pool.checkedout() == 0  # type: ignore[attr-defined]
        # a handler error: an unknown membership is a 404
        missing = f"/campaigns/{g.campaign_id}/memberships/{uuid.uuid4()}/end"
        assert _post(client, missing).status_code == 404
        assert small_engine.pool.checkedout() == 0  # type: ignore[attr-defined]
        # a commit failure
        failing = _post(client, urls["end_o2"], correlation_id=_failing_correlation_id("0004"))
        assert failing.status_code == 500
        assert small_engine.pool.checkedout() == 0  # type: ignore[attr-defined]

        # a rollback failure
        def broken_rollback(connection: Connection) -> None:
            raise OperationalError("ROLLBACK", {}, Exception("connection lost"))

        monkeypatch.setattr(deps, "_rollback", broken_rollback)
        assert _post(client, missing).status_code == 404
        monkeypatch.undo()
        assert small_engine.pool.checkedout() == 0  # type: ignore[attr-defined]
        # and the pool still serves the next request
        assert _post(client, urls["end_o2"], key=_fresh_key("b")).status_code == 200
    assert not _open(postgres_engine, g.player) and not _open(postgres_engine, g.o2)


def test_a_failed_rollback_keeps_the_original_error_and_ends_the_session(
    postgres_engine: Engine,
    small_engine: Engine,
    g: Gate,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    key = _fresh_key("t7")
    url = _urls(g)["end_player"]
    name = small_engine.application_name  # type: ignore[attr-defined]
    pool_log = _PoolLog(small_engine)

    real = memberships_api.record_change_log

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("deliberate failure after the reservation")

    monkeypatch.setattr(memberships_api, "record_change_log", fail)

    def broken_rollback(connection: Connection) -> None:
        raise OperationalError("ROLLBACK", {"secret": "do-not-log"}, Exception("secret detail"))

    monkeypatch.setattr(deps, "_rollback", broken_rollback)
    correlation_id = str(uuid.uuid4())

    def probe() -> dict[str, Any]:
        state = _probe(postgres_engine, g, key=key, correlation_id=correlation_id)()
        state["app_sessions"] = _app_sessions(postgres_engine, name)
        state["events"] = list(pool_log.events)
        return state

    client, observers = _client(
        postgres_engine,
        g.o1_user_id,
        app_engine=small_engine,
        observer=lambda app: _Observer(app, probe),
    )
    with caplog.at_level(logging.ERROR, logger="dnd_ai.api.deps"), client:
        response = _post(client, url, key=key, correlation_id=correlation_id)
    assert response.status_code == 400  # the handler's own error, not the rollback's
    at_start = observers[0].at_start[0]
    assert at_start["advisory_locks"] == 0
    assert at_start["app_sessions"] == []  # the invalidated session ended; PostgreSQL rolled back
    assert at_start["player_open"] and at_start["receipt"] == [] and at_start["audit"] == 0
    # the pool saw the invalidate before the connection was returned
    assert pool_log.events.index("invalidate") < pool_log.events.index("checkin")
    assert small_engine.pool.checkedout() == 0  # type: ignore[attr-defined]
    messages = [r.getMessage() for r in caplog.records if r.name == "dnd_ai.api.deps"]
    assert messages == ["request transaction rollback failed: OperationalError"]
    assert "secret" not in "".join(messages)
    assert real is not fail  # (the unpatched command stays reachable for later tests)


# --- T6: a serialization failure rolls back -----------------------------------------------------


class _Declared(BaseModel):
    user_id: uuid.UUID


def test_a_response_validation_failure_after_a_write_persists_nothing(
    postgres_engine: Engine, small_engine: Engine, g: Gate
) -> None:
    name = f"s1-{uuid.uuid4().hex[:8]}"

    def configure(app: FastAPI) -> None:
        @app.post("/test-s1/{display_name}", response_model=_Declared)
        def _s1(
            display_name: str, connection: Annotated[Connection, Depends(get_connection)]
        ) -> dict[str, str]:
            make_user(connection, display_name)
            return {"user_id": "not-a-uuid"}

    client, _ = _client(postgres_engine, g.o1_user_id, app_engine=small_engine, configure=configure)
    with client:
        response = client.post(f"/test-s1/{name}")
    assert response.status_code == 500
    with postgres_engine.connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM security.users WHERE display_name = :n"), {"n": name}
        ).scalar_one()
    assert count == 0
    assert small_engine.pool.checkedout() == 0  # type: ignore[attr-defined]


# --- T14: guards --------------------------------------------------------------------------------


def test_an_app_without_the_commit_dependency_refuses_before_any_statement(
    postgres_engine: Engine,
) -> None:
    statements: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        statements.append(statement)

    event.listen(postgres_engine, "before_cursor_execute", record)
    try:
        app = FastAPI()
        app.dependency_overrides[get_engine] = lambda: postgres_engine

        @app.get("/probe")
        def _probe_route(
            connection: Annotated[Connection, Depends(get_connection)],
        ) -> dict[str, int]:
            return {"ok": 1}

        install_error_handlers(app)
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/probe")
    finally:
        event.remove(postgres_engine, "before_cursor_execute", record)
    assert response.status_code == 500
    assert statements == []


def test_a_request_cannot_open_a_second_request_connection(
    postgres_engine: Engine, small_engine: Engine, g: Gate
) -> None:
    def configure(app: FastAPI) -> None:
        @app.get("/test-twice")
        def _twice(
            first: Annotated[Connection, Depends(get_connection)],
            second: Annotated[Connection, Depends(get_connection, use_cache=False)],
        ) -> dict[str, int]:
            return {"ok": 1}

    client, _ = _client(postgres_engine, g.o1_user_id, app_engine=small_engine, configure=configure)
    with client:
        response = client.get("/test-twice")
    assert response.status_code == 500
    assert small_engine.pool.checkedout() == 0  # type: ignore[attr-defined]


# --- T9: DEF-019, a different-key commit-time deadlock, observed (not fixed by P3) ----------------


def test_def019_two_keyed_ends_by_one_owner_deadlock_and_the_loser_persists_nothing(
    postgres_engine: Engine, g: Gate
) -> None:
    """Two keyed ends by the same owner with different keys, on the player's and O2's memberships.
    The first is held at the player's membership row; the second waits behind it; releasing the hold
    makes them deadlock (each holds the campaign `KEY SHARE` from its reservation and wants the
    campaign `FOR UPDATE`). Exactly one request succeeds. The other is a non-2xx with no end, no
    audit row and no receipt. Before A3a the second waited at COMMIT for the retention trigger's
    campaign lock; `end_campaign_membership` now takes that lock itself, earlier, so the wait and
    the deadlock moved into the command and the outcome is the same. This test changes with DEF-019."""
    urls = _urls(g)
    keys = (_fresh_key("def19-one"), _fresh_key("def19-two"))
    correlations = (str(uuid.uuid4()), str(uuid.uuid4()))
    results: dict[int, Any] = {}
    errors: list[BaseException] = []

    def run(index: int, url: str) -> None:
        try:
            client, _ = _client(postgres_engine, g.o1_user_id)
            with client:
                results[index] = _post(
                    client, url, key=keys[index], correlation_id=correlations[index]
                )
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    deadlocks_before = _deadlocks(postgres_engine)
    hold = _hold_membership(postgres_engine, g.player)
    threads = [threading.Thread(target=run, args=(0, urls["end_player"]), daemon=True)]
    threads[0].start()
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline and _blocked_by(postgres_engine, hold.pid) < 1:
        assert 0 not in results, getattr(results.get(0), "text", errors)
        time.sleep(0.02)
    threads.append(threading.Thread(target=run, args=(1, urls["end_o2"]), daemon=True))
    threads[1].start()
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline and _lock_waiters(postgres_engine) < 2:
        assert 1 not in results, getattr(results.get(1), "text", errors)
        time.sleep(0.02)
    # The first waits on the hold; the second waits on the first (since A3a at the end command's
    # explicit campaign lock, where it used to wait at COMMIT).
    assert _lock_waiters(postgres_engine) >= 2, "the second request never waited on the first"
    hold.release()
    for thread in threads:
        thread.join(timeout=_WAIT_SECONDS)
        assert not thread.is_alive()
    assert not errors, errors

    statuses = [results[0].status_code, results[1].status_code]
    assert sum(1 for s in statuses if 200 <= s < 300) == 1, statuses
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and _deadlocks(postgres_engine) < deadlocks_before + 1:
        time.sleep(0.1)
    assert _deadlocks(postgres_engine) == deadlocks_before + 1

    memberships = (g.player, g.o2)
    for index in (0, 1):
        ended = not _open(postgres_engine, memberships[index])
        audited = _audit_for(postgres_engine, correlations[index])
        receipt = _receipts(postgres_engine, g, keys[index])
        if 200 <= statuses[index] < 300:
            assert ended and audited == 1 and receipt == [(200, True)]
        else:
            assert not ended and audited == 0 and receipt == []


def _lock_waiters(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("""
                    SELECT count(*) FROM pg_stat_activity
                    WHERE wait_event_type = 'Lock' AND datname = current_database()
                """)
            ).scalar_one()
        )


def _deadlocks(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT deadlocks FROM pg_stat_database WHERE datname = current_database()")
            ).scalar_one()
        )
