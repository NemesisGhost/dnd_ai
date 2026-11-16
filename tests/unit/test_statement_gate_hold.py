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
