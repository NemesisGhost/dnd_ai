"""Campaign clock policy (Phase 15 checkpoint 15.2W-2, decision D-10).

The clock is typed timeline state: its value changes only through an advance (the
new time is strictly later than the current effective time) or a correction (any
different time, citing the advance it corrects). A timeline with no clock row of
its own *inherits* its parent's clock, bounded by its branch point (it never
sees parent time that lies after the branch). These errors are fixed-code 409s.
"""

from .errors import SafeMessageError

CLOCK_EVENT_ADVANCED = "time_advanced"
CLOCK_EVENT_CORRECTED = "time_corrected"
CLOCK_COMPONENT = "current_world_time_id"


class ClockNotAdvancedError(SafeMessageError):
    """The requested time is not strictly later than the current clock."""

    safe_status_code = 409
    safe_error_code = "clock_not_advanced"
    safe_message = "The new time must be later than the campaign's current time."


class ClockNotSetError(SafeMessageError):
    """A correction needs an existing clock value of the campaign's own."""

    safe_status_code = 409
    safe_error_code = "clock_not_set"
    safe_message = "This campaign has no recorded time to correct. Advance the clock first."


class ClockUnchangedError(SafeMessageError):
    """A correction to the time the clock already shows."""

    safe_status_code = 409
    safe_error_code = "clock_unchanged"
    safe_message = "The clock already shows that time."


def bounded_inherited_sort_key(parent_sort_key: int | None, branch_sort_key: int) -> int:
    """The sort key a branch's inherited clock shows: the parent's clock, but never
    later than the branch point (a branch with no parent clock starts at its
    branch point)."""
    if parent_sort_key is None or parent_sort_key > branch_sort_key:
        return branch_sort_key
    return parent_sort_key
