"""Encounter preparation policy (Phase 15 checkpoint 15.3B-2a, decision D-23).

A GM prepares an encounter in a session before it starts: where it happens, who takes part and
on which side. A prepared encounter is `pending`; only a pending encounter's details and
participants can change (starting, running and ending it are checkpoint 15.3B-2b). Participants
are existing published characters of the world; creatures are Phase 19.
"""

from .authoring import AuthoringValidationError
from .errors import SafeMessageError

SIDES = (
    ("party", "Party"),
    ("ally", "Ally"),
    ("enemy", "Enemy"),
    ("neutral", "Neutral"),
)
SIDE_CODES = frozenset(code for code, _ in SIDES)
PARTICIPANT_TYPE_CODES = frozenset({"npc", "player_character", "character"})
MAX_PARTICIPANTS = 50
SUMMARY_MAX_LENGTH = 4000
INITIATIVE_MIN = -100
INITIATIVE_MAX = 1000


def normalize_side(value: str) -> str:
    if value not in SIDE_CODES:
        raise AuthoringValidationError("side is not one of party, ally, enemy, neutral")
    return value


def normalize_initiative(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise AuthoringValidationError("initiative must be a whole number")
    if not INITIATIVE_MIN <= value <= INITIATIVE_MAX:
        raise AuthoringValidationError("initiative is out of range")
    return value


def normalize_summary(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    clean = value.strip()
    if len(clean) > SUMMARY_MAX_LENGTH:
        raise AuthoringValidationError(f"summary must be at most {SUMMARY_MAX_LENGTH} characters")
    return clean


class EncounterNotPendingError(SafeMessageError):
    """Only a pending encounter can be prepared."""

    safe_status_code = 409
    safe_error_code = "encounter_not_pending"
    safe_message = "This encounter has already started or finished."


class EncounterParticipantInvalidError(SafeMessageError):
    safe_status_code = 400
    safe_error_code = "encounter_participant_invalid"
    safe_message = "Choose a published character or place in this world."


class EncounterParticipantExistsError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "encounter_participant_exists"
    safe_message = "That character is already in this encounter."


class EncounterParticipantNotFoundError(SafeMessageError):
    safe_status_code = 404
    safe_error_code = "not_found"
    safe_message = "Not found."


class EncounterFullError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "encounter_full"
    safe_message = "This encounter has as many participants as it can hold."


class EncounterSessionNotUsableError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "session_not_usable"
    safe_message = "Encounters cannot be prepared in an archived session."
