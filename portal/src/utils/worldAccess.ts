import type { SessionBootstrap } from "../types/bootstrap"
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
