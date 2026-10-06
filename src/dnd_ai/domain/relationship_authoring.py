"""World relationship authoring policy (Phase 15 checkpoint 15.3A-2a, decision D-18, ADR 0017).

A world relationship is a shared, objective fact about how entities are connected; how each
participant feels about it is a per-holder perspective (a baseline, authored here) and the
current, event-driven status is timeline state (`campaign.relationship_state`, written by
`evolve_relationship_reaction`). This module holds the closed catalogs and rules the commands
and the editor read model share: the authorable kinds, which relationship types and participant
roles each takes, and the errors. Membership in an organization is the next checkpoint
(15.3A-2b); routes are 15.3A-2c.
"""

from dataclasses import dataclass

from .authoring import AuthoringValidationError
from .errors import SafeMessageError

KIND_FAMILY = "family"
KIND_EMPLOYMENT = "employment"
KIND_OWNERSHIP = "ownership"
KIND_POLITICAL = "political"
KIND_GENERAL = "general"
KIND_MEMBERSHIP = "membership"


@dataclass(frozen=True)
class RelationshipKind:
    code: str
    label: str
    # `world.relationship_types` codes this kind may take.
    types: tuple[str, ...]
    # `world.relationship_participant_roles` codes a participant of this kind may hold.
    roles: tuple[str, ...]
    # For a fixed-shape kind, exactly these roles once each (employer and employee).
    fixed_roles: tuple[str, ...] | None = None


RELATIONSHIP_KINDS: tuple[RelationshipKind, ...] = (
    RelationshipKind(
        KIND_FAMILY, "Family", ("family",), ("parent", "child", "subject", "object", "other")
    ),
    RelationshipKind(
        KIND_EMPLOYMENT,
        "Employment",
        ("employment",),
        ("employer", "employee"),
        fixed_roles=("employer", "employee"),
    ),
    RelationshipKind(
        KIND_OWNERSHIP,
        "Ownership",
        ("ownership",),
        ("owner", "property"),
        fixed_roles=("owner", "property"),
    ),
    RelationshipKind(
        KIND_MEMBERSHIP,
        "Membership",
        ("membership",),
        ("member", "organization"),
        fixed_roles=("member", "organization"),
    ),
    RelationshipKind(
        KIND_POLITICAL,
        "Political",
        ("alliance", "rivalry", "war", "control"),
        ("subject", "object", "ally", "rival", "ruler", "territory", "other"),
    ),
    RelationshipKind(
        KIND_GENERAL,
        "Other connection",
        ("worship", "adjacency", "capital_of", "parent_of", "other"),
        ("subject", "object", "other"),
    ),
)
_KIND_BY_CODE = {k.code: k for k in RELATIONSHIP_KINDS}

# Entity types that can take part in a relationship: places, organizations, religions and
# characters (items and events are not related this way).
PARTICIPANT_TYPE_CODES = frozenset(
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
        "dungeon",
        "dungeon_area",
        "organization",
        "business",
        "government",
        "religious_organization",
        "military_unit",
        "political_faction",
        "religion",
        "npc",
        "player_character",
    }
)

MIN_PARTICIPANTS = 2
MAX_PARTICIPANTS = 20
TEXT_MAX_LENGTH = 4000
SHORT_TEXT_MAX_LENGTH = 200
STANCE_MIN = -100
STANCE_MAX = 100


def relationship_kind(code: str) -> RelationshipKind:
    kind = _KIND_BY_CODE.get(code)
    if kind is None:
        raise RelationshipInvalidError(f"unknown relationship kind {code!r}")
    return kind


def validate_shape(kind: RelationshipKind, relationship_type: str, roles: list[str]) -> None:
    """The type belongs to the kind, every role is one the kind allows, and the number of
    participants fits (a fixed-shape kind has exactly its roles, once each)."""
    if relationship_type not in kind.types:
        raise RelationshipInvalidError(f"{relationship_type!r} is not a {kind.code} type")
    if any(role not in kind.roles for role in roles):
        raise RelationshipInvalidError("a participant role is not allowed for this kind")
    if kind.fixed_roles is not None:
        if sorted(roles) != sorted(kind.fixed_roles):
            raise RelationshipInvalidError(f"{kind.code} needs exactly {kind.fixed_roles}")
    elif not MIN_PARTICIPANTS <= len(roles) <= MAX_PARTICIPANTS:
        raise RelationshipInvalidError(
            f"a relationship has {MIN_PARTICIPANTS} to {MAX_PARTICIPANTS} participants"
        )


def normalize_text(value: str | None, *, field: str, limit: int = TEXT_MAX_LENGTH) -> str | None:
    if value is None or not value.strip():
        return None
    clean = value.strip()
    if len(clean) > limit:
        raise AuthoringValidationError(f"{field} must be at most {limit} characters")
    return clean


def normalize_share(value: int | None) -> int | None:
    if value is not None and not 0 <= value <= 100:
        raise AuthoringValidationError("ownership_share must be from 0 to 100")
    return value


def normalize_stance(value: int | None, *, field: str) -> int | None:
    if value is not None and not STANCE_MIN <= value <= STANCE_MAX:
        raise AuthoringValidationError(f"{field} must be from {STANCE_MIN} to {STANCE_MAX}")
    return value


# Membership (15.3A-2b): who may belong to an organization, and which entity is the organization.
ORGANIZATION_TYPE_CODES = frozenset(
    {
        "organization",
        "business",
        "government",
        "religious_organization",
        "military_unit",
        "political_faction",
    }
)
MEMBER_TYPE_CODES = frozenset({"npc", "player_character"}) | ORGANIZATION_TYPE_CODES


class MembershipOverlapError(SafeMessageError):
    """One stint at a time for the same member and organization."""

    safe_status_code = 409
    safe_error_code = "membership_overlap"
    safe_message = "That member already belongs to this organization during that time."


class MembershipStartRequiredError(SafeMessageError):
    """A membership begins at a world time."""

    safe_status_code = 400
    safe_error_code = "membership_start_required"
    safe_message = "Choose when the membership began."


class OrganizationStatusUnchangedError(SafeMessageError):
    """A status change must change the status."""

    safe_status_code = 409
    safe_error_code = "organization_status_unchanged"
    safe_message = "The organization already has that status."


class RelationshipInvalidError(SafeMessageError):
    """The kind, type, roles or participant count do not fit together."""

    safe_status_code = 400
    safe_error_code = "relationship_invalid"
    safe_message = "That is not a valid relationship."


class RelationshipParticipantInvalidError(SafeMessageError):
    """A participant must be a published, active place, organization, religion or character."""

    safe_status_code = 400
    safe_error_code = "participant_invalid"
    safe_message = "Choose published places, organizations, religions or characters."


class RelationshipTimeInvalidError(SafeMessageError):
    """A time is not in the world, or an end is not after the start."""

    safe_status_code = 400
    safe_error_code = "relationship_time_invalid"
    safe_message = "Choose times in this world, with the end after the start."


class RelationshipStartRequiredError(SafeMessageError):
    """A relationship can end only once it has a start."""

    safe_status_code = 409
    safe_error_code = "relationship_start_required"
    safe_message = "Set when the relationship started before ending it."


class RelationshipArchivedError(SafeMessageError):
    """An archived relationship is restored before it is changed."""

    safe_status_code = 409
    safe_error_code = "relationship_archived"
    safe_message = "This relationship is archived. Restore it first."


class RelationshipNotArchivedError(SafeMessageError):
    """Restore applies only to an archived relationship."""

    safe_status_code = 409
    safe_error_code = "relationship_not_archived"
    safe_message = "This relationship is not archived."


class RelationshipAlreadyEndedError(SafeMessageError):
    """A relationship ends once."""

    safe_status_code = 409
    safe_error_code = "relationship_already_ended"
    safe_message = "This relationship has already ended."


class PerspectiveHolderInvalidError(SafeMessageError):
    """Only a participant holds a perspective on the relationship."""

    safe_status_code = 400
    safe_error_code = "perspective_holder_invalid"
    safe_message = "Choose one of the relationship's participants."
