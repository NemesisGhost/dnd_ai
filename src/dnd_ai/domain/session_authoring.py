"""Session definition policy (Phase 15 checkpoint 15.2D-1, decision D-13).

A session's *play status* is derived, never stored: `completed` once it has ended,
`in_progress` once it has started, `scheduled` while it has a planned real-world
start, otherwise `unscheduled`. Its `lifecycle_status` carries only `active` /
`archived`. The play commands (start, participants, log) arrive in checkpoint
15.2D-2. Errors here are fixed-code 409s.
"""

from datetime import datetime

from .authoring import AuthoringValidationError, normalize_description, normalize_name
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


class SessionNotOpenError(SafeMessageError):
    """Participants can be changed only until the session has ended."""

    safe_status_code = 409
    safe_error_code = "session_not_open"
    safe_message = "This session has ended."


class SessionNotInProgressError(SafeMessageError):
    """Logging and ending need a session that has started and not ended."""

    safe_status_code = 409
    safe_error_code = "session_not_in_progress"
    safe_message = "This session is not in progress."


class AnotherSessionInProgressError(SafeMessageError):
    """At most one session per campaign is in progress."""

    safe_status_code = 409
    safe_error_code = "another_session_in_progress"
    safe_message = "Another session of this campaign is already in progress."


class SessionTimeRequiredError(SafeMessageError):
    """Starting, ending, or logging needs a time; the campaign clock supplies it."""

    safe_status_code = 409
    safe_error_code = "clock_required"
    safe_message = "Set the campaign time first, or choose a time."


class SessionEndNotAfterStartError(SafeMessageError):
    """A session must end later (in fictional time) than it began."""

    safe_status_code = 409
    safe_error_code = "session_end_not_after_start"
    safe_message = "The end time must be later than when the session began."


class ParticipantInvalidError(SafeMessageError):
    """The character cannot take part: it must be a published, active character of this world."""

    safe_status_code = 400
    safe_error_code = "session_participant_invalid"
    safe_message = "The selected character cannot take part in this session."


class ParticipantExistsError(SafeMessageError):
    """The character is already present in this session."""

    safe_status_code = 409
    safe_error_code = "session_participant_exists"
    safe_message = "That character is already in this session."


class ParticipantRemovedError(SafeMessageError):
    """Only a present participant can be removed."""

    safe_status_code = 409
    safe_error_code = "session_participant_removed"
    safe_message = "That participant has already been removed."


PARTICIPATION_ROLES = ("player_character", "npc", "guest")
LOG_ENTRY_MAX_LENGTH = 500
LOG_DETAILS_MAX_LENGTH = 4000


def normalize_log_entry(value: str | None) -> str:
    """The text of a session log entry: stripped, 1 to 500 characters (it is the
    campaign-visible name of the recorded event)."""
    text_value = (value or "").strip()
    if not text_value or len(text_value) > LOG_ENTRY_MAX_LENGTH:
        raise AuthoringValidationError("entry must be 1 to 500 characters")
    return text_value


def normalize_log_details(value: str | None) -> str | None:
    """Optional GM-only detail, stripped; blank becomes none."""
    if value is None or not value.strip():
        return None
    if len(value.strip()) > LOG_DETAILS_MAX_LENGTH:
        raise AuthoringValidationError("details must be at most 4000 characters")
    return value.strip()


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
    "LOG_DETAILS_MAX_LENGTH",
    "LOG_ENTRY_MAX_LENGTH",
    "PARTICIPATION_ROLES",
    "AnotherSessionInProgressError",
    "ParticipantExistsError",
    "ParticipantInvalidError",
    "ParticipantRemovedError",
    "SessionAlreadyStartedError",
    "SessionEndNotAfterStartError",
    "SessionNotInProgressError",
    "SessionNotOpenError",
    "SessionTimeRequiredError",
    "normalize_log_details",
    "normalize_log_entry",
    "SessionInProgressError",
    "SessionNotActiveError",
    "SessionNotArchivedError",
    "derive_play_status",
    "normalize_description",
    "normalize_title",
]
