"""Dungeon authoring and runtime-state policy (Phase 15 checkpoint 15.3A-1, decision D-31).

A dungeon is a location composed of areas; an area is a location too. Both are
lifecycle-managed definitions (draft, then published). Their structural children (connections,
features, hazards, interactables) are not entities: they belong to the aggregate whose root is
the dungeon (decision D-31, option a). The dungeon's `row_version` covers every structural
child of every one of its areas, while an area's own `row_version` covers only the area's own
fields. What is currently true in a timeline (a door open, a trap triggered) is timeline state,
changed by explicit GM commands that record an event; the definition is never touched by it.
"""

from .authoring import AuthoringValidationError
from .content_authoring import SHORT_TEXT_MAX_LENGTH, normalize_short_text
from .errors import SafeMessageError

DUNGEON_TYPE = "dungeon"
AREA_TYPE = "dungeon_area"

RATING_MIN = 1
RATING_MAX = 10
ALARM_LEVEL_MAX = 1000
NOTES_MAX_LENGTH = 4000
MAX_AREAS = 500
MAX_CHILDREN_PER_AREA = 200

# Structural child kinds, as they appear in routes and audit.
CHILD_KINDS = ("feature", "hazard", "interactable")

# State targets, as they appear in the state route.
STATE_KINDS = ("area", "connection", "feature", "hazard", "interactable")


def normalize_rating(value: int | None, *, field: str) -> int | None:
    if value is None:
        return None
    if not RATING_MIN <= value <= RATING_MAX:
        raise AuthoringValidationError(f"{field} must be from {RATING_MIN} to {RATING_MAX}")
    return value


def normalize_child_text(value: str | None, *, field: str) -> str | None:
    return normalize_short_text(value, field=field)


def normalize_long_text(value: str | None, *, field: str) -> str | None:
    if value is None or not value.strip():
        return None
    clean = value.strip()
    if len(clean) > NOTES_MAX_LENGTH:
        raise AuthoringValidationError(f"{field} must be at most {NOTES_MAX_LENGTH} characters")
    return clean


def normalize_alarm_level(value: int) -> int:
    if not 0 <= value <= ALARM_LEVEL_MAX:
        raise AuthoringValidationError(f"alarm_level must be from 0 to {ALARM_LEVEL_MAX}")
    return value


__all__ = [
    "AREA_TYPE",
    "CHILD_KINDS",
    "DUNGEON_TYPE",
    "SHORT_TEXT_MAX_LENGTH",
    "STATE_KINDS",
]


class ConnectionInvalidError(SafeMessageError):
    """A connection joins two different areas of the one dungeon."""

    safe_status_code = 400
    safe_error_code = "connection_invalid"
    safe_message = "Choose two different areas of this dungeon."


class ConnectionTypeInvalidError(SafeMessageError):
    """The connection type is not one of the lookup values."""

    safe_status_code = 400
    safe_error_code = "connection_type_invalid"
    safe_message = "Choose a valid connection type."


class DungeonNotDraftError(SafeMessageError):
    """Structure is removed only while the dungeon is a draft; a published dungeon is
    changed in place or superseded."""

    safe_status_code = 409
    safe_error_code = "dungeon_not_draft"
    safe_message = "Structure can be removed only while the dungeon is a draft."


class DungeonHasActiveAreasError(SafeMessageError):
    """A dungeon with active areas cannot be archived."""

    safe_status_code = 409
    safe_error_code = "dungeon_has_active_areas"
    safe_message = "Archive the dungeon's areas first."


class DungeonLimitError(SafeMessageError):
    """A bounded count was reached."""

    safe_status_code = 409
    safe_error_code = "dungeon_limit_reached"
    safe_message = "This dungeon has reached its limit for that."


class StateTargetInvalidError(SafeMessageError):
    """The state change names something that is not in this dungeon area, or a value the
    target does not allow."""

    safe_status_code = 400
    safe_error_code = "state_target_invalid"
    safe_message = "That cannot be changed here."
