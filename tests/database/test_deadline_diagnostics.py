"""A race-harness deadline captures a persistent report BEFORE teardown, without extending the deadline
(R01 S5-E2 E10 correction, design section 10).

The historical stalls (a gate statement never reached, no non-idle backend, the request still running client-side) are not
reproduced here and are not explained by this test: it builds the *shape* that the old `activity_report` could not show,
a request that holds a pool connection idle in a transaction and is stuck in application code, and proves that the new
report shows it, with the gate listener still registered, the request still running and its stack, the pool checkout,
the idle-in-transaction backend, the deadlock counter and the machine context.
"""

import threading
import time
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, text

from tests import http_race_support as support
from tests.http_race_support import Request, StatementGate, run_in_thread

pytestmark = pytest.mark.database

DEADLINE = 1.5


def stalled_in_application_code(engine: Engine, release: threading.Event) -> None:
    """Holds a pool connection idle in a transaction and does nothing: no statement is running on the server."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        release.wait(60)


@pytest.fixture
def pooled(postgres_engine: Engine) -> Any:
    engine = create_engine(postgres_engine.url, pool_size=2, max_overflow=0)
    try:
        yield engine
    finally:
        engine.dispose()


def test_a_gate_that_is_never_reached_reports_the_stalled_request_before_teardown(
    pooled: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUNNER_DEADLINE_DIAG_DIR", str(tmp_path))
    monkeypatch.setattr(support, "WAIT_SECONDS", DEADLINE)
    release = threading.Event()
    started = time.monotonic()
    try:
        with StatementGate(pooled, r"^THIS STATEMENT NEVER RUNS$") as gate:
            request = run_in_thread(
                "stalled-request", lambda: stalled_in_application_code(pooled, release)
            )
            time.sleep(
                0.3
            )  # the request has checked a connection out and is parked in application code
            with pytest.raises(AssertionError) as raised:
                gate.wait_reached()
            elapsed = time.monotonic() - started
            message = str(raised.value)
            # the original assertion is raised unchanged and the deadline was not extended
            assert "the request never reached the gated statement" in message
            assert DEADLINE <= elapsed < DEADLINE + 6, f"the deadline moved: {elapsed:.1f}s"
            files = list(tmp_path.glob("*.txt"))
            assert len(files) == 1 and f"report file: {files[0]}" in message
            report = files[0].read_text(encoding="utf-8")
            # captured while everything was still alive (this is inside the `with`, before any teardown)
            assert "listener_registered=True" in report, (
                "the gate listener must still be registered"
            )
            assert "reached=False" in report and "released=False" in report
            assert "stalled-request: done=False" in report and "STILL RUNNING" in report
            assert "stalled_in_application_code" in report, "the request's own stack is shown"
            assert "1 connection(s) checked out" in report
            assert "idle in transaction" in report, (
                "pg_stat_activity includes idle-in-transaction backends"
            )
            assert "deadlock counter:" in report and "== machine context ==" in report
            assert not request.finished(), "the request was still parked when the report was taken"
    finally:
        release.set()
    request.wait("the stalled request finishes once released")


def test_a_request_that_does_not_finish_reports_its_completion_state_and_stack(
    pooled: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUNNER_DEADLINE_DIAG_DIR", str(tmp_path))
    monkeypatch.setattr(support, "WAIT_SECONDS", DEADLINE)
    release = threading.Event()
    request: Request = run_in_thread(
        "never-finishes", lambda: stalled_in_application_code(pooled, release)
    )
    try:
        time.sleep(0.3)
        with pytest.raises(AssertionError) as raised:
            request.wait("the test asks for it")
        assert "never-finishes did not finish: the test asks for it" in str(raised.value)
        (path,) = tmp_path.glob("*.txt")
        report = path.read_text(encoding="utf-8")
        assert "never-finishes: done=False" in report and "stalled_in_application_code" in report
    finally:
        release.set()
    request.wait("released")


def test_gate_cleanup_removes_the_listener_and_releases_even_if_removal_fails(
    pooled: Engine,
) -> None:
    gate = StatementGate(pooled, r"^NEVER$")
    gate.__enter__()
    # removing twice must not raise out of __exit__ (it would mask the exception already propagating)
    gate.__exit__(None, None, None)
    gate.__exit__(None, None, None)
    assert gate.resume.is_set()
