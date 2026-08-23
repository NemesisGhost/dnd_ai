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
