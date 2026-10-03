"""`dnd_ai.queries.bootstrap.resolve_startup_campaign_id` — the pure landing
precedence (docs/UI_DESIGN.md §4.2 steps 2-6)."""

import uuid

import pytest

from dnd_ai.queries.bootstrap import resolve_startup_campaign_id

pytestmark = pytest.mark.unit

A, B, C = (uuid.uuid4() for _ in range(3))
STRANGER = uuid.uuid4()


def test_no_campaigns_resolves_to_none_even_with_stored_ids() -> None:
    assert resolve_startup_campaign_id([], A, B) is None


def test_exactly_one_campaign_wins_over_any_preference() -> None:
    assert resolve_startup_campaign_id([A], None, None) == A
    assert resolve_startup_campaign_id([A], STRANGER, STRANGER) == A


def test_valid_preferred_campaign_wins_over_last_visited() -> None:
    assert resolve_startup_campaign_id([A, B, C], B, C) == B


def test_invalid_preferred_falls_back_to_valid_last_visited() -> None:
    assert resolve_startup_campaign_id([A, B, C], STRANGER, C) == C


def test_last_visited_used_when_no_preferred() -> None:
    assert resolve_startup_campaign_id([A, B], None, B) == B


def test_no_valid_preference_never_picks_the_first_campaign() -> None:
    assert resolve_startup_campaign_id([A, B, C], None, None) is None
    assert resolve_startup_campaign_id([A, B, C], STRANGER, STRANGER) is None
