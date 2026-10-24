import type { SessionBootstrap } from "../types/bootstrap"

// System-scope presentation helpers. Every answer is read from the server's
// `global_capabilities` (docs/adr/0020-scoped-system-world-and-campaign-roles.md)
// and never from a role label: they decide what to *show*, while the server
// re-checks every request. A system role never implies campaign or world access.

export const ACCOUNTS_MANAGE = "accounts.manage"
export const SYSTEM_ROLES_MANAGE = "system_roles.manage"
export const SYSTEM_ROLES_GRANT_ADMIN = "system_roles.grant_admin"
export const CAMPAIGN_HOST = "campaign.host"

type CapabilityHolder = Pick<SessionBootstrap, "global_capabilities">

function holds(bootstrap: CapabilityHolder, capability: string): boolean {
    return bootstrap.global_capabilities?.includes(capability) === true
}

export function canManageAccounts(bootstrap: CapabilityHolder): boolean {
    return holds(bootstrap, ACCOUNTS_MANAGE)
}

export function canManageSystemRoles(bootstrap: CapabilityHolder): boolean {
    return holds(bootstrap, SYSTEM_ROLES_MANAGE)
}

// Only while the deployment enables the in-app Administrator grant.
export function canGrantAdmin(bootstrap: CapabilityHolder): boolean {
    return holds(bootstrap, SYSTEM_ROLES_GRANT_ADMIN)
}

export function canHostCampaigns(bootstrap: CapabilityHolder): boolean {
    return holds(bootstrap, CAMPAIGN_HOST)
}

export type SystemRoleCode = "admin" | "gm" | "player" | "observer"

export const SYSTEM_ROLE_OPTIONS: readonly { code: SystemRoleCode; label: string }[] = [
    { code: "admin", label: "Administrator" },
    { code: "gm", label: "Game master" },
    { code: "player", label: "Player" },
    { code: "observer", label: "Observer" },
]
