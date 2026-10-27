"""NPC portrayal policy (Phase 15 checkpoint 15.3A-3, decision D-21).

An NPC has a detail level (how much authoring it deserves) and versioned portrayal guidance for
whoever plays it. Both are GM-only definition data. Goals, routines, preferences and per-timeline
emotional state are Phase 20, and the AI context builder does not read the profile yet.
"""

from .authoring import AuthoringValidationError
from .errors import SafeMessageError

DETAIL_LEVELS = (
    ("minimal", "Minimal: a background figure"),
    ("standard", "Standard: a named NPC"),
    ("major", "Major: a fully portrayed NPC"),
)
DETAIL_LEVEL_CODES = frozenset(code for code, _ in DETAIL_LEVELS)

PROFILE_FIELDS = (
    ("voice", "Voice"),
    ("speech_style", "Speech style"),
    ("vocabulary", "Vocabulary"),
    ("mannerisms", "Mannerisms"),
    ("emotional_baseline", "Emotional baseline"),
    ("conversational_habits", "Conversational habits"),
    ("topics_avoided", "Topics avoided"),
    ("disclosure_boundaries", "Disclosure boundaries"),
    ("roleplay_guidance", "Roleplay guidance"),
)
PROFILE_FIELD_NAMES = tuple(name for name, _ in PROFILE_FIELDS)
FIELD_MAX_LENGTH = 4000
NOTE_MAX_LENGTH = 1000


def normalize_detail_level(value: str) -> str:
    if value not in DETAIL_LEVEL_CODES:
        raise AuthoringValidationError("detail_level is not one of minimal, standard, major")
    return value


def normalize_profile_field(value: str | None, *, field: str) -> str | None:
    if value is None or not value.strip():
        return None
    clean = value.strip()
    if len(clean) > FIELD_MAX_LENGTH:
        raise AuthoringValidationError(f"{field} must be at most {FIELD_MAX_LENGTH} characters")
    return clean


class PortrayalVersionNotFoundError(SafeMessageError):
    """No such version of this NPC portrayal."""

    safe_status_code = 404
    safe_error_code = "portrayal_version_not_found"
    safe_message = "That version does not exist."
