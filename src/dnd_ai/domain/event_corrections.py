"""Event correction policy (Phase 15 checkpoint 15.2E-1, decision D-15).

A recorded event is never edited. To undo one, a *correcting event* is recorded that
carries the compensating effects, the original moves to `voided` (void) or `corrected`
(correct, with a replacement event), and `narrative.event_corrections` links them. The
compensation is applied only when the state the original effect produced is still
there: if anything has changed it since, the correction is refused
(`correction_not_reversible`) rather than guessing. Only effect kinds with a writer the
platform can safely reverse are supported; any other effect refuses.
"""

from dataclasses import dataclass

from .authoring import AuthoringValidationError
from .errors import DomainAuthorizationError, SafeMessageError

CORRECTION_VOID = "void"
CORRECTION_CORRECT = "correct"

# The event type of a correcting event.
CORRECTING_EVENT_TYPE = "administrative_correction"

# Narrative event types a GM may record or use as a replacement through the authoring
# surface: no effects of their own, so they never need a writer.
RECORDABLE_NARRATIVE_TYPES = ("other", "session_narrative")

EVENT_NAME_MAX_LENGTH = 500
EVENT_DETAILS_MAX_LENGTH = 4000

# Effect components whose compensation exists today. Anything else refuses.
REVERSIBLE_COMPONENTS = frozenset(
    {
        "current_hit_points",
        "character_build_id",
        "party_membership",
        "quest_status_id",
        "objective_status_id",
    }
)

REASON_STATE_CHANGED = "state_changed"
REASON_UNSUPPORTED = "unsupported_effect"
REASON_NOT_APPLIED = "effect_not_applied"


class EventNotFoundError(DomainAuthorizationError):
    """A nonexistent event, one on another timeline (an ancestor's, a sibling's), or one of
    another world: one fixed 404."""


class EventAlreadyCorrectedError(SafeMessageError):
    """Only a recorded event can be corrected, and only once."""

    safe_status_code = 409
    safe_error_code = "event_already_corrected"
    safe_message = "This event has already been voided or corrected, or is not recorded."


class EventNotCorrectableError(SafeMessageError):
    """A correction cannot itself be corrected."""

    safe_status_code = 409
    safe_error_code = "event_not_correctable"
    safe_message = "A correction cannot be corrected."


class CorrectionNotReversibleError(SafeMessageError):
    """Some effect of the event cannot be reversed: its state has changed since, or no
    safe reversal exists for it yet."""

    safe_status_code = 409
    safe_error_code = "correction_not_reversible"
    safe_message = (
        "This event cannot be corrected automatically: something it changed has changed "
        "since, or it changed something that cannot be reversed yet."
    )


@dataclass(frozen=True)
class ReplacementEvent:
    event_type_code: str
    name: str
    details: str | None
    world_time_id: object | None = None


def normalize_event_text(name: str | None, details: str | None) -> tuple[str, str | None]:
    clean_name = (name or "").strip()
    if not clean_name or len(clean_name) > EVENT_NAME_MAX_LENGTH:
        raise AuthoringValidationError("name must be 1 to 500 characters")
    clean_details = None if details is None or not details.strip() else details.strip()
    if clean_details is not None and len(clean_details) > EVENT_DETAILS_MAX_LENGTH:
        raise AuthoringValidationError("details must be at most 4000 characters")
    return clean_name, clean_details


def require_recordable_type(event_type_code: str) -> None:
    if event_type_code not in RECORDABLE_NARRATIVE_TYPES:
        raise AuthoringValidationError("event_type_code is not a recordable narrative type")
