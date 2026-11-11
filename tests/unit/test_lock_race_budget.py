"""`tests.lock_race_support.Budget`: a wait budget that is not charged for process freezes.

The behaviour exists because of an observed failure (a 44 second whole-process freeze right after a
hold, then a 15 second wait expiring the instant the process resumed); these tests drive it with a
fake clock, so no real time passes and no database is involved.
"""

import threading
from typing import Any

import pytest

import tests.lock_race_support as support
from tests.lock_race_support import STALL_SECONDS, Budget, Pause, Worker


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_budget_expires_after_its_seconds_of_ordinary_polling() -> None:
    clock = Clock()
    budget = Budget(15.0, clock)
    steps = 0
    while not budget.expired():
        clock.now += 0.05
        steps += 1
    assert 299 <= steps <= 301  # 15 s in polls of 0.05 s
    assert budget.stalled == 0.0 and budget.note() == ""


def test_a_freeze_longer_than_the_whole_budget_does_not_end_the_wait() -> None:
    clock = Clock()
    budget = Budget(15.0, clock)
    assert not budget.expired()
    clock.now += 44.0  # the whole process did not run
    assert not budget.expired()  # the wait resumes with its full remaining budget
    assert budget.stalled == 44.0
    assert "44.0s" in budget.note()
    steps = 0
    while not budget.expired():
        clock.now += 0.05
        steps += 1
    assert 299 <= steps <= 301  # the whole 15 s are still there to poll in


def test_after_a_freeze_the_remaining_budget_still_runs_out_in_polled_time() -> None:
    clock = Clock()
    budget = Budget(15.0, clock)
    for _ in range(10):  # 5 s of ordinary polling
        assert not budget.expired()
        clock.now += 0.5
    clock.now += 30.0  # frozen
    assert not budget.expired()
    steps = 0
    while not budget.expired():  # a request hung in a process that keeps running still fails
        clock.now += 0.5
        steps += 1
    assert 19 <= steps <= 21  # the 10 s that were left, not 10 s plus the freeze
    assert 30.0 <= budget.stalled <= 31.0  # the freeze, with the poll step before it


def test_a_gap_at_the_threshold_is_not_a_freeze() -> None:
    clock = Clock()
    budget = Budget(15.0, clock)
    budget.expired()
    clock.now += STALL_SECONDS
    budget.expired()
    assert budget.stalled == 0.0


def test_repeated_slow_polls_are_credited_only_up_to_the_cap() -> None:
    clock = Clock()
    budget = Budget(15.0, clock, max_credit=10.0)
    budget.expired()
    for _ in range(50):  # every poll slow (5 s): the credit stops at the cap
        clock.now += 5.0
        budget.expired()
        if budget.stalled >= 10.0:
            break
    assert budget.stalled == 10.0
    for _ in range(5):
        clock.now += 5.0
        budget.expired()
    assert budget.stalled == 10.0  # not extended further
    assert budget.expired()  # and the wait ends: 15 s + at most the cap


def test_a_gap_is_credited_in_part_when_it_crosses_the_cap() -> None:
    clock = Clock()
    budget = Budget(15.0, clock, max_credit=10.0)
    clock.now += 4.0
    budget.expired()
    clock.now += 30.0
    budget.expired()
    assert budget.stalled == 10.0
    assert "10.0s" in budget.note()


class _Race:
    def waiting_sessions(self) -> list[object]:
        return []


class _ExpiresOnFirstAsk:
    """A budget whose deadline is already past at the first ask, after running `before`: the
    boundary the poll loop has to look again at."""

    before: Any = None

    def __init__(self, seconds: float) -> None:
        pass

    def expired(self) -> bool:
        if _ExpiresOnFirstAsk.before is not None:
            _ExpiresOnFirstAsk.before()
        return True

    def note(self) -> str:
        return ""


def _pause() -> Pause:
    return Pause(_Race(), thread_name="t", pattern="x")  # type: ignore[arg-type]


def _worker() -> Worker:
    return Worker(name="w", thread=threading.Thread())


def test_wait_reached_looks_again_after_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    pause, worker = _pause(), _worker()
    monkeypatch.setattr(support, "Budget", _ExpiresOnFirstAsk)
    _ExpiresOnFirstAsk.before = pause.reached.set  # reached in the last poll interval
    pause.wait_reached(worker)  # passes: the pause was reached before the final look


def test_wait_reached_reports_a_worker_that_ended_at_the_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pause, worker = _pause(), _worker()
    monkeypatch.setattr(support, "Budget", _ExpiresOnFirstAsk)
    _ExpiresOnFirstAsk.before = worker.finished.set
    with pytest.raises(AssertionError, match="ended before the pause point"):
        pause.wait_reached(worker)


def test_wait_reached_expires_when_neither_happened(monkeypatch: pytest.MonkeyPatch) -> None:
    pause, worker = _pause(), _worker()
    monkeypatch.setattr(support, "Budget", _ExpiresOnFirstAsk)
    _ExpiresOnFirstAsk.before = None
    with pytest.raises(AssertionError, match="never reached the pause point"):
        pause.wait_reached(worker)
