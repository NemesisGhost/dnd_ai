"""State-precondition policy for world, timeline, and campaign authoring.

Pure functions that answer "why is this action not legal from this state", used
by **both** the commands (which raise the matching domain error) and the read
models (which report `available_actions` / `blocked_actions` to the portal), so
a preview can never drift from enforcement (docs/PLAN.md Phase 14, D14).
Reason codes are the same stable codes the API returns for the corresponding
409, so a blocked-action explanation and a rejected-command error agree.

This module decides *state* legality only. Authority, scope binding,
`expected_row_version`, and locking are the command's job.
"""

from collections.abc import Callable
from dataclasses import dataclass

from .authoring import (
    CampaignAccessManagerRequiredError,
    CampaignArchivedError,
    LifecycleTransitionNotAllowedError,
    PrimaryTimelineNotArchivableError,
    TimelineArchivedError,
    TimelineHasActiveCampaignsError,
    WorldArchivedError,
    WorldHasActiveCampaignsError,
)
from .errors import SafeMessageError

# Reason codes (identical to the API error codes).
WORLD_ARCHIVED = "world_archived"
TIMELINE_ARCHIVED = "timeline_archived"
TRANSITION_NOT_ALLOWED = "lifecycle_transition_not_allowed"
WORLD_HAS_ACTIVE_CAMPAIGNS = "world_has_active_campaigns"
TIMELINE_HAS_ACTIVE_CAMPAIGNS = "timeline_has_active_campaigns"
PRIMARY_TIMELINE_NOT_ARCHIVABLE = "primary_timeline_not_archivable"
ACCESS_MANAGER_REQUIRED = "campaign_access_manager_required"

_ERRORS: dict[str, type[SafeMessageError]] = {
    WORLD_ARCHIVED: WorldArchivedError,
    TIMELINE_ARCHIVED: TimelineArchivedError,
    TRANSITION_NOT_ALLOWED: LifecycleTransitionNotAllowedError,
    WORLD_HAS_ACTIVE_CAMPAIGNS: WorldHasActiveCampaignsError,
    TIMELINE_HAS_ACTIVE_CAMPAIGNS: TimelineHasActiveCampaignsError,
    PRIMARY_TIMELINE_NOT_ARCHIVABLE: PrimaryTimelineNotArchivableError,
    ACCESS_MANAGER_REQUIRED: CampaignAccessManagerRequiredError,
}


def raise_for_reason(reason: str, detail: str = "") -> None:
    """Raise the domain error a blocked-action reason code stands for."""
    raise _ERRORS[reason](detail or reason)


@dataclass(frozen=True)
class BlockedAction:
    action: str
    reason: str


def _evaluate(
    actions: tuple[str, ...], reason_for: Callable[[str], str | None]
) -> tuple[list[str], list[BlockedAction]]:
    available: list[str] = []
    blocked: list[BlockedAction] = []
    for action in actions:
        reason = reason_for(action)
        if reason is None:
            available.append(action)
        else:
            blocked.append(BlockedAction(action=action, reason=reason))
    return available, blocked


# --- World ---------------------------------------------------------------------

WORLD_UPDATE = "update"
WORLD_ARCHIVE = "archive"
WORLD_RESTORE = "restore"
WORLD_CREATE_TIMELINE = "create_timeline"
WORLD_CREATE_CAMPAIGN = "create_campaign"
WORLD_ACTIONS = (
    WORLD_UPDATE,
    WORLD_ARCHIVE,
    WORLD_RESTORE,
    WORLD_CREATE_TIMELINE,
    WORLD_CREATE_CAMPAIGN,
)


def world_blocked_reason(
    action: str, *, lifecycle_status: str, has_blocking_campaigns: bool
) -> str | None:
    active = lifecycle_status == "active"
    if action in (WORLD_UPDATE, WORLD_CREATE_TIMELINE, WORLD_CREATE_CAMPAIGN):
        return None if active else WORLD_ARCHIVED
    if action == WORLD_ARCHIVE:
        if not active:
            return TRANSITION_NOT_ALLOWED
        return WORLD_HAS_ACTIVE_CAMPAIGNS if has_blocking_campaigns else None
    if action == WORLD_RESTORE:
        return None if lifecycle_status == "archived" else TRANSITION_NOT_ALLOWED
    raise ValueError(f"unknown world action {action!r}")


def world_actions(
    *, lifecycle_status: str, has_blocking_campaigns: bool
) -> tuple[list[str], list[BlockedAction]]:
    return _evaluate(
        WORLD_ACTIONS,
        lambda a: world_blocked_reason(
            a, lifecycle_status=lifecycle_status, has_blocking_campaigns=has_blocking_campaigns
        ),
    )


# --- Timeline -------------------------------------------------------------------

TIMELINE_UPDATE = "update"
TIMELINE_ARCHIVE = "archive"
TIMELINE_RESTORE = "restore"
TIMELINE_CREATE_BRANCH = "create_branch"
TIMELINE_CREATE_CAMPAIGN = "create_campaign"
TIMELINE_ACTIONS = (
    TIMELINE_UPDATE,
    TIMELINE_ARCHIVE,
    TIMELINE_RESTORE,
    TIMELINE_CREATE_BRANCH,
    TIMELINE_CREATE_CAMPAIGN,
)


def timeline_blocked_reason(
    action: str,
    *,
    world_status: str,
    timeline_status: str,
    is_primary: bool,
    has_blocking_campaigns: bool,
) -> str | None:
    """Why `action` is not legal on this timeline, or `None`. The world being
    archived dominates every action: an archived world is read-only except
    for restoring the world itself."""
    if action not in TIMELINE_ACTIONS:
        raise ValueError(f"unknown timeline action {action!r}")
    if world_status != "active":
        return WORLD_ARCHIVED
    if action == TIMELINE_RESTORE:
        return None if timeline_status == "archived" else TRANSITION_NOT_ALLOWED
    if action == TIMELINE_ARCHIVE:
        if timeline_status != "active":
            return TRANSITION_NOT_ALLOWED
        if is_primary:
            return PRIMARY_TIMELINE_NOT_ARCHIVABLE
        return TIMELINE_HAS_ACTIVE_CAMPAIGNS if has_blocking_campaigns else None
    return None if timeline_status == "active" else TIMELINE_ARCHIVED


def timeline_actions(
    *,
    world_status: str,
    timeline_status: str,
    is_primary: bool,
    has_blocking_campaigns: bool,
) -> tuple[list[str], list[BlockedAction]]:
    return _evaluate(
        TIMELINE_ACTIONS,
        lambda a: timeline_blocked_reason(
            a,
            world_status=world_status,
            timeline_status=timeline_status,
            is_primary=is_primary,
            has_blocking_campaigns=has_blocking_campaigns,
        ),
    )


# --- Campaign -------------------------------------------------------------------

CAMPAIGN_UPDATE = "update"
CAMPAIGN_ARCHIVE = "archive"
CAMPAIGN_REACTIVATE = "reactivate"
CAMPAIGN_ACTIONS = (CAMPAIGN_UPDATE, CAMPAIGN_ARCHIVE, CAMPAIGN_REACTIVATE)

CAMPAIGN_ARCHIVED = "campaign_archived"
_ERRORS[CAMPAIGN_ARCHIVED] = CampaignArchivedError


def campaign_blocked_reason(
    action: str,
    *,
    campaign_status: str,
    world_status: str,
    timeline_status: str,
    has_access_manager: bool,
) -> str | None:
    """Why `action` is not legal on this campaign, or `None`.

    Update and archive need an active campaign. Reactivation needs an archived
    campaign whose world and timeline are active and which still has a
    non-expiring `access.manage` holder (the database enforces that last rule
    at commit; pre-checking it here yields a classified 409 instead of an
    unclassified integrity failure)."""
    if action not in CAMPAIGN_ACTIONS:
        raise ValueError(f"unknown campaign action {action!r}")
    if action == CAMPAIGN_REACTIVATE:
        if campaign_status != "archived":
            return TRANSITION_NOT_ALLOWED
        if world_status != "active":
            return WORLD_ARCHIVED
        if timeline_status != "active":
            return TIMELINE_ARCHIVED
        return None if has_access_manager else ACCESS_MANAGER_REQUIRED
    if campaign_status == "archived":
        return CAMPAIGN_ARCHIVED if action == CAMPAIGN_UPDATE else TRANSITION_NOT_ALLOWED
    return None if campaign_status == "active" else TRANSITION_NOT_ALLOWED


def campaign_actions(
    *,
    campaign_status: str,
    world_status: str,
    timeline_status: str,
    has_access_manager: bool,
) -> tuple[list[str], list[BlockedAction]]:
    return _evaluate(
        CAMPAIGN_ACTIONS,
        lambda a: campaign_blocked_reason(
            a,
            campaign_status=campaign_status,
            world_status=world_status,
            timeline_status=timeline_status,
            has_access_manager=has_access_manager,
        ),
    )
