"""`tests.http_race_support.StatementGate`: the hold budget, the recorded expiry and the strict mode.

The gate used to let a parked request run on, silently, once `WAIT_SECONDS` had passed without a release. A test that
was still establishing the blocking relationship it needed (a second request queued behind the parked one) could then
lose its parked request to that silent release at the same moment its own wait ran out. The default is unchanged; the
proceed is now recorded, and `strict=True` with an explicit `hold_seconds` makes an expired hold a visible failure in the
parked request. These tests drive the hook directly with a fake connection: no database, and only tenths of a second.
"""

import threading
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy import Engine

from tests.http_race_support import GateExpired, StatementGate

pytestmark = pytest.mark.unit


def _connection(pid: int = 4242) -> Any:
    return SimpleNamespace(
        connection=SimpleNamespace(
            driver_connection=SimpleNamespace(info=SimpleNamespace(backend_pid=pid))
        )
    )


def _gate(**kwargs: Any) -> StatementGate:
    return StatementGate(cast(Engine, None), r"UPDATE target", **kwargs)


def _run_hook(gate: StatementGate, outcome: dict[str, Any]) -> threading.Thread:
    def run() -> None:
        try:
            gate._hook(_connection(), None, "UPDATE   target SET x = 1")
            outcome["proceeded"] = True
        except BaseException as exc:  # noqa: BLE001 - what the parked request would see
            outcome["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def test_the_default_proceeds_after_the_hold_and_now_records_that_it_did() -> None:
    gate = _gate(hold_seconds=0.2)
    outcome: dict[str, Any] = {}
    _run_hook(gate, outcome).join(5)
    assert outcome == {"proceeded": True}
    assert gate.expired and gate.released_by == "timeout"
    assert "EXPIRED" in gate.describe()


def test_a_strict_gate_fails_the_parked_request_instead_of_letting_it_run_on() -> None:
    gate = _gate(hold_seconds=0.2, strict=True)
    outcome: dict[str, Any] = {}
    _run_hook(gate, outcome).join(5)
    assert "proceeded" not in outcome
    assert isinstance(outcome["error"], GateExpired)
    assert gate.expired and gate.released_by == "timeout"


def test_a_release_inside_the_budget_is_recorded_as_the_tests_and_never_expires() -> None:
    gate = _gate(hold_seconds=5.0, strict=True)
    outcome: dict[str, Any] = {}
    thread = _run_hook(gate, outcome)
    assert gate.reached.wait(5) and gate.pid == 4242
    assert not gate.expired and gate.released_by is None
    gate.release()
    thread.join(5)
    assert outcome == {"proceeded": True}
    assert gate.released_by == "test" and not gate.expired


def test_the_hold_can_outlive_a_wait_that_is_longer_than_the_default_budget() -> None:
    """The case the profile race needs: the parked request is still held after the default budget would have passed."""
    gate = _gate(hold_seconds=0.6, strict=True)
    outcome: dict[str, Any] = {}
    thread = _run_hook(gate, outcome)
    assert gate.reached.wait(5)
    # a (scaled-down) default budget passes with the gate still holding: the request has not been released
    assert not threading.Event().wait(0.3)
    assert "proceeded" not in outcome and not gate.expired
    gate.release()
    thread.join(5)
    assert outcome == {"proceeded": True} and gate.released_by == "test"


# --- cleanup: the listener is never removed from under an active worker -------------------------------------------------


class _Worker:
    """What `StatementGate.track` needs of a request: a `done` event and a `describe()`."""

    def __init__(self, name: str = "worker") -> None:
        self.name = name
        self.done = threading.Event()

    def describe(self) -> str:
        return f"{self.name}: {'finished' if self.done.is_set() else 'still running'}"


def _installed(engine: Any, gate: StatementGate) -> bool:
    from sqlalchemy import event

    return bool(event.contains(engine, "before_cursor_execute", gate._hook))


def _armed(**kwargs: Any) -> tuple[Any, StatementGate]:
    from sqlalchemy import create_engine

    engine = create_engine("sqlite://")
    return engine, StatementGate(engine, r"never matches", **kwargs)


def test_finished_workers_let_the_listener_go_at_once() -> None:
    engine, gate = _armed(cleanup_seconds=0.2)
    worker = _Worker()
    worker.done.set()
    with gate:
        gate.track(worker)
        assert _installed(engine, gate)
    assert (
        not _installed(engine, gate)
        and gate.listener_removed.is_set()
        and not gate.listener_retained
    )


def test_an_unfinished_worker_keeps_the_listener_installed_and_the_original_failure_is_preserved() -> (
    None
):
    """A worker still running after the bounded cleanup wait: detected, explicit (a note on the exception that is already
    propagating, never replacing it), the listener **retained**; it is removed once the worker finishes."""
    engine, gate = _armed(cleanup_seconds=0.1)
    worker = _Worker("edit")
    original = RuntimeError("the test's own failure")
    with pytest.raises(RuntimeError) as raised, gate:
        gate.track(worker)
        raise original
    assert raised.value is original, "the original failure is the one that propagates"
    assert gate.listener_retained and not gate.listener_removed.is_set()
    assert _installed(engine, gate), "the listener stays installed while the worker is active"
    assert any("RETAINED" in note and "edit: still running" in note for note in original.__notes__)
    worker.done.set()  # the worker finishes: the daemon removal thread may now detach the listener
    assert gate.listener_removed.wait(5)
    assert not _installed(engine, gate)


def test_an_unfinished_worker_with_no_other_failure_is_an_explicit_failure_and_still_retains_the_listener() -> (
    None
):
    engine, gate = _armed(cleanup_seconds=0.1)
    worker = _Worker()
    with pytest.raises(AssertionError, match="RETAINED"), gate:
        gate.track(worker)
    assert gate.listener_retained and _installed(engine, gate)
    worker.done.set()
    assert gate.listener_removed.wait(5) and not _installed(engine, gate)


def test_the_cleanup_wait_is_bounded_in_total_across_workers() -> None:
    import time

    engine, gate = _armed(cleanup_seconds=0.3)
    workers = [_Worker(f"w{i}") for i in range(5)]
    started = time.monotonic()
    with pytest.raises(RuntimeError), gate:
        for worker in workers:
            gate.track(worker)
        raise RuntimeError("fails")
    assert time.monotonic() - started < 2.0, (
        "five stuck workers still cost one bounded wait, not five"
    )
    for worker in workers:
        worker.done.set()
    assert gate.listener_removed.wait(5) and not _installed(engine, gate)


def test_a_worker_that_finishes_inside_the_cleanup_wait_is_not_an_error() -> None:
    """The ordinary failure path: the gate is released, the worker then finishes within the wait."""
    engine, gate = _armed(cleanup_seconds=5.0)
    worker = _Worker()
    timer = threading.Timer(0.1, worker.done.set)
    with pytest.raises(RuntimeError, match="boom"), gate:
        gate.track(worker)
        timer.start()
        raise RuntimeError("boom")
    timer.join()
    assert not gate.listener_retained and not _installed(engine, gate)


def test_an_untracked_gate_behaves_as_before() -> None:
    engine, gate = _armed()
    with gate:
        assert _installed(engine, gate)
    assert not _installed(engine, gate) and not gate.listener_retained
