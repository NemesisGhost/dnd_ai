import type { CampaignContext, SessionBootstrap } from "../types/bootstrap"
import type { WorldSummary } from "../types/worldAuthoring"

// World-access presentation helpers. Every answer is read from server-computed
// data — the bootstrap's `global_capabilities` and a world's own
// `capabilities` — and never from a display role, campaign membership, or the
// administrator flag. They decide what to *show*; the server re-checks every
// request and every mutation.

export const WORLD_CREATE = "world.create"
const WORLD_MANAGE = "world.manage"
const WORLD_VIEW = "world.view"

// True only when the server says this user may create worlds (an active
// platform administrator or an effective built-in GM, decided server-side).
export function canCreateWorlds(bootstrap: Pick<SessionBootstrap, "global_capabilities">): boolean {
    return bootstrap.global_capabilities?.includes(WORLD_CREATE) === true
}

// How a caller may use one world the server returned:
// - "edit": the caller manages it, so it opens on its authoring overview;
// - "view": the server granted view only, so it opens read-only;
// - "none": the record carries no world access, so nothing links to it.
export type WorldAccess = "edit" | "view" | "none"

export function worldAccess(world: Partial<Pick<WorldSummary, "capabilities">>): WorldAccess {
    // Deny by default: a record without a capability list grants nothing.
    const capabilities = world.capabilities ?? []
    if (capabilities.includes(WORLD_MANAGE)) return "edit"
    if (capabilities.includes(WORLD_VIEW)) return "view"
    return "none"
}

// The one destination a world-selection link may point at, or null when the
// caller has no world access. A view-only world opens the same overview route,
// which renders it read-only (WorldOverviewPage) with no authoring controls.
export function worldDestination(
    world: Pick<WorldSummary, "world_id"> & Partial<Pick<WorldSummary, "capabilities">>,
): string | null {
    return worldAccess(world) === "none" ? null : `/worlds/${encodeURIComponent(world.world_id)}`
}

// What the server says the caller may do on a world, from its own `capabilities` (ADR 0020).
export function worldCan(world: Partial<Pick<WorldSummary, "capabilities">>, capability: string): boolean {
    return (world.capabilities ?? []).includes(capability)
}

// One entry in any list of worlds the portal presents (All worlds, the
// hierarchy panel). Built only from server data: GET /worlds (explicit world
// authority) and the bootstrap's campaigns (campaign-scoped visibility).
export interface WorldChoice {
    world_id: string
    name: string
    // "world": explicit world authority (a world role), opening /worlds/{id}.
    // "campaign": visible only because the caller holds campaign.view in a
    // campaign on this world, opening that campaign's read-only World
    // Explorer. Campaign visibility never grants a world route or action.
    source: "world" | "campaign"
    // "edit" only for explicit world.manage; every campaign entry is "view".
    access: Exclude<WorldAccess, "none">
    to: string
    // The campaign a "campaign" entry opens through; null for "world".
    campaign_id: string | null
    campaign_name: string | null
    description: string | null
    lifecycle_status: string
    // Display only (ADR 0020): the caller's world roles and whether they hold a use grant.
    role_codes: string[]
    has_use_grant: boolean
}

type CampaignWorldSource = Pick<
    CampaignContext,
    "campaign_id" | "campaign_name" | "world_id" | "world_name"
>

export function campaignWorldPath(campaignId: string): string {
    return `/app/${encodeURIComponent(campaignId)}/world`
}

// Merges the two server sources into one deduplicated, deterministic list:
// - one entry per world_id;
// - explicit world authority wins over campaign visibility, so a world the
//   caller owns or views by role keeps its /worlds/{id} destination and its
//   own capabilities;
// - a world reachable only through campaigns opens through `currentCampaignId`
//   when that campaign is on the world, otherwise through the first such
//   campaign in bootstrap order (the server sorts by name, then ID);
// - entries sort by case-insensitive name, then world_id.
// A world the server returned with no world access and no campaign route is
// omitted: there is nowhere to send the user.
export function buildWorldChoices(
    worlds: readonly WorldSummary[],
    campaigns: readonly CampaignWorldSource[],
    currentCampaignId: string | null = null,
): WorldChoice[] {
    const byWorld = new Map<string, WorldChoice>()

    for (const world of worlds) {
        const access = worldAccess(world)
        if (access === "none") continue
        byWorld.set(world.world_id, {
            world_id: world.world_id,
            name: world.name,
            source: "world",
            access,
            to: `/worlds/${encodeURIComponent(world.world_id)}`,
            campaign_id: null,
            campaign_name: null,
            description: world.description,
            lifecycle_status: world.lifecycle_status,
            role_codes: world.role_codes ?? [],
            has_use_grant: world.has_use_grant === true,
        })
    }

    const current = campaigns.find((campaign) => campaign.campaign_id === currentCampaignId)
    const ordered = current === undefined ? campaigns : [current, ...campaigns]
    for (const campaign of ordered) {
        if (campaign.world_id === null || campaign.world_name === null) continue
        if (byWorld.has(campaign.world_id)) continue
        byWorld.set(campaign.world_id, {
            world_id: campaign.world_id,
            name: campaign.world_name,
            source: "campaign",
            access: "view",
            to: campaignWorldPath(campaign.campaign_id),
            campaign_id: campaign.campaign_id,
            campaign_name: campaign.campaign_name,
            description: null,
            // Bootstrap campaigns are active, and an active campaign keeps its
            // world from being archived.
            lifecycle_status: "active",
            role_codes: [],
            has_use_grant: false,
        })
    }

    return [...byWorld.values()].sort((a, b) => {
        const left = a.name.toLocaleLowerCase()
        const right = b.name.toLocaleLowerCase()
        if (left !== right) return left < right ? -1 : 1
        return a.world_id < b.world_id ? -1 : a.world_id > b.world_id ? 1 : 0
    })
}
