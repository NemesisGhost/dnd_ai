"""Session definition policy (Phase 15 checkpoint 15.2D-1, decision D-13).

A session's *play status* is derived, never stored: `completed` once it has ended,
`in_progress` once it has started, `scheduled` while it has a planned real-world
start, otherwise `unscheduled`. Its `lifecycle_status` carries only `active` /
`archived`. The play commands (start, participants, log) arrive in checkpoint
15.2D-2. Errors here are fixed-code 409s.
"""

from datetime import datetime

from .authoring import normalize_description, normalize_name
from .errors import SafeMessageError

SESSION_ACTIVE = "active"
SESSION_ARCHIVED = "archived"

PLAY_UNSCHEDULED = "unscheduled"
PLAY_SCHEDULED = "scheduled"
PLAY_IN_PROGRESS = "in_progress"
PLAY_COMPLETED = "completed"


def derive_play_status(
    *, scheduled_for: datetime | None, started_at: datetime | None, ended_at: datetime | None
) -> str:
    if ended_at is not None:
        return PLAY_COMPLETED
    if started_at is not None:
        return PLAY_IN_PROGRESS
    if scheduled_for is not None:
        return PLAY_SCHEDULED
    return PLAY_UNSCHEDULED


class SessionNotActiveError(SafeMessageError):
    """The action needs an active (not archived) session."""

    safe_status_code = 409
    safe_error_code = "session_not_active"
    safe_message = "This session is archived. Restore it first."


class SessionNotArchivedError(SafeMessageError):
    """Restore applies only to an archived session."""

    safe_status_code = 409
    safe_error_code = "session_not_archived"
    safe_message = "This session is not archived."


class SessionInProgressError(SafeMessageError):
    """A session that is being played cannot be archived."""

    safe_status_code = 409
    safe_error_code = "session_in_progress"
    safe_message = "End the session before archiving it."


class SessionAlreadyStartedError(SafeMessageError):
    """The planned start cannot change once the session has started."""

    safe_status_code = 409
    safe_error_code = "session_already_started"
    safe_message = "This session has already started, so its planned start cannot change."


def normalize_title(value: str | None) -> str | None:
    """An optional session title: stripped; blank becomes none; same bound as a name."""
    if value is None or not value.strip():
        return None
    return normalize_name(value)


__all__ = [
    "PLAY_COMPLETED",
    "PLAY_IN_PROGRESS",
    "PLAY_SCHEDULED",
    "PLAY_UNSCHEDULED",
    "SESSION_ACTIVE",
    "SESSION_ARCHIVED",
    "SessionAlreadyStartedError",
    "SessionInProgressError",
    "SessionNotActiveError",
    "SessionNotArchivedError",
    "derive_play_status",
    "normalize_description",
    "normalize_title",
]
