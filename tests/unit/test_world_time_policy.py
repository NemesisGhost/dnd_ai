"""Calendar and world-time sort-key policy (checkpoint 15.2W-1, decision D-11)."""

import pytest

from dnd_ai.domain.authoring import AuthoringValidationError
from dnd_ai.domain.world_time import (
    NARRATIVE_STEP,
    CalendarDate,
    WorldTimeNoGapError,
    allocate_narrative_sort_key,
    calendar_code,
    calendar_precision,
    calendar_sort_key,
    display_text,
    full_display_text,
    normalize_calendar,
    normalize_label,
)

pytestmark = pytest.mark.unit

# A 3-month calendar: 30 + 28 + 31 = 89 days a year.
MONTHS = [30, 28, 31]


def test_the_sort_key_is_minutes_since_the_start_of_year_zero() -> None:
    assert calendar_sort_key(CalendarDate(0), MONTHS) == 0
    assert calendar_sort_key(CalendarDate(0, 1, 1, 0, 1), MONTHS) == 1
    assert calendar_sort_key(CalendarDate(0, 1, 2), MONTHS) == 24 * 60
    assert calendar_sort_key(CalendarDate(0, 2, 1), MONTHS) == 30 * 24 * 60
    assert calendar_sort_key(CalendarDate(1), MONTHS) == 89 * 24 * 60
    assert calendar_sort_key(CalendarDate(0, 3, 31, 23, 59), MONTHS) == (88 * 24 + 23) * 60 + 59


def test_negative_years_sort_before_zero_and_order_is_monotonic() -> None:
    before = calendar_sort_key(CalendarDate(-1, 3, 31), MONTHS)
    assert before < calendar_sort_key(CalendarDate(0), MONTHS)
    keys = [
        calendar_sort_key(d, MONTHS)
        for d in (
            CalendarDate(-2),
            CalendarDate(-1, 2, 5),
            CalendarDate(0),
            CalendarDate(0, 2),
            CalendarDate(0, 2, 3, 4),
            CalendarDate(1),
        )
    ]
    assert keys == sorted(keys) and len(set(keys)) == len(keys)


@pytest.mark.parametrize(
    "date",
    [
        CalendarDate(0, None, 1),
        CalendarDate(0, 1, None, 5),
        CalendarDate(0, 1, 1, None, 5),
        CalendarDate(0, 4),
        CalendarDate(0, 2, 29),
        CalendarDate(0, 1, 1, 24),
        CalendarDate(0, 1, 1, 0, 60),
        CalendarDate(2_000_000),
    ],
)
def test_invalid_dates_are_refused(date: CalendarDate) -> None:
    with pytest.raises(AuthoringValidationError):
        calendar_sort_key(date, MONTHS)


def test_precision_follows_how_much_of_the_date_is_given() -> None:
    assert calendar_precision(CalendarDate(1, 2, 3), approximate=False) == "exact"
    assert calendar_precision(CalendarDate(1, 2), approximate=False) == "partial"
    assert calendar_precision(CalendarDate(1, 2, 3), approximate=True) == "approximate"


def test_a_narrative_key_sits_strictly_between_its_neighbours() -> None:
    assert allocate_narrative_sort_key(100, next_key=None, before_key=None) == 100 + NARRATIVE_STEP
    assert allocate_narrative_sort_key(100, next_key=200, before_key=None) == 150
    assert allocate_narrative_sort_key(100, next_key=200, before_key=120) == 110
    key = allocate_narrative_sort_key(100, next_key=103, before_key=None)
    assert 100 < key < 103


@pytest.mark.parametrize(("next_key", "before_key"), [(101, None), (None, 101), (102, 101)])
def test_no_gap_is_refused(next_key: int | None, before_key: int | None) -> None:
    with pytest.raises(WorldTimeNoGapError):
        allocate_narrative_sort_key(100, next_key=next_key, before_key=before_key)


def test_before_must_be_later_than_after() -> None:
    with pytest.raises(AuthoringValidationError):
        allocate_narrative_sort_key(100, next_key=None, before_key=100)


def test_repeated_placements_in_one_gap_stay_ordered_until_it_closes() -> None:
    low, high = 0, 1000
    placed = []
    while True:
        try:
            key = allocate_narrative_sort_key(low, next_key=high, before_key=None)
        except WorldTimeNoGapError:
            break
        assert low < key < high
        placed.append(key)
        high = key  # the next placement goes between `low` and the one just made
    assert placed == sorted(placed, reverse=True) and len(placed) >= 9


def test_calendar_normalization_bounds_and_uniqueness() -> None:
    spec = normalize_calendar(
        name=" Common Reckoning ",
        description=None,
        days_per_week=7,
        epoch_label=" Founding ",
        months=[("Frost", 30), ("Bloom", 31)],
    )
    assert spec.name == "Common Reckoning" and spec.epoch_label == "Founding"
    assert [m.day_count for m in spec.months] == [30, 31]
    bad = [
        {"months": []},
        {"months": [("A", 0)]},
        {"months": [("A", 401)]},
        {"months": [("A", 5), ("a", 5)]},
        {"months": [("", 5)]},
        {"days_per_week": 0},
        {"days_per_week": 31},
    ]
    for override in bad:
        kwargs: dict = {
            "name": "C",
            "description": None,
            "days_per_week": None,
            "epoch_label": None,
            "months": [("A", 5)],
        }
        kwargs.update(override)
        with pytest.raises(AuthoringValidationError):
            normalize_calendar(**kwargs)


def test_calendar_codes_are_server_generated_and_unique() -> None:
    assert calendar_code("Common Reckoning", set()) == "common_reckoning"
    assert calendar_code("Common Reckoning", {"common_reckoning"}) == "common_reckoning_2"
    assert calendar_code("123", set()).startswith("calendar_")
    assert calendar_code("!!!", set()).startswith("calendar")


def test_label_and_display_text() -> None:
    assert normalize_label("  after the war ", required=True) == "after the war"
    assert normalize_label("  ", required=False) is None
    with pytest.raises(AuthoringValidationError):
        normalize_label(None, required=True)
    assert (
        display_text(label=None, year=3, month_name="Bloom", day=5, epoch_label="Founding")
        == "Year 3 (Founding), Bloom 5"
    )
    assert display_text(label="Dusk", year=3, month_name=None, day=None, epoch_label=None) == "Dusk"
    assert display_text(label=None, year=None, month_name=None, day=None, epoch_label=None) == (
        "Unplaced time"
    )


def _full(**overrides: object) -> str | None:
    fields: dict[str, object] = {
        "label": None,
        "calendar_name": "Common Reckoning",
        "has_calendar": True,
        "year": 3,
        "month_name": "Bloom",
        "day": 5,
        "hour": None,
        "minute": None,
        "epoch_label": "Founding",
    }
    fields.update(overrides)
    return full_display_text(**fields)  # type: ignore[arg-type]


def test_full_display_text_keeps_calendar_date_clock_and_label() -> None:
    assert _full() == "Common Reckoning: Year 3 (Founding), Bloom 5"
    assert _full(hour=7, minute=5) == "Common Reckoning: Year 3 (Founding), Bloom 5, 07:05"
    assert _full(hour=14) == "Common Reckoning: Year 3 (Founding), Bloom 5, 14:00"
    assert _full(label="Harvest feast") == (
        "Common Reckoning: Year 3 (Founding), Bloom 5 — Harvest feast"
    )


def test_full_display_text_year_zero_is_a_real_year() -> None:
    assert _full(year=0, epoch_label=None, month_name=None, day=None) == (
        "Common Reckoning: Year 0"
    )


def test_full_display_text_narrative_and_missing_time() -> None:
    narrative = {"has_calendar": False, "calendar_name": None, "year": None}
    assert _full(label="Before the war", **narrative) == "Before the war"
    assert _full(label=None, **narrative) is None
