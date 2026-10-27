"""Calendars, world-time points, and sort-key policy (Phase 15 checkpoint 15.2W-1).

Pure and framework-free. A world-time point's `sort_key` is permanent
(`core.world_times.world_id`/`sort_key` are immutable), so the policy here is a
decision the whole timeline model leans on (decision D-11):

- A point on a **calendar** gets the number of minutes since the start of year
  zero: whole years are the sum of the calendar's month lengths, a missing finer
  component counts as the start of its parent (month 1, day 1, 00:00). A year may
  be negative.
- A **narrative** point (no calendar date) is placed "after X" and optionally
  "before Y". The server allocates a key strictly between X and the next existing
  point after X (or Y, if earlier), and refuses when no whole number fits. With
  nothing later it sits one day (1440 minutes) after X.

Points are never edited. The same moment may legitimately have more than one
point, so keys are not unique.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .authoring import AuthoringValidationError, normalize_description, normalize_name
from .errors import SafeMessageError

YEAR_MIN = -1_000_000
YEAR_MAX = 1_000_000
NARRATIVE_STEP = 24 * 60

MONTHS_MAX = 60
DAY_COUNT_MAX = 400
MONTH_NAME_MAX_LENGTH = 100
DAYS_PER_WEEK_MAX = 30
EPOCH_LABEL_MAX_LENGTH = 200
LABEL_MAX_LENGTH = 200

PRECISION_EXACT = "exact"
PRECISION_PARTIAL = "partial"
PRECISION_APPROXIMATE = "approximate"
PRECISION_NARRATIVE = "narrative"


class CalendarInvalidError(SafeMessageError):
    """The calendar is nonexistent or belongs to another world -- identical."""

    safe_status_code = 400
    safe_error_code = "calendar_id_invalid"
    safe_message = "That calendar is not available."


class WorldTimeReferenceInvalidError(SafeMessageError):
    """A referenced world-time point is nonexistent or in another world."""

    safe_status_code = 400
    safe_error_code = "world_time_id_invalid"
    safe_message = "That world time is not available."


class WorldTimeNoGapError(SafeMessageError):
    """No whole sort key fits between the neighbours of a narrative placement."""

    safe_status_code = 409
    safe_error_code = "world_time_no_gap"
    safe_message = "There is no room to place a new time there; choose a different position."


@dataclass(frozen=True)
class MonthSpec:
    name: str
    day_count: int


@dataclass(frozen=True)
class CalendarSpec:
    name: str
    description: str | None
    days_per_week: int | None
    epoch_label: str | None
    months: tuple[MonthSpec, ...]


def normalize_calendar(
    *,
    name: str,
    description: str | None,
    days_per_week: int | None,
    epoch_label: str | None,
    months: Sequence[tuple[str, int]],
) -> CalendarSpec:
    clean_name = normalize_name(name)
    clean_description = normalize_description(description)
    if days_per_week is not None and not 1 <= days_per_week <= DAYS_PER_WEEK_MAX:
        raise AuthoringValidationError("days_per_week is out of range")
    epoch = None
    if epoch_label is not None and epoch_label.strip():
        epoch = epoch_label.strip()
        if len(epoch) > EPOCH_LABEL_MAX_LENGTH:
            raise AuthoringValidationError("epoch_label is too long")
    if not 1 <= len(months) <= MONTHS_MAX:
        raise AuthoringValidationError("a calendar needs between 1 and 60 months")
    seen: set[str] = set()
    specs: list[MonthSpec] = []
    for raw_name, day_count in months:
        month_name = raw_name.strip()
        if not month_name or len(month_name) > MONTH_NAME_MAX_LENGTH:
            raise AuthoringValidationError("a month name is required and must be short")
        if month_name.lower() in seen:
            raise AuthoringValidationError("month names must be unique")
        seen.add(month_name.lower())
        if not 1 <= day_count <= DAY_COUNT_MAX:
            raise AuthoringValidationError("a month's day count is out of range")
        specs.append(MonthSpec(month_name, day_count))
    return CalendarSpec(clean_name, clean_description, days_per_week, epoch, tuple(specs))


def calendar_code(name: str, taken: set[str]) -> str:
    """A server-generated, world-unique calendar code from its name (the code is
    never client-supplied: a globally chosen code would let one world probe
    another's)."""
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:48]
    if not base or not base[0].isalpha():
        base = f"calendar_{base}".strip("_")
    code = base
    suffix = 2
    while code in taken:
        code = f"{base}_{suffix}"
        suffix += 1
    return code


@dataclass(frozen=True)
class CalendarDate:
    year: int
    month_number: int | None = None
    day: int | None = None
    hour: int | None = None
    minute: int | None = None


def validate_calendar_date(date: CalendarDate, month_day_counts: Sequence[int]) -> None:
    if not YEAR_MIN <= date.year <= YEAR_MAX:
        raise AuthoringValidationError("year is out of range")
    if date.day is not None and date.month_number is None:
        raise AuthoringValidationError("a day needs a month")
    if date.hour is not None and date.day is None:
        raise AuthoringValidationError("an hour needs a day")
    if date.minute is not None and date.hour is None:
        raise AuthoringValidationError("a minute needs an hour")
    if date.month_number is not None and not 1 <= date.month_number <= len(month_day_counts):
        raise AuthoringValidationError("month_number is out of range")
    if date.day is not None:
        assert date.month_number is not None
        if not 1 <= date.day <= month_day_counts[date.month_number - 1]:
            raise AuthoringValidationError("day is out of range for that month")
    if date.hour is not None and not 0 <= date.hour < 24:
        raise AuthoringValidationError("hour is out of range")
    if date.minute is not None and not 0 <= date.minute < 60:
        raise AuthoringValidationError("minute is out of range")


def calendar_sort_key(date: CalendarDate, month_day_counts: Sequence[int]) -> int:
    """Minutes since the start of year zero (negative before it)."""
    validate_calendar_date(date, month_day_counts)
    year_length = sum(month_day_counts)
    month = 1 if date.month_number is None else date.month_number
    day = 1 if date.day is None else date.day
    days = date.year * year_length + sum(month_day_counts[: month - 1]) + (day - 1)
    return (days * 24 + (date.hour or 0)) * 60 + (date.minute or 0)


def calendar_precision(date: CalendarDate, *, approximate: bool) -> str:
    if approximate:
        return PRECISION_APPROXIMATE
    return PRECISION_EXACT if date.day is not None else PRECISION_PARTIAL


def allocate_narrative_sort_key(
    after_key: int, *, next_key: int | None, before_key: int | None
) -> int:
    """A key strictly after `after_key` and strictly before the nearest upper
    bound (the next existing point after it, or `before_key`, whichever is
    earlier). Raises `WorldTimeNoGapError` when no whole number fits."""
    if before_key is not None and before_key <= after_key:
        raise AuthoringValidationError("the 'before' time must be later than the 'after' time")
    bounds = [b for b in (next_key, before_key) if b is not None]
    if not bounds:
        return after_key + NARRATIVE_STEP
    upper = min(bounds)
    if upper - after_key < 2:
        raise WorldTimeNoGapError(f"no gap after {after_key} before {upper}")
    return after_key + (upper - after_key) // 2


def normalize_label(label: str | None, *, required: bool) -> str | None:
    if label is None or not label.strip():
        if required:
            raise AuthoringValidationError("a label is required")
        return None
    stripped = label.strip()
    if len(stripped) > LABEL_MAX_LENGTH:
        raise AuthoringValidationError("label is too long")
    return stripped


def display_text(
    *,
    label: str | None,
    year: int | None,
    month_name: str | None,
    day: int | None,
    epoch_label: str | None,
) -> str:
    """A human-readable name for a point: its label if it has one, otherwise
    "Year Y, Month D" built from the calendar fields."""
    if label:
        return label
    if year is None:
        return "Unplaced time"
    parts = [f"Year {year}"]
    if epoch_label:
        parts[0] += f" ({epoch_label})"
    if month_name:
        parts.append(month_name + (f" {day}" if day is not None else ""))
    return ", ".join(parts)


def full_display_text(
    *,
    label: str | None,
    calendar_name: str | None,
    has_calendar: bool,
    year: int | None,
    month_name: str | None,
    day: int | None,
    hour: int | None,
    minute: int | None,
    epoch_label: str | None,
) -> str | None:
    """The complete reading of a point for event feeds, or None when it has
    neither a label nor a year (callers show their own "unassigned" text).

    A calendar point reads "Calendar: Year Y (Epoch), Month D, HH:MM" with the
    label, when present, appended after an em dash; a narrative point keeps its
    label (or, without a calendar, the `display_text` reading). Year zero is a
    real year."""
    if not label and year is None:
        return None
    if not has_calendar or year is None:
        return display_text(
            label=label, year=year, month_name=month_name, day=day, epoch_label=epoch_label
        )
    date = display_text(
        label=None, year=year, month_name=month_name, day=day, epoch_label=epoch_label
    )
    parts = [date]
    if hour is not None:
        parts.append(f"{hour:02d}:{(minute or 0):02d}")
    text = f"{calendar_name or 'Calendar'}: {', '.join(parts)}"
    return f"{text} — {label}" if label else text
