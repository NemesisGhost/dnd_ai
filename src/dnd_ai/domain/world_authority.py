"""World-level authority (docs/adr/0014-world-authoring-authority.md, amended by
docs/adr/0020-scoped-system-world-and-campaign-roles.md).

A closed, server-side mapping from a world role to the world capabilities it
carries. These codes are deliberately **not** rows in `security.capabilities`
(that vocabulary is assignable to campaign roles, where a `world.manage` grant
would be meaningless): they exist only here, derive only from an open
`security.world_memberships` row or an open `security.world_use_grants` row
resolved fresh from the database on every request, and are never cached, never
derived from campaign roles, and never inferred by a client.

A user may hold several world roles on one world; capabilities are the union of
each role's explicit set (Owner lists the editing and reviewing capabilities
explicitly rather than inheriting them). A world-use grant confers `world.view`
and `campaign.create` and nothing else.

The four *world-management* capabilities (`world.manage`, `world.share`,
`world.transfer`, `campaign.create`) are effective only while the holder also has
the system capability `world.administer` (the system `gm` role; decision D11).
That gate is applied when the authority is resolved, so it is continuous: revoking
system GM removes them on the next request while the world-role rows stay in place,
and restoring it brings them back with no data change. Editing, reviewing, reading
and timeline work never need it.

`WorldAuthority` is the resolved snapshot a route or command receives. It is the
analogue of `dnd_ai.domain.access.AccessContext` for the world aggregate.

World *creation* is the one global, not per-world, capability. It belongs to the
system scope (`dnd_ai.domain.system_authority.WORLD_CREATE`, held by the system
`gm` role); campaign roles and platform administration never confer it. Creating
a world grants the creator `world_owner` on that world and nothing broader.
"""

import uuid
from dataclasses import dataclass

# The one definition of the global creation capability lives in the system scope;
# re-exported here so existing imports keep working.
from dnd_ai.domain.system_authority import WORLD_CREATE

from .authoring_policy import (
    TIMELINE_ARCHIVE,
    TIMELINE_CREATE_BRANCH,
    TIMELINE_CREATE_CAMPAIGN,
    TIMELINE_RESTORE,
    TIMELINE_UPDATE,
    WORLD_ARCHIVE,
    WORLD_CREATE_CALENDAR,
    WORLD_CREATE_CAMPAIGN,
    WORLD_CREATE_TIMELINE,
    WORLD_RESTORE,
    WORLD_UPDATE,
    BlockedAction,
)

WORLD_VIEW = "world.view"
WORLD_CANON_READ = "world.canon.read"
WORLD_CANON_READ_PRIVATE = "world.canon.read_private"
WORLD_CANON_EDIT = "world.canon.edit"
WORLD_CANON_REVIEW = "world.canon.review"
WORLD_MANAGE = "world.manage"
TIMELINE_MANAGE = "timeline.manage"
WORLD_SHARE = "world.share"
WORLD_TRANSFER = "world.transfer"
CAMPAIGN_CREATE = "campaign.create"

WORLD_OWNER_ROLE = "world_owner"
WORLD_EDITOR_ROLE = "world_editor"
WORLD_REVIEWER_ROLE = "world_reviewer"
WORLD_READER_ROLE = "world_reader"
# Explicit read-only access to a world outside any campaign: `world.view` and nothing else
# (docs/adr/0019-world-visibility-and-viewer-role.md). Never derived from a campaign role.
# Distinct from `world_reader`, which also reads the world's published canon (ADR 0020).
WORLD_VIEWER_ROLE = "world_viewer"

WORLD_ROLE_CODES: frozenset[str] = frozenset(
    {
        WORLD_OWNER_ROLE,
        WORLD_VIEWER_ROLE,
        WORLD_EDITOR_ROLE,
        WORLD_REVIEWER_ROLE,
        WORLD_READER_ROLE,
    }
)

WORLD_ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    WORLD_OWNER_ROLE: frozenset(
        {
            WORLD_VIEW,
            WORLD_CANON_READ,
            WORLD_CANON_READ_PRIVATE,
            WORLD_CANON_EDIT,
            WORLD_CANON_REVIEW,
            WORLD_MANAGE,
            TIMELINE_MANAGE,
            WORLD_SHARE,
            WORLD_TRANSFER,
            CAMPAIGN_CREATE,
        }
    ),
    WORLD_EDITOR_ROLE: frozenset(
        {WORLD_VIEW, WORLD_CANON_READ, WORLD_CANON_READ_PRIVATE, WORLD_CANON_EDIT, TIMELINE_MANAGE}
    ),
    WORLD_REVIEWER_ROLE: frozenset(
        {WORLD_VIEW, WORLD_CANON_READ, WORLD_CANON_READ_PRIVATE, WORLD_CANON_REVIEW}
    ),
    WORLD_READER_ROLE: frozenset({WORLD_VIEW, WORLD_CANON_READ}),
    WORLD_VIEWER_ROLE: frozenset({WORLD_VIEW}),
}

# What an open world-use grant confers, separate from any world role.
USE_GRANT_CAPABILITIES: frozenset[str] = frozenset({WORLD_VIEW, CAMPAIGN_CREATE})

# Effective only while the holder has the system `world.administer` capability.
WORLD_MANAGEMENT_CAPABILITIES: frozenset[str] = frozenset(
    {WORLD_MANAGE, WORLD_SHARE, WORLD_TRANSFER, CAMPAIGN_CREATE}
)

# The world capability each action a world/timeline read model can report
# requires — the same capability the action's route and command enforce. The
# read models drop an action the caller lacks the capability for from *both*
# `available_actions` and `blocked_actions`: a viewer is not "blocked" from
# editing, the action simply is not theirs.
WORLD_ACTION_CAPABILITIES: dict[str, str] = {
    WORLD_UPDATE: WORLD_MANAGE,
    WORLD_ARCHIVE: WORLD_MANAGE,
    WORLD_RESTORE: WORLD_MANAGE,
    WORLD_CREATE_CALENDAR: WORLD_MANAGE,
    WORLD_CREATE_TIMELINE: TIMELINE_MANAGE,
    WORLD_CREATE_CAMPAIGN: CAMPAIGN_CREATE,
}
TIMELINE_ACTION_CAPABILITIES: dict[str, str] = {
    TIMELINE_UPDATE: TIMELINE_MANAGE,
    TIMELINE_ARCHIVE: TIMELINE_MANAGE,
    TIMELINE_RESTORE: TIMELINE_MANAGE,
    TIMELINE_CREATE_BRANCH: TIMELINE_MANAGE,
    TIMELINE_CREATE_CAMPAIGN: CAMPAIGN_CREATE,
}


def authorized_actions(
    available: list[str],
    blocked: list[BlockedAction],
    *,
    capabilities: frozenset[str],
    required: dict[str, str],
) -> tuple[list[str], list[BlockedAction]]:
    """Keep only the actions whose required capability the caller holds. An
    action missing from `required` is dropped (deny by default)."""

    def allowed(action: str) -> bool:
        needed = required.get(action)
        return needed is not None and needed in capabilities

    return (
        [action for action in available if allowed(action)],
        [item for item in blocked if allowed(item.action)],
    )


# Every global capability code that exists. Membership is per user and
# database-resolved; this set only names the closed vocabulary.
GLOBAL_CAPABILITIES: frozenset[str] = frozenset({WORLD_CREATE})


def capabilities_for_roles(
    role_codes: frozenset[str], *, has_use_grant: bool = False, may_administer: bool
) -> frozenset[str]:
    """The world capabilities a set of role codes (plus an optional use grant)
    carries; unknown role codes carry none (deny by default). `may_administer` is
    whether the holder has the system `world.administer` capability: without it the
    world-management capabilities are withheld (decision D11). It has no default so
    that every caller states it."""
    granted: set[str] = set()
    for role_code in role_codes:
        granted |= WORLD_ROLE_CAPABILITIES.get(role_code, frozenset())
    if has_use_grant:
        granted |= USE_GRANT_CAPABILITIES
    if not may_administer:
        granted -= WORLD_MANAGEMENT_CAPABILITIES
    return frozenset(granted)


@dataclass(frozen=True)
class WorldAuthority:
    """One user's resolved authority over one world.

    `world_lifecycle_status` is the world's lifecycle code (`active` or
    `archived`) at resolution time. It is informational for presentation;
    commands re-check it under lock, because archival can change between this
    resolution and the write. `may_administer` records whether the holder had the
    system `world.administer` capability at resolution time.
    """

    world_id: uuid.UUID
    user_id: uuid.UUID
    role_codes: frozenset[str]
    world_lifecycle_status: str
    may_administer: bool
    has_use_grant: bool = False

    @property
    def capabilities(self) -> frozenset[str]:
        return capabilities_for_roles(
            self.role_codes, has_use_grant=self.has_use_grant, may_administer=self.may_administer
        )

    def has_capability(self, capability_code: str) -> bool:
        return capability_code in self.capabilities
