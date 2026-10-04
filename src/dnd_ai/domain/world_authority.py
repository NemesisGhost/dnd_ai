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
"""

import uuid
from dataclasses import dataclass

WORLD_VIEW = "world.view"
WORLD_MANAGE = "world.manage"
TIMELINE_MANAGE = "timeline.manage"
CAMPAIGN_CREATE = "campaign.create"

# Global (not world-scoped) capability: any active human principal may create
# a world (ADR 0014, D3). Foundry device principals and machine principals
# never hold it — `dnd_ai.api.auth.require_human_user_id` is the gate.
WORLD_CREATE = "world.create"

WORLD_OWNER_ROLE = "world_owner"

WORLD_ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    WORLD_OWNER_ROLE: frozenset({WORLD_VIEW, WORLD_MANAGE, TIMELINE_MANAGE, CAMPAIGN_CREATE}),
}

HUMAN_GLOBAL_CAPABILITIES: frozenset[str] = frozenset({WORLD_CREATE})


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
