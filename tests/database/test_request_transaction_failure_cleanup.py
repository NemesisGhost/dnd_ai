"""R01 slice T0 (docs/R01_FRESH_AUTHORIZATION_PLAN_2026-11-12.md, section 6.8): a failed or refused
request-transaction exit never returns a pooled connection that the driver reports in a transaction.

Every test runs against PostgreSQL with a one-connection `QueuePool`, so the second request reuses the
first one's connection whenever the first one returned it to the pool. The backend pid of each request
is recorded. The only seams replaced are `dnd_ai.api.deps._commit`'s caller side (a `commit` event
listener on the engine) and `dnd_ai.api.deps._driver_rollback`.
"""

import threading
import time
from collections.abc import Iterator
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, create_engine, event, text

import dnd_ai.api.deps as deps
from dnd_ai.api.errors import install_error_handlers

pytestmark = pytest.mark.database

SCHEMA = "t0_cleanup"
_WAIT = 15.0


class _Guard(RuntimeError):
    """Stands in for the commit guard's error until S1 (a plain RuntimeError, as S1 pins)."""


@pytest.fixture
def scratch(postgres_engine: Engine) -> Iterator[Engine]:
    admin = postgres_engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        connection.execute(text(f"CREATE TABLE {SCHEMA}.marker (n int)"))
        connection.execute(
            text(f"""
                CREATE FUNCTION {SCHEMA}.fail_at_commit() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                  IF NEW.n = 13 THEN
                    RAISE EXCEPTION 't0 test commit failure' USING ERRCODE = '23000';
                  END IF;
                  RETURN NULL;
                END $$
            """)
        )
        connection.execute(
            text(f"""
                CREATE CONSTRAINT TRIGGER fail_at_commit AFTER INSERT ON {SCHEMA}.marker
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.fail_at_commit()
            """)
        )
    try:
        yield postgres_engine
    finally:
        with admin.connect() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))


def _app(
    engine: Engine, *, gate: "_Gate | None" = None, seen: list[tuple[int, str]] | None = None
) -> FastAPI:
    app = FastAPI(dependencies=[Depends(deps.commit_request_transaction, scope="function")])
    install_error_handlers(app)

    @app.post("/write/{n}")
    def write(
        n: int, connection: Annotated[Connection, Depends(deps.get_connection)]
    ) -> dict[str, Any]:
        connection.execute(text(f"INSERT INTO {SCHEMA}.marker VALUES (:n)"), {"n": n})
        pid, started = _identity(connection)
        if seen is not None:
            seen.append((pid, started))
        if gate is not None:
            gate.reached(pid, started)
        return {"pid": pid, "started": started}

    @app.post("/early/{n}")
    def early(
        n: int, request: Request, connection: Annotated[Connection, Depends(deps.get_connection)]
    ) -> dict[str, Any]:
        connection.execute(text(f"INSERT INTO {SCHEMA}.marker VALUES (:n)"), {"n": n})
        pid, started = _identity(connection)
        if seen is not None:
            seen.append((pid, started))
        deps.end_request_transaction(request)
        return {"pid": pid, "started": started}

    app.dependency_overrides[deps.get_engine] = lambda: engine
    return app


def _identity(connection: Connection) -> tuple[int, str]:
    """A backend's identity: its pid and start time (Windows reuses pids at once, so a pid alone
    cannot tell a replacement connection from the old one)."""
    row = connection.execute(
        text(
            "SELECT pg_backend_pid(), backend_start::text FROM pg_stat_activity "
            "WHERE pid = pg_backend_pid()"
        )
    ).one()
    return int(row[0]), str(row[1])


class _Gate:
    """Holds the handler (after its write) until released, so a test can act on its backend."""

    def __init__(self) -> None:
        self.pid: int | None = None
        self.started: str | None = None
        self.entered = threading.Event()
        self.release = threading.Event()

    def reached(self, pid: int, started: str) -> None:
        if self.entered.is_set():  # only the first request is held
            return
        self.pid = pid
        self.started = started
        self.entered.set()
        assert self.release.wait(_WAIT)


def _rows(engine: Engine) -> list[int]:
    with engine.connect() as connection:
        return [
            int(r[0])
            for r in connection.execute(text(f"SELECT n FROM {SCHEMA}.marker ORDER BY n")).all()
        ]


def _idle_in_transaction(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND state LIKE 'idle in transaction%'"
                )
            ).scalar_one()
        )


def _backend_gone(engine: Engine, pid: int, started: str) -> bool:
    deadline = time.monotonic() + _WAIT
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            if not connection.execute(
                text("SELECT 1 FROM pg_stat_activity WHERE pid = :p AND backend_start::text = :s"),
                {"p": pid, "s": started},
            ).first():
                return True
        time.sleep(0.05)
    return False


@pytest.fixture
def one(scratch: Engine) -> Iterator[Engine]:
    engine = create_engine(scratch.url, pool_size=1, max_overflow=0)
    try:
        yield engine
    finally:
        engine.dispose()


def _refuse_first_commit(engine: Engine) -> list[int]:
    calls: list[int] = []

    def guard(connection: Any) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise _Guard("plan not finalised")

    event.listen(engine, "commit", guard)
    return calls


def test_t0_1_a_listener_refusal_leaves_a_clean_connection_for_the_next_request(
    scratch: Engine, one: Engine
) -> None:
    calls = _refuse_first_commit(one)
    seen: list[tuple[int, str]] = []
    with TestClient(_app(one, seen=seen), raise_server_exceptions=False) as client:
        refused = client.post("/write/1")
        assert refused.status_code == 500
        assert _rows(scratch) == []
        assert _idle_in_transaction(scratch) == 0
        allowed = client.post("/write/2")
        assert allowed.status_code == 200
    assert len(calls) == 2
    assert len(seen) == 2 and seen[0] == seen[1], "the pooled backend was not reused"
    assert _rows(scratch) == [2]


def test_t0_2_a_refusal_through_end_request_transaction_is_cleaned_up(
    scratch: Engine, one: Engine
) -> None:
    calls = _refuse_first_commit(one)
    seen: list[tuple[int, str]] = []
    with TestClient(_app(one, seen=seen), raise_server_exceptions=False) as client:
        refused = client.post("/early/1")
        assert refused.status_code == 500
        assert _rows(scratch) == []
        assert _idle_in_transaction(scratch) == 0
        allowed = client.post("/early/2")
        assert allowed.status_code == 200
    assert len(calls) == 2
    assert len(seen) == 2 and seen[0] == seen[1], "the pooled backend was not reused"
    assert _rows(scratch) == [2]


def test_t0_3_a_server_side_commit_failure_leaves_the_driver_idle(
    scratch: Engine, one: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ESTABLISHES the driver state after a COMMIT that the server rejects at a deferred trigger."""
    observed: dict[str, Any] = {}
    real_discard = deps._discard

    def observing_discard(connection: Connection) -> None:
        driver = connection.connection.driver_connection
        assert driver is not None
        observed["status_on_entry"] = driver.info.transaction_status
        observed["sqlalchemy_in_transaction"] = connection.in_transaction()
        observed["invalidated_on_entry"] = connection.invalidated
        real_discard(connection)

    monkeypatch.setattr(deps, "_discard", observing_discard)
    with TestClient(_app(one), raise_server_exceptions=False) as client:
        failed = client.post("/write/13")
        assert failed.status_code == 500
        assert _rows(scratch) == []
        assert _idle_in_transaction(scratch) == 0
        first = observed["status_on_entry"]
        allowed = client.post("/write/2")
        assert allowed.status_code == 200
    assert _rows(scratch) == [2]
    # Recorded as the driver's actual state: the server ended the transaction, so it is idle.
    from psycopg.pq import TransactionStatus

    assert first == TransactionStatus.IDLE, observed
    assert not observed["invalidated_on_entry"]


def test_t0_4_a_rollback_failure_invalidates_and_the_connection_is_replaced(
    scratch: Engine, one: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _refuse_first_commit(one)
    seen: list[tuple[int, str]] = []
    failed: list[int] = []

    def failing_rollback(connection: Connection) -> None:
        failed.append(1)
        raise OSError("rollback failed")

    with TestClient(_app(one, seen=seen), raise_server_exceptions=False) as client:
        with monkeypatch.context() as patched:
            patched.setattr(deps, "_driver_rollback", failing_rollback)
            refused = client.post("/write/1")
        assert refused.status_code == 500  # the original error's mapping
        second = client.post("/write/2")
        assert second.status_code == 200
    assert failed == [1]
    first = seen[0]
    assert (second.json()["pid"], second.json()["started"]) != first, (
        "an invalidated connection was reused"
    )
    assert _backend_gone(scratch, *first)
    assert _rows(scratch) == [2]


def test_t0_5_a_disconnect_before_commit_is_a_5xx_and_the_next_request_gets_a_new_backend(
    scratch: Engine, one: Engine
) -> None:
    """ESTABLISHES only the disconnect-before-COMMIT case: nothing was committed. A connection lost
    during COMMIT can leave the outcome unknown and is not claimed here."""
    gate = _Gate()
    result: dict[str, Any] = {}

    with TestClient(_app(one, gate=gate), raise_server_exceptions=False) as client:

        def first() -> None:
            result["first"] = client.post("/write/1")

        worker = threading.Thread(target=first)
        worker.start()
        try:
            assert gate.entered.wait(_WAIT)
            assert gate.pid is not None
            with scratch.connect() as admin:
                admin.execute(text("SELECT pg_terminate_backend(:p)"), {"p": gate.pid})
            assert gate.started is not None
            assert _backend_gone(scratch, gate.pid, gate.started)
        finally:
            gate.release.set()
            worker.join(_WAIT)
        assert result["first"].status_code >= 500
        assert _rows(scratch) == []
        second = client.post("/write/2")
    assert second.status_code == 200
    assert second.json()["started"] != gate.started, (
        "the terminated backend's connection was reused"
    )
    assert _rows(scratch) == [2]


def test_t0_6_the_stand_in_guard_error_is_a_sanitized_5xx(scratch: Engine, one: Engine) -> None:
    _refuse_first_commit(one)
    with TestClient(_app(one), raise_server_exceptions=False) as client:
        refused = client.post("/write/1")
    assert refused.status_code == 500
    assert "plan not finalised" not in refused.text
    assert "_Guard" not in refused.text
    assert _rows(scratch) == []
