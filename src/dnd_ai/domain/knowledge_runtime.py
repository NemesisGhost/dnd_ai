"""Knowledge runtime policy (Phase 15 checkpoint 15.2E-3, decision D-17).

Who knows a claim is per-knower timeline state, kept apart from the claim (its statement and
truth) and from history. The audiences are a party (`campaign.party_knowledge`), a character,
NPC or organization (`knowledge.entity_knowledge`), and everyone at a location
(`knowledge.public_knowledge`). Learning, transferring, changing a belief and making a claim
public each record one causal event with its effects, atomically. A belief never changes the
claim's truth, and a false belief is valid data.
"""

from .authoring import AuthoringValidationError
from .errors import SafeMessageError

AWARENESS_LEVELS = ("aware", "rumored", "suspected")
TRANSFER_METHODS = (
    "dialogue",
    "written_message",
    "public_announcement",
    "rumor",
    "telepathy",
    "magical_vision",
    "other",
)

# Entity types that can hold a belief of their own.
KNOWER_TYPE_CODES = frozenset(
    {
        "npc",
        "player_character",
        "organization",
        "business",
        "government",
        "religious_organization",
        "military_unit",
        "political_faction",
    }
)

# Places a claim can be public at (every kind of `world.locations` row).
LOCATION_TYPE_CODES = frozenset(
    {
        "location",
        "settlement",
        "building",
        "plane",
        "continent",
        "nation",
        "region",
        "district",
        "geographic_feature",
        "realm",
    }
)

INTERPRETATION_MAX_LENGTH = 4000

# Effect components the knowledge runtime writes (the correction catalog reverses them).
COMPONENT_LEARNED = "knowledge_learned"
COMPONENT_PUBLIC = "knowledge_public"
BELIEF_COMPONENTS = {
    "awareness_level": "belief_awareness_level",
    "confidence": "belief_confidence",
    "interpretation": "belief_interpretation",
    "willing_to_share": "belief_willing_to_share",
}


def normalize_awareness(value: str) -> str:
    if value not in AWARENESS_LEVELS:
        raise AuthoringValidationError("awareness_level is not one of aware, rumored, suspected")
    return value


def normalize_confidence(value: int | None) -> int | None:
    if value is not None and not 0 <= value <= 100:
        raise AuthoringValidationError("confidence must be from 0 to 100")
    return value


def normalize_interpretation(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    clean = value.strip()
    if len(clean) > INTERPRETATION_MAX_LENGTH:
        raise AuthoringValidationError("interpretation must be at most 4000 characters")
    return clean


class KnowerInvalidError(SafeMessageError):
    """The knower must be a published, active character, NPC or organization of the world."""

    safe_status_code = 400
    safe_error_code = "knower_invalid"
    safe_message = "Choose a published character, NPC or organization."


class KnowerAlreadyKnowsError(SafeMessageError):
    """One current belief per knower and claim; later changes are belief changes."""

    safe_status_code = 409
    safe_error_code = "knower_already_knows"
    safe_message = "That knower already has this claim. Change their belief instead."


class SourceDoesNotKnowError(SafeMessageError):
    """A transfer starts from a knower who currently holds the claim."""

    safe_status_code = 409
    safe_error_code = "source_does_not_know"
    safe_message = "The source does not know this claim."


class LocationInvalidError(SafeMessageError):
    """Public knowledge is held at a published, active location of the world."""

    safe_status_code = 400
    safe_error_code = "location_invalid"
    safe_message = "Choose a published location."


class AlreadyPublicError(SafeMessageError):
    """One current public row per claim and location."""

    safe_status_code = 409
    safe_error_code = "knowledge_already_public"
    safe_message = "This claim is already public at that location."
