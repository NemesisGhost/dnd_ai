"""Pure policy shared by the typed world-content authoring commands (Phase 15.1,
[ADR 0015](../../../docs/adr/0015-typed-world-content-authoring.md)).

Framework-free, like `dnd_ai.domain.entity_lifecycle`, which it extends. The
commands and the read models that tell the portal what a GM may do call the
**same** functions, so a preview cannot drift from enforcement:

- which canon/lifecycle states allow *editing* a definition
  (`content_edit_blocked_reason`);
- which records may be *newly referenced* by another definition
  (`is_reference_eligible`);
- the closed catalog of authorable location categories and their typed fields;
- the bounded `{field: {from, to}}` audit diff.

This module decides state legality and shapes data. Authority, scope binding,
`expected_row_version`, and locking are the command's job.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from .authoring import (
    AuthoringValidationError,
    normalize_description,
    normalize_name,
)
from .entity_lifecycle import (
    BLOCKED_ENTITY_ARCHIVED,
    BLOCKED_REVIEW_IN_PROGRESS,
    BLOCKED_WRONG_CANON_STATUS,
    CANON_APPROVED,
    CANON_CANON,
    CANON_DRAFT,
    CANON_PROPOSED,
    LIFECYCLE_ACTIVE,
    BlockedAction,
    evaluate_actions,
)

UPDATE = "update"

# Canon statuses a record may be edited in. `proposed` and `approved` are under
# review: they must return to draft first, so an approved record cannot change
# between approval and publish.
_EDITABLE_CANON_STATUSES = frozenset({CANON_DRAFT, CANON_CANON})
_REVIEW_CANON_STATUSES = frozenset({CANON_PROPOSED, CANON_APPROVED})

# A record may be newly referenced by another definition in these canon states.
_REFERENCEABLE_CANON_STATUSES = frozenset(
    {CANON_DRAFT, CANON_PROPOSED, CANON_APPROVED, CANON_CANON}
)

AUDIT_VALUE_MAX_LENGTH = 1000


def content_edit_blocked_reason(canon_status: str, lifecycle_status: str) -> str | None:
    """Why a definition cannot be edited from this state, or `None`."""
    if lifecycle_status != LIFECYCLE_ACTIVE:
        return BLOCKED_ENTITY_ARCHIVED
    if canon_status in _EDITABLE_CANON_STATUSES:
        return None
    if canon_status in _REVIEW_CANON_STATUSES:
        return BLOCKED_REVIEW_IN_PROGRESS
    return BLOCKED_WRONG_CANON_STATUS


def is_reference_eligible(canon_status: str, lifecycle_status: str) -> bool:
    """Whether a record may be *newly* referenced (a parent, headquarters,
    origin, target, or subject). Existing references to a record that later
    becomes archived or superseded are kept; this gates new ones only."""
    return lifecycle_status == LIFECYCLE_ACTIVE and canon_status in _REFERENCEABLE_CANON_STATUSES


def is_publish_reference_ready(canon_status: str, lifecycle_status: str) -> bool:
    """Whether a referenced record is published (`canon` and `active`), the
    precondition for publishing the record that refers to it."""
    return lifecycle_status == LIFECYCLE_ACTIVE and canon_status == CANON_CANON


def evaluate_content_actions(
    *,
    entity_type_code: str,
    canon_status: str,
    lifecycle_status: str,
    extra_blocked: Mapping[str, str] | None = None,
) -> tuple[list[str], list[BlockedAction]]:
    """`(available_actions, blocked_actions)` for an authorable definition: the
    Phase 14 lifecycle evaluation, plus `update`, plus type-specific blocks
    (`extra_blocked`, action -> reason) such as an unpublished parent blocking
    `publish`."""
    available, blocked = evaluate_actions(
        entity_type_code=entity_type_code,
        canon_status=canon_status,
        lifecycle_status=lifecycle_status,
        extra_blocked=extra_blocked,
    )
    reason = content_edit_blocked_reason(canon_status, lifecycle_status)
    if reason is None:
        return [UPDATE, *available], blocked
    return available, [BlockedAction(action=UPDATE, reason=reason), *blocked]


# --- Bounded audit diff ---------------------------------------------------------


def _bounded(value: object) -> object:
    if isinstance(value, str) and len(value) > AUDIT_VALUE_MAX_LENGTH:
        return {"value": value[:AUDIT_VALUE_MAX_LENGTH], "truncated": True}
    return value


def diff_fields(
    before: Mapping[str, object], after: Mapping[str, object]
) -> dict[str, dict[str, object]]:
    """`{field: {"from": old, "to": new}}` for every field whose value changed.
    Free-text values are truncated to `AUDIT_VALUE_MAX_LENGTH` with a
    `truncated` marker; reference fields are IDs and are passed as strings."""
    changed: dict[str, dict[str, object]] = {}
    for key, new_value in after.items():
        old_value = before.get(key)
        if old_value != new_value:
            changed[key] = {"from": _bounded(old_value), "to": _bounded(new_value)}
    return changed


def initial_fields(values: Mapping[str, object]) -> dict[str, object]:
    """Bounded initial values for a `created` audit row (non-null fields only)."""
    return {key: _bounded(value) for key, value in values.items() if value is not None}


# --- Typed field normalization --------------------------------------------------

SHORT_TEXT_MAX_LENGTH = 200
POPULATION_MAX = 2_147_483_647


def normalize_short_text(value: str | None, *, field: str) -> str | None:
    """An optional single-line field: stripped, blank becomes NULL, at most 200."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) > SHORT_TEXT_MAX_LENGTH:
        raise AuthoringValidationError(f"{field} exceeds {SHORT_TEXT_MAX_LENGTH} characters")
    return stripped


def normalize_population(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise AuthoringValidationError("population must be an integer")
    if value < 0 or value > POPULATION_MAX:
        raise AuthoringValidationError("population is out of range")
    return value


# --- Location categories --------------------------------------------------------


@dataclass(frozen=True)
class FieldDescriptor:
    """A typed field a category carries, for the portal to render."""

    name: str
    kind: str  # "integer" | "text"
    label: str
    max_length: int | None = None
    minimum: int | None = None
    maximum: int | None = None


@dataclass(frozen=True)
class LocationCategory:
    code: str
    label: str
    fields: tuple[FieldDescriptor, ...] = ()


_POPULATION = FieldDescriptor(
    name="population", kind="integer", label="Population", minimum=0, maximum=POPULATION_MAX
)
_BUILDING_USE = FieldDescriptor(
    name="building_use", kind="text", label="Use", max_length=SHORT_TEXT_MAX_LENGTH
)

# Dungeons and dungeon areas are deliberately absent (structural 15A work).
LOCATION_CATEGORIES: tuple[LocationCategory, ...] = (
    LocationCategory("location", "Location"),
    LocationCategory("plane", "Plane"),
    LocationCategory("realm", "Realm"),
    LocationCategory("continent", "Continent"),
    LocationCategory("nation", "Nation"),
    LocationCategory("region", "Region"),
    LocationCategory("district", "District"),
    LocationCategory("geographic_feature", "Geographic feature"),
    LocationCategory("settlement", "Settlement", (_POPULATION,)),
    LocationCategory("building", "Building", (_BUILDING_USE,)),
)
AUTHORABLE_LOCATION_CATEGORIES: frozenset[str] = frozenset(c.code for c in LOCATION_CATEGORIES)
_LOCATION_CATEGORY_BY_CODE = {c.code: c for c in LOCATION_CATEGORIES}


def location_category(code: str) -> LocationCategory:
    category = _LOCATION_CATEGORY_BY_CODE.get(code)
    if category is None:
        raise AuthoringValidationError("category is not an authorable location category")
    return category


def normalize_location_fields(
    *,
    category_code: str,
    name: str | None,
    summary: str | None,
    population: int | None,
    building_use: str | None,
) -> tuple[str, str | None, int | None, str | None]:
    """Validate and normalize a location's editable fields for its category.
    A typed field that does not apply to the category must be absent."""
    category = location_category(category_code)
    applicable = {f.name for f in category.fields}
    normalized_name = normalize_name(name)
    normalized_summary = normalize_description(summary)
    normalized_population = normalize_population(population)
    normalized_use = normalize_short_text(building_use, field="building_use")
    if normalized_population is not None and "population" not in applicable:
        raise AuthoringValidationError("population does not apply to this category")
    if normalized_use is not None and "building_use" not in applicable:
        raise AuthoringValidationError("building_use does not apply to this category")
    return normalized_name, normalized_summary, normalized_population, normalized_use
