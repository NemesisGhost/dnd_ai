"""World-level authoring authority (docs/adr/0014-world-authoring-authority.md).

A closed, server-side mapping from a world role to the world capabilities it
carries. These codes are deliberately **not** rows in `security.capabilities`
(that vocabulary is assignable to campaign roles, where a `world.manage`
grant would be meaningless): they exist only here, derive only from an
active `security.world_memberships` row resolved fresh from the database on
every request, and are never cached, never derived from campaign roles or
platform administration, and never inferred by a client.

`WorldAuthority` is the resolved snapshot a route or command receives. It is
the analogue of `dnd_ai.domain.access.AccessContext` for the world aggregate.

World *creation* is the one global, not per-world, capability (`world.create`,
below). It is the deliberate exception to "never derived from campaign roles or
platform administration": docs/adr/0018-world-creation-eligibility.md makes it
exactly "active platform administrator, or effective built-in `gm`". Creating a
world grants the creator `world_owner` on that world and nothing broader;
being an administrator or a GM confers no authority over any existing world.
"""

import uuid
from dataclasses import dataclass

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
WORLD_MANAGE = "world.manage"
TIMELINE_MANAGE = "timeline.manage"
CAMPAIGN_CREATE = "campaign.create"

# Global (not world-scoped) capability. Held only by an active platform
# administrator or an active user with an effective assignment of the built-in
# `gm` system-template role (ADR 0018, which amends ADR 0014 D3). It is
# computed per user from the database by
# `dnd_ai.queries.world_authority.may_create_worlds` — never granted statically
# — and `create_world` enforces that same policy in its own transaction.
# Foundry device principals and machine principals never hold it:
# `dnd_ai.api.auth.require_human_user_id` refuses them before the policy runs.
WORLD_CREATE = "world.create"

# The `security.roles.code` of the built-in (campaign_id IS NULL) system
# template whose effective holders may create worlds. A campaign-scoped custom
# role with the same code is a different role and never qualifies.
WORLD_CREATOR_SYSTEM_ROLE_CODE = "gm"

WORLD_OWNER_ROLE = "world_owner"
# Explicit read-only access to a world outside any campaign: `world.view` and
# nothing else. Never derived from a campaign role — a campaign's
# `campaign.view` already reaches that campaign's world through the campaign's
# own World Explorer routes and confers no world role.
WORLD_VIEWER_ROLE = "world_viewer"

WORLD_ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    WORLD_OWNER_ROLE: frozenset({WORLD_VIEW, WORLD_MANAGE, TIMELINE_MANAGE, CAMPAIGN_CREATE}),
    WORLD_VIEWER_ROLE: frozenset({WORLD_VIEW}),
}

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


@dataclass(frozen=True)
class WorldAuthority:
    """One user's resolved authority over one world.

    `world_lifecycle_status` is the world's lifecycle code (`active` or
    `archived`) at resolution time. It is informational for presentation;
    commands re-check it under lock, because archival can change between this
    resolution and the write.
    """

    world_id: uuid.UUID
    user_id: uuid.UUID
    role_codes: frozenset[str]
    world_lifecycle_status: str

    @property
    def capabilities(self) -> frozenset[str]:
        granted: set[str] = set()
        for role_code in self.role_codes:
            granted |= WORLD_ROLE_CAPABILITIES.get(role_code, frozenset())
        return frozenset(granted)

    def has_capability(self, capability_code: str) -> bool:
        return capability_code in self.capabilities


def capabilities_for_roles(role_codes: frozenset[str]) -> frozenset[str]:
    """The world capabilities a set of role codes carries; unknown role codes
    carry none (deny by default)."""
    granted: set[str] = set()
    for role_code in role_codes:
        granted |= WORLD_ROLE_CAPABILITIES.get(role_code, frozenset())
    return frozenset(granted)
