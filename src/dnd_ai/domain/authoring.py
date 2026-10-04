"""Shared vocabulary for Phase 14 authoring commands: bounded input
normalization, stable domain error codes, and the world-slug generator.

Framework-free (docs/architecture/SYSTEM_ARCHITECTURE.md §5.4). Every error
here is a `SafeMessageError` with a fixed, type-level `safe_status_code`,
`safe_error_code`, and `safe_message` — never derived from caller input — so
`dnd_ai.api.errors` returns it as a stable, client-branchable code without
any per-route handling. The codes are the closed vocabulary the portal maps
onto recovery paths (docs/UI_DESIGN.md §5.11): `stale_write` offers "load the
latest version", `lifecycle_transition_not_allowed` explains the state
precondition, and the field-mapped 400s (`ruleset_not_available`,
`branch_point_invalid`, `supersession_target_invalid`) land on one form field.

Validation limits mirror the table CHECK constraints and the Pydantic request
models, so a command called outside HTTP (a script, a test) is bounded the same
way as a request.
"""

import re

from .errors import DomainAuthorizationError, SafeMessageError

NAME_MAX_LENGTH = 200
DESCRIPTION_MAX_LENGTH = 4000
REASON_MAX_LENGTH = 1000
LABEL_MAX_LENGTH = 200
SLUG_MAX_LENGTH = 60


class AuthoringValidationError(SafeMessageError):
    """An authoring input failed a bounded structural rule (empty or
    over-long name, description, reason, or label). Fixed message: the
    offending value is never echoed."""

    safe_status_code = 400
    safe_error_code = "validation_failed"
    safe_message = "The request could not be processed."


class StaleWriteError(SafeMessageError):
    """`expected_row_version` no longer matches the row: someone else changed
    it since the caller read it. Distinct from an idempotency `conflict` and
    from a state-precondition `lifecycle_transition_not_allowed`, so a client
    can offer the right recovery (reload, then re-apply)."""

    safe_status_code = 409
    safe_error_code = "stale_write"
    safe_message = "The record was changed by someone else. Reload it and try again."


class LifecycleTransitionNotAllowedError(SafeMessageError):
    """The requested transition is not legal from the record's current state
    (ENTITY_LIFECYCLE §3, D8)."""

    safe_status_code = 409
    safe_error_code = "lifecycle_transition_not_allowed"
    safe_message = "That change is not allowed from the record's current state."


class LifecycleNotSupportedError(SafeMessageError):
    """The entity's type does not use shared canon lifecycle commands."""

    safe_status_code = 409
    safe_error_code = "lifecycle_not_supported"
    safe_message = "This kind of record is not managed through shared lifecycle commands."


class WorldArchivedError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "world_archived"
    safe_message = "The world is archived."


class TimelineArchivedError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "timeline_archived"
    safe_message = "The timeline is archived."


class CampaignArchivedError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "campaign_archived"
    safe_message = "The campaign is archived."


class WorldHasActiveCampaignsError(SafeMessageError):
    """No count, name, or identifier of the blocking campaigns is disclosed."""

    safe_status_code = 409
    safe_error_code = "world_has_active_campaigns"
    safe_message = "The world still has active campaigns."


class TimelineHasActiveCampaignsError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "timeline_has_active_campaigns"
    safe_message = "The timeline still has active campaigns."


class PrimaryTimelineNotArchivableError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "primary_timeline_not_archivable"
    safe_message = "A world's primary timeline cannot be archived."


class CampaignAccessManagerRequiredError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "campaign_access_manager_required"
    safe_message = "The campaign has no member who can manage its access."


class EntityReferencedError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "entity_referenced"
    safe_message = "The record is referenced elsewhere and cannot be deleted."


class SubtypeIncompleteError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "subtype_incomplete"
    safe_message = "The record is missing required type-specific data."


class RulesetNotAvailableError(SafeMessageError):
    """A ruleset in a world-creation request is unknown, not canon, or has no
    current version — all folded into one error."""

    safe_status_code = 400
    safe_error_code = "ruleset_not_available"
    safe_message = "A selected ruleset is not available."


class BranchPointInvalidError(SafeMessageError):
    """Nonexistent, other-world, and not-in-the-parent's-effective-history
    branch points are indistinguishable."""

    safe_status_code = 400
    safe_error_code = "branch_point_invalid"
    safe_message = "The branch point is not valid for this timeline."


class SupersessionTargetInvalidError(SafeMessageError):
    """Nonexistent, other-world, wrong-type, and wrong-status replacements
    are indistinguishable."""

    safe_status_code = 400
    safe_error_code = "supersession_target_invalid"
    safe_message = "The replacement is not valid for this record."


class WorldNotAuthorizedError(DomainAuthorizationError):
    """No world authority, or no such world — indistinguishable (fixed 404)."""


class CampaignNotAuthorizedError(DomainAuthorizationError):
    """No such campaign, or the caller no longer holds `access.manage` on it
    — indistinguishable (fixed 404). Reached by a command only when authority
    changed between the route's dependency and the command's locked re-check."""


class TimelineNotFoundError(DomainAuthorizationError):
    """No such timeline *in this world* — a nonexistent timeline and one that
    belongs to a different world are indistinguishable (fixed 404)."""


class WorldAlreadyClaimedError(ValueError):
    """`claim_unowned_world` refused: the world has (or ever had) a
    membership row. Raised only to trusted infrastructure (a script), never
    over HTTP."""


def _normalize(value: str | None, *, field: str, max_length: int, required: bool) -> str | None:
    if value is None:
        if required:
            raise AuthoringValidationError(f"{field} is required")
        return None
    stripped = value.strip()
    if not stripped:
        if required:
            raise AuthoringValidationError(f"{field} must not be blank")
        return None
    if len(stripped) > max_length:
        raise AuthoringValidationError(f"{field} exceeds {max_length} characters")
    return stripped


def normalize_name(value: str | None) -> str:
    """A required name: stripped, 1-200 characters."""
    result = _normalize(value, field="name", max_length=NAME_MAX_LENGTH, required=True)
    assert result is not None
    return result


def normalize_description(value: str | None) -> str | None:
    """An optional description: stripped; blank becomes NULL; at most 4000."""
    return _normalize(value, field="description", max_length=DESCRIPTION_MAX_LENGTH, required=False)


def normalize_reason(value: str | None, *, required: bool = False) -> str | None:
    """A bounded audit reason: stripped, at most 1000; blank becomes NULL
    unless `required`."""
    return _normalize(value, field="reason", max_length=REASON_MAX_LENGTH, required=required)


def normalize_label(value: str | None) -> str:
    """A required world-time label: stripped, 1-200 characters."""
    result = _normalize(value, field="label", max_length=LABEL_MAX_LENGTH, required=True)
    assert result is not None
    return result


_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """A `core.worlds.slug`-shaped (`^[a-z][a-z0-9-]*$`) base for `name`,
    truncated to 60 characters; `world` when nothing usable remains. Slugs
    are server-generated and never exposed for editing, so uniqueness
    collisions are resolved by the command with a random suffix rather than
    reported to the caller (a collision would otherwise disclose another
    user's world)."""
    base = _SLUG_NON_ALNUM.sub("-", name.lower()).strip("-")
    if not base:
        return "world"
    if not base[0].isalpha():
        base = f"world-{base}"
    return base[:SLUG_MAX_LENGTH].rstrip("-") or "world"
