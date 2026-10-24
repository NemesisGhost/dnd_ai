"""The derived period status of a relationship against the campaign clock (half-open [start, end))."""

import pytest

from dnd_ai.domain.relationship_authoring import relationship_period_status


@pytest.mark.parametrize(
    ("start", "end", "clock", "expected"),
    [
        (None, None, 5, "undated"),
        (None, None, None, "undated"),
        (1, None, None, "clock_unset"),
        (1, 9, None, "clock_unset"),
        (None, 9, None, "clock_unset"),
        (5, None, 4, "not_started"),
        (5, 9, 4, "not_started"),
        (5, None, 5, "in_effect"),
        (5, 9, 8, "in_effect"),
        (5, 9, 9, "ended"),
        (5, 9, 12, "ended"),
        (None, 9, 3, "in_effect"),
        (None, 9, 9, "ended"),
        (5, None, 99, "in_effect"),
    ],
)
def test_period_status(
    start: int | None, end: int | None, clock: int | None, expected: str
) -> None:
    assert relationship_period_status(start, end, clock) == expected
