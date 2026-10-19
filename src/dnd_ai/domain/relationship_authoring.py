"""World relationship authoring policy (Phase 15 checkpoint 15.3A-2a, decision D-18, ADR 0017).

A world relationship is a shared, objective fact about how entities are connected; how each
participant feels about it is a per-holder perspective (a baseline, authored here) and the
current, event-driven status is timeline state (`campaign.relationship_state`, written by
`evolve_relationship_reaction`). This module holds the closed catalogs and rules the commands
and the editor read model share: the authorable kinds, which relationship types and participant
roles each takes, and the errors. Membership in an organization is the next checkpoint
(15.3A-2b); routes are 15.3A-2c.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from .authoring import AuthoringValidationError
from .errors import SafeMessageError

KIND_FAMILY = "family"
KIND_EMPLOYMENT = "employment"
KIND_OWNERSHIP = "ownership"
KIND_POLITICAL = "political"
KIND_GENERAL = "general"
KIND_MEMBERSHIP = "membership"
KIND_ROUTE = "route"


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


# Entity groups (subtype codes from `core.entity_types`). The compatibility policy below and the
# membership and route commands share these.
PERSON_TYPE_CODES = frozenset({"npc", "player_character"})
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
RELIGION_TYPE_CODES = frozenset({"religion"})
PLACE_TYPE_CODES = frozenset(
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
    }
)
# A place that can act politically (ally, rival, ruler, worshipper).
POLITY_PLACE_TYPE_CODES = frozenset(
    {"nation", "region", "realm", "settlement", "district", "location"}
)
MEMBER_TYPE_CODES = PERSON_TYPE_CODES | ORGANIZATION_TYPE_CODES

# Entity types that can take part in a relationship: places, organizations, religions and
# characters (items and events are not related this way).
PARTICIPANT_TYPE_CODES = (
    PLACE_TYPE_CODES | ORGANIZATION_TYPE_CODES | RELIGION_TYPE_CODES | PERSON_TYPE_CODES
)

_POLITICAL_ACTORS = (
    PERSON_TYPE_CODES | ORGANIZATION_TYPE_CODES | RELIGION_TYPE_CODES | POLITY_PLACE_TYPE_CODES
)


@dataclass(frozen=True)
class RolePolicy:
    code: str
    # Reads in the direction of the relationship ("Worshipper", "Controlled place").
    label: str
    entity_type_codes: frozenset[str]


@dataclass(frozen=True)
class RelationshipTypePolicy:
    """What one relationship type may connect. Applied when a relationship is created; participants
    and type are fixed afterwards (ADR 0017), so later commands never re-check it."""

    code: str
    kind: str
    roles: tuple[RolePolicy, ...]
    symmetric: bool = False
    min_participants: int = 2
    max_participants: int = 20
    # Each set must be held by at least one participant ({"ruler"}, {"territory", "object"}).
    required_roles: tuple[frozenset[str], ...] = ()
    # A fixed-shape type has exactly these roles, once each.
    exact_roles: tuple[str, ...] | None = None
    distinct_entities: bool = False
    # Both participants of a two-sided type must come from the same one of these groups.
    same_group_of: tuple[frozenset[str], ...] = ()
    # Route and membership keep their original refusal (`participant_invalid`).
    legacy_entity_error: bool = False

    def role(self, code: str) -> RolePolicy | None:
        return next((r for r in self.roles if r.code == code), None)


def _roles(codes: frozenset[str], *labelled: tuple[str, str]) -> tuple[RolePolicy, ...]:
    return tuple(RolePolicy(code, label, codes) for code, label in labelled)


def _fixed(
    code: str, kind: str, *roles: RolePolicy, legacy: bool = False
) -> RelationshipTypePolicy:
    return RelationshipTypePolicy(
        code,
        kind,
        roles,
        min_participants=2,
        max_participants=2,
        exact_roles=tuple(r.code for r in roles),
        distinct_entities=True,
        legacy_entity_error=legacy,
    )


_PARENT_GROUPS = (RELIGION_TYPE_CODES, ORGANIZATION_TYPE_CODES, PLACE_TYPE_CODES)
_ADJACENT_PLACES = PLACE_TYPE_CODES - {"dungeon_area"}
_PERSON_OR_ORG = PERSON_TYPE_CODES | ORGANIZATION_TYPE_CODES
_ANY = PARTICIPANT_TYPE_CODES

RELATIONSHIP_TYPE_POLICIES: dict[str, RelationshipTypePolicy] = {
    p.code: p
    for p in (
        RelationshipTypePolicy(
            "family",
            KIND_FAMILY,
            _roles(
                PERSON_TYPE_CODES,
                ("parent", "Parent"),
                ("child", "Child"),
                ("subject", "Subject"),
                ("object", "Object"),
                ("other", "Other"),
            ),
        ),
        _fixed(
            "employment",
            KIND_EMPLOYMENT,
            RolePolicy("employer", "Employer", _PERSON_OR_ORG),
            RolePolicy("employee", "Employee", _PERSON_OR_ORG),
        ),
        _fixed(
            "ownership",
            KIND_OWNERSHIP,
            RolePolicy(
                "owner", "Owner", PERSON_TYPE_CODES | ORGANIZATION_TYPE_CODES | RELIGION_TYPE_CODES
            ),
            RolePolicy(
                "property",
                "Owned",
                PERSON_TYPE_CODES | PLACE_TYPE_CODES | ORGANIZATION_TYPE_CODES,
            ),
        ),
        _fixed(
            "membership",
            KIND_MEMBERSHIP,
            RolePolicy("member", "Member", MEMBER_TYPE_CODES),
            RolePolicy("organization", "Organization", ORGANIZATION_TYPE_CODES),
            legacy=True,
        ),
        _fixed(
            "route",
            KIND_ROUTE,
            RolePolicy("origin", "Origin", PLACE_TYPE_CODES),
            RolePolicy("destination", "Destination", PLACE_TYPE_CODES),
            legacy=True,
        ),
        RelationshipTypePolicy(
            "alliance",
            KIND_POLITICAL,
            _roles(_POLITICAL_ACTORS, ("ally", "Ally")),
            symmetric=True,
        ),
        RelationshipTypePolicy(
            "rivalry",
            KIND_POLITICAL,
            _roles(_POLITICAL_ACTORS, ("rival", "Rival")),
            symmetric=True,
        ),
        RelationshipTypePolicy(
            "war",
            KIND_POLITICAL,
            _roles(
                _POLITICAL_ACTORS,
                ("subject", "Side A"),
                ("object", "Side B"),
                ("other", "Third party"),
            ),
            required_roles=(frozenset({"subject"}), frozenset({"object"})),
        ),
        RelationshipTypePolicy(
            "control",
            KIND_POLITICAL,
            (
                RolePolicy("ruler", "Controller", _POLITICAL_ACTORS),
                RolePolicy("territory", "Controlled place", PLACE_TYPE_CODES),
                RolePolicy("object", "Controlled party", _PERSON_OR_ORG),
            ),
            required_roles=(frozenset({"ruler"}), frozenset({"territory", "object"})),
        ),
        RelationshipTypePolicy(
            "worship",
            KIND_GENERAL,
            (
                RolePolicy(
                    "subject",
                    "Worshipper",
                    PERSON_TYPE_CODES | ORGANIZATION_TYPE_CODES | PLACE_TYPE_CODES,
                ),
                RolePolicy(
                    "object",
                    "Worshipped",
                    RELIGION_TYPE_CODES
                    | PERSON_TYPE_CODES
                    | PLACE_TYPE_CODES
                    | ORGANIZATION_TYPE_CODES,
                ),
            ),
            required_roles=(frozenset({"subject"}), frozenset({"object"})),
        ),
        RelationshipTypePolicy(
            "adjacency",
            KIND_GENERAL,
            _roles(_ADJACENT_PLACES, ("subject", "Adjoining place"), ("object", "Adjoining place")),
            symmetric=True,
            max_participants=2,
            required_roles=(frozenset({"subject"}), frozenset({"object"})),
            distinct_entities=True,
        ),
        RelationshipTypePolicy(
            "capital_of",
            KIND_GENERAL,
            (
                RolePolicy("subject", "Capital", frozenset({"settlement", "location"})),
                RolePolicy(
                    "object",
                    "Governed place",
                    frozenset({"nation", "region", "realm", "continent", "plane", "location"}),
                ),
            ),
            max_participants=2,
            required_roles=(frozenset({"subject"}), frozenset({"object"})),
            distinct_entities=True,
        ),
        RelationshipTypePolicy(
            "parent_of",
            KIND_GENERAL,
            (
                RolePolicy(
                    "subject",
                    "Parent",
                    RELIGION_TYPE_CODES | ORGANIZATION_TYPE_CODES | PLACE_TYPE_CODES,
                ),
                RolePolicy(
                    "object",
                    "Child",
                    RELIGION_TYPE_CODES | ORGANIZATION_TYPE_CODES | PLACE_TYPE_CODES,
                ),
            ),
            max_participants=2,
            required_roles=(frozenset({"subject"}), frozenset({"object"})),
            distinct_entities=True,
            same_group_of=_PARENT_GROUPS,
        ),
        RelationshipTypePolicy(
            "other",
            KIND_GENERAL,
            _roles(_ANY, ("subject", "Subject"), ("object", "Object"), ("other", "Other")),
        ),
    )
}

# Catalog order of roles within a kind (kept stable for the options payload).
_ROLE_ORDER = (
    "parent",
    "child",
    "subject",
    "object",
    "ally",
    "rival",
    "ruler",
    "territory",
    "other",
    "employer",
    "employee",
    "owner",
    "property",
    "member",
    "organization",
    "origin",
    "destination",
)

_KIND_LABELS = (
    (KIND_FAMILY, "Family"),
    (KIND_EMPLOYMENT, "Employment"),
    (KIND_OWNERSHIP, "Ownership"),
    (KIND_MEMBERSHIP, "Membership"),
    (KIND_ROUTE, "Route"),
    (KIND_POLITICAL, "Political"),
    (KIND_GENERAL, "Other connection"),
)


def _derive_kind(code: str, label: str) -> RelationshipKind:
    policies = [p for p in RELATIONSHIP_TYPE_POLICIES.values() if p.kind == code]
    roles = {r.code for p in policies for r in p.roles}
    fixed = policies[0].exact_roles if len(policies) == 1 else None
    return RelationshipKind(
        code,
        label,
        tuple(p.code for p in policies),
        tuple(sorted(roles, key=_ROLE_ORDER.index)),
        fixed_roles=fixed,
    )


# Derived from the policies, so the kind catalog and the type policy cannot disagree.
RELATIONSHIP_KINDS: tuple[RelationshipKind, ...] = tuple(
    _derive_kind(code, label) for code, label in _KIND_LABELS
)
_KIND_BY_CODE = {k.code: k for k in RELATIONSHIP_KINDS}


def _humanize(code: str) -> str:
    return code.replace("_", " ")


@dataclass(frozen=True)
class PolicyViolation:
    # "shape": the type, roles or counts do not fit; "entity": a participant cannot take its role.
    category: str
    message: str


# One participant as the policy sees it: role code, entity type code, optional display name.
PolicyParticipant = tuple[str, str] | tuple[str, str, str]


def _violations(
    policy: RelationshipTypePolicy,
    participants: list[PolicyParticipant],
    entity_ids: Sequence[object] | None = None,
) -> list[PolicyViolation]:
    found: list[PolicyViolation] = []
    if (
        policy.distinct_entities
        and entity_ids is not None
        and len(set(entity_ids)) != len(entity_ids)
    ):
        found.append(
            PolicyViolation(
                "shape", f"The same record cannot be on both sides of {_humanize(policy.code)}."
            )
        )
    roles = [p[0] for p in participants]
    for role in dict.fromkeys(roles):
        if policy.role(role) is None:
            found.append(
                PolicyViolation(
                    "shape", f"{_humanize(role).capitalize()} is not a role of this type."
                )
            )
    if not policy.min_participants <= len(participants) <= policy.max_participants:
        found.append(
            PolicyViolation(
                "shape",
                f"This type has {policy.min_participants} to {policy.max_participants} participants.",
            )
        )
    if policy.exact_roles is not None and sorted(roles) != sorted(policy.exact_roles):
        found.append(PolicyViolation("shape", f"This type needs exactly {policy.exact_roles}."))
    for needed in policy.required_roles:
        if not needed.intersection(roles):
            found.append(
                PolicyViolation("shape", f"This type needs a {' or '.join(sorted(needed))} role.")
            )
    for item in participants:
        role, entity_type = item[0], item[1]
        role_policy = policy.role(role)
        if role_policy is None or entity_type in role_policy.entity_type_codes:
            continue
        who = item[2] if len(item) == 3 else "A participant"
        found.append(
            PolicyViolation(
                "entity",
                f"{who} ({_humanize(entity_type)}) cannot be the {role_policy.label.lower()} "
                f"in {_humanize(policy.code)}.",
            )
        )
    if policy.same_group_of and len(participants) == 2:
        groups = [
            next((i for i, g in enumerate(policy.same_group_of) if p[1] in g), None)
            for p in participants
        ]
        if None not in groups and groups[0] != groups[1]:
            found.append(
                PolicyViolation(
                    "entity",
                    f"Both sides of {_humanize(policy.code)} must be the same kind of record.",
                )
            )
    return found


def validate_participants(
    policy: RelationshipTypePolicy, participants: list[PolicyParticipant]
) -> None:
    """Raise unless the roles, counts and each participant's entity type fit the type's policy."""
    violations = _violations(policy, participants)
    shape = [v for v in violations if v.category == "shape"]
    if shape:
        raise RelationshipInvalidError(shape[0].message)
    if violations:
        error: type[SafeMessageError] = (
            RelationshipParticipantInvalidError
            if policy.legacy_entity_error
            else RelationshipParticipantIncompatibleError
        )
        raise error(violations[0].message)


def policy_conflicts(
    relationship_type: str,
    participants: list[PolicyParticipant],
    *,
    type_offered: bool = True,
    entity_ids: Sequence[object] | None = None,
) -> list[str]:
    """Plain reasons the current policy would refuse a stored relationship; empty when it fits.
    Reports only what the policy says about the stored roles and entity types."""
    policy = RELATIONSHIP_TYPE_POLICIES.get(relationship_type)
    if policy is None or not type_offered:
        return ["This type of relationship is no longer offered."]
    return [v.message for v in _violations(policy, participants, entity_ids)]


@dataclass(frozen=True)
class TypePairing:
    relationship_type: str
    my_role: str
    other_role: str
    other_entity_type_codes: tuple[str, ...]


def pairs_for(entity_type_code: str) -> list[TypePairing]:
    """Every (my role, other role) that the entity can take in a two-participant relationship of
    each type, with the entity types the counterpart may be. Computed from the policies."""
    pairings: list[TypePairing] = []
    for policy in RELATIONSHIP_TYPE_POLICIES.values():
        if policy.max_participants < 2 or policy.min_participants > 2:
            continue
        for mine in policy.roles:
            if entity_type_code not in mine.entity_type_codes:
                continue
            for theirs in policy.roles:
                if not _two_sided_fits(policy, mine.code, theirs.code):
                    continue
                others = theirs.entity_type_codes
                if policy.same_group_of:
                    group = next((g for g in policy.same_group_of if entity_type_code in g), None)
                    if group is None:
                        continue
                    others = others & group
                if others:
                    pairings.append(
                        TypePairing(policy.code, mine.code, theirs.code, tuple(sorted(others)))
                    )
    return pairings


def _two_sided_fits(policy: RelationshipTypePolicy, first: str, second: str) -> bool:
    roles = [first, second]
    if policy.exact_roles is not None:
        return sorted(roles) == sorted(policy.exact_roles)
    return all(needed.intersection(roles) for needed in policy.required_roles)


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


# Membership (15.3A-2b) and routes (15.3A-2c) use the entity groups above; travel moves
# characters between places.
MAX_TRAVELERS = 50


class RouteMismatchError(SafeMessageError):
    """The route does not join where the travelers are to where they are going."""

    safe_status_code = 409
    safe_error_code = "route_mismatch"
    safe_message = "That route does not join where the travelers are to where they are going."


class TravelInvalidError(SafeMessageError):
    """Travel needs a published destination and at least one published traveler."""

    safe_status_code = 400
    safe_error_code = "travel_invalid"
    safe_message = "Choose a published destination and at least one traveler."


class TravelTimeInvalidError(SafeMessageError):
    """Travelers leave a place after they arrived there."""

    safe_status_code = 409
    safe_error_code = "travel_time_invalid"
    safe_message = "Choose a time after the travelers arrived where they are."


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


class RelationshipParticipantIncompatibleError(SafeMessageError):
    """A usable participant cannot take that role in this type of relationship."""

    safe_status_code = 400
    safe_error_code = "participant_incompatible"
    safe_message = "That participant cannot take that role in this type of relationship."


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
