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

WORLD_ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    WORLD_OWNER_ROLE: frozenset({WORLD_VIEW, WORLD_MANAGE, TIMELINE_MANAGE, CAMPAIGN_CREATE}),
}

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
