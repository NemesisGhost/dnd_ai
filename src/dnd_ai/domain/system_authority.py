"""System-scope authority (docs/adr/0020-scoped-system-world-and-campaign-roles.md).

A closed, server-side mapping from a system role to the platform capabilities it
carries. Like the world capabilities in `dnd_ai.domain.world_authority`, these
codes are deliberately **not** rows in `security.capabilities` (which is
assignable to campaign roles): they exist only here and derive only from an
unrevoked `security.user_system_roles` row on an active account, resolved from
the database on every request (`dnd_ai.queries.system_authority`).

There is no hierarchy. A user may hold any combination of the four roles and the
effective capabilities are the union of each held role's explicit set: Admin does
not imply GM, GM does not imply Player. System capabilities never confer campaign
membership, campaign capabilities, or authority over any world.
"""

from collections.abc import Iterable

SYSTEM_ROLE_ADMIN = "admin"
SYSTEM_ROLE_GM = "gm"
SYSTEM_ROLE_PLAYER = "player"
SYSTEM_ROLE_OBSERVER = "observer"

SYSTEM_ROLE_CODES: frozenset[str] = frozenset(
    {SYSTEM_ROLE_ADMIN, SYSTEM_ROLE_GM, SYSTEM_ROLE_PLAYER, SYSTEM_ROLE_OBSERVER}
)

ACCOUNTS_MANAGE = "accounts.manage"
SYSTEM_ROLES_MANAGE = "system_roles.manage"
SYSTEM_ROLES_GRANT_ADMIN = "system_roles.grant_admin"
WORLD_CREATE = "world.create"
CAMPAIGN_HOST = "campaign.host"
WORLD_ADMINISTER = "world.administer"

SYSTEM_ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    SYSTEM_ROLE_ADMIN: frozenset({ACCOUNTS_MANAGE, SYSTEM_ROLES_MANAGE, SYSTEM_ROLES_GRANT_ADMIN}),
    SYSTEM_ROLE_GM: frozenset({WORLD_CREATE, CAMPAIGN_HOST, WORLD_ADMINISTER}),
    SYSTEM_ROLE_PLAYER: frozenset(),
    SYSTEM_ROLE_OBSERVER: frozenset(),
}

# Every system capability code that exists (the closed vocabulary).
SYSTEM_CAPABILITIES: frozenset[str] = frozenset().union(*SYSTEM_ROLE_CAPABILITIES.values())


def capabilities_for_system_roles(
    role_codes: Iterable[str], *, allow_in_app_admin_grant: bool = False
) -> frozenset[str]:
    """The union of the capabilities carried by `role_codes`; unknown codes carry
    none (deny by default). `system_roles.grant_admin` is effective only while the
    deployment setting `DND_AI_ALLOW_IN_APP_ADMIN_GRANT` is on (the Admin role is
    otherwise granted only by the operator script)."""
    granted: set[str] = set()
    for role_code in role_codes:
        granted |= SYSTEM_ROLE_CAPABILITIES.get(role_code, frozenset())
    if not allow_in_app_admin_grant:
        granted.discard(SYSTEM_ROLES_GRANT_ADMIN)
    return frozenset(granted)
