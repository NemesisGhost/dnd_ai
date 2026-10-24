import { useLocation } from "react-router"

export interface WorldReturnState {
    worldSearch?: string
    // The Review queue's query string, when a record was opened from the queue.
    reviewSearch?: string
}

// A query string carried in router state, or undefined. Only a string that starts with "?" is
// honoured, so a crafted state cannot send the person anywhere else.
function readQuery(state: unknown, key: keyof WorldReturnState): string | undefined {
    const value = (state as WorldReturnState | null | undefined)?.[key]
    return typeof value === "string" && value.startsWith("?") ? value : undefined
}

// The World browser's query string an entry was opened from, or undefined for
// an entry opened any other way (a bookmark, a link elsewhere).
function readWorldSearch(state: WorldReturnState | null): string | undefined {
    return readQuery(state, "worldSearch")
}

// The valid return keys of a location state, for forwarding through in-page links.
export function pickWorldReturnState(state: unknown): WorldReturnState | undefined {
    const worldSearch = readQuery(state, "worldSearch")
    const reviewSearch = readQuery(state, "reviewSearch")
    if (worldSearch === undefined && reviewSearch === undefined) return undefined
    return {
        ...(worldSearch === undefined ? {} : { worldSearch }),
        ...(reviewSearch === undefined ? {} : { reviewSearch }),
    }
}

// Router state for a link from one World entry to another, so the next entry's
// "Back to World" still returns to the original category, search and page.
export function useWorldReturnState(): WorldReturnState | undefined {
    const { state } = useLocation() as { state: WorldReturnState | null }
    const worldSearch = readWorldSearch(state)
    return worldSearch === undefined ? undefined : { worldSearch }
}

// "Back to World" target for an entry opened from the World browser: the
// browser's own query string rides along as router state, so returning lands
// on the same category, search and page. Opened any other way, it is the plain
// World address.
export function useWorldBackPath(campaignId: string): string {
    const { state } = useLocation() as { state: WorldReturnState | null }
    return `/app/${encodeURIComponent(campaignId)}/world${readWorldSearch(state) ?? ""}`
}

// "Back to Review queue" target for a record opened from the queue, with the filters it was left
// on; null for a record opened any other way.
export function useReviewBackPath(campaignId: string): string | null {
    const { state } = useLocation()
    const search = readQuery(state, "reviewSearch")
    return search === undefined ? null : `/app/${encodeURIComponent(campaignId)}/review${search}`
}
