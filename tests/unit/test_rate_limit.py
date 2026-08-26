"""Tests for dnd_ai.domain.rate_limit.RateLimiter — deterministic (no real
sleep/wall-clock), per docs/PLAN.md §23.4/§23.5's "account/IP-aware
rate-limit abstractions ... deterministic in tests."
"""

from datetime import UTC, datetime, timedelta

import pytest

from dnd_ai.domain.rate_limit import RateLimiter

pytestmark = pytest.mark.unit

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_allows_up_to_max_attempts_then_denies() -> None:
    limiter = RateLimiter(max_attempts=3, window=timedelta(minutes=1))
    assert limiter.allow("key", now=_T0)
    assert limiter.allow("key", now=_T0)
    assert limiter.allow("key", now=_T0)
    assert not limiter.allow("key", now=_T0)


def test_a_denied_attempt_is_not_recorded_and_does_not_extend_the_block() -> None:
    limiter = RateLimiter(max_attempts=1, window=timedelta(minutes=1))
    assert limiter.allow("key", now=_T0)
    assert not limiter.allow("key", now=_T0 + timedelta(seconds=1))
    # The block is still governed by the original attempt's window, not
    # extended by the denied retry — allowed again once that window has
    # fully elapsed from the *original* attempt.
    assert limiter.allow("key", now=_T0 + timedelta(minutes=1, seconds=1))


def test_window_expiry_allows_a_fresh_attempt() -> None:
    limiter = RateLimiter(max_attempts=1, window=timedelta(minutes=1))
    assert limiter.allow("key", now=_T0)
    assert not limiter.allow("key", now=_T0 + timedelta(seconds=30))
    assert limiter.allow("key", now=_T0 + timedelta(minutes=1, seconds=1))


def test_different_keys_are_independent() -> None:
    limiter = RateLimiter(max_attempts=1, window=timedelta(minutes=1))
    assert limiter.allow("key-a", now=_T0)
    assert limiter.allow("key-b", now=_T0)
    assert not limiter.allow("key-a", now=_T0)


def test_reset_clears_recorded_attempts() -> None:
    limiter = RateLimiter(max_attempts=1, window=timedelta(minutes=1))
    assert limiter.allow("key", now=_T0)
    assert not limiter.allow("key", now=_T0)
    limiter.reset("key")
    assert limiter.allow("key", now=_T0)


def test_max_attempts_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        RateLimiter(max_attempts=0, window=timedelta(minutes=1))


def test_max_tracked_keys_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_tracked_keys"):
        RateLimiter(max_attempts=1, window=timedelta(minutes=1), max_tracked_keys=0)


# ---------------------------------------------------------------------------
# Bounded key tracking / LRU eviction (Phase 13B correction — arbitrary
# caller-controlled keys, e.g. login names, must not grow this process's
# memory without bound).
# ---------------------------------------------------------------------------


def test_tracked_key_count_never_exceeds_the_configured_cap() -> None:
    limiter = RateLimiter(max_attempts=5, window=timedelta(minutes=15), max_tracked_keys=3)
    for i in range(100):
        limiter.allow(f"key-{i}", now=_T0)
    assert limiter.tracked_key_count() == 3


def test_eviction_removes_the_least_recently_used_key_first() -> None:
    limiter = RateLimiter(max_attempts=5, window=timedelta(minutes=15), max_tracked_keys=2)
    limiter.allow("a", now=_T0)
    limiter.allow("b", now=_T0)
    # "a" is now the least-recently-used of the two tracked keys. Adding a
    # third, distinct key must evict "a", not "b".
    limiter.allow("c", now=_T0)
    assert limiter.tracked_key_count() == 2
    # "a"'s history was evicted, so it gets a fresh 5-attempt allowance —
    # observable as "a" no longer sharing any state with its original
    # attempt.
    for _ in range(5):
        assert limiter.allow("a", now=_T0)
    assert not limiter.allow("a", now=_T0)


def test_re_touching_a_key_protects_it_from_eviction() -> None:
    limiter = RateLimiter(max_attempts=5, window=timedelta(minutes=15), max_tracked_keys=2)
    limiter.allow("a", now=_T0)
    limiter.allow("b", now=_T0)
    # Touch "a" again — it is now the most-recently-used, so "b" (untouched
    # since its first call) is the one evicted when "c" arrives.
    limiter.allow("a", now=_T0)
    limiter.allow("c", now=_T0)
    assert limiter.tracked_key_count() == 2
    for _ in range(5):
        assert limiter.allow("b", now=_T0)
    assert not limiter.allow("b", now=_T0)


def test_an_unbounded_number_of_distinct_keys_from_a_single_caller_stays_bounded() -> None:
    """The exact scenario this correction closes: an attacker (or any
    caller) presenting a fresh, never-repeated key on every single call —
    e.g. a different login name each time — must never grow tracked state
    past the configured cap, regardless of how many distinct keys are
    presented."""
    limiter = RateLimiter(max_attempts=10, window=timedelta(minutes=15), max_tracked_keys=50)
    for i in range(5_000):
        limiter.allow(f"attacker-supplied-name-{i}", now=_T0)
    assert limiter.tracked_key_count() <= 50
