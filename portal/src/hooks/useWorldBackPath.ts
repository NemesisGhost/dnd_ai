import { useLocation } from "react-router"

export interface WorldReturnState {
    worldSearch?: string
}

// The World browser's query string an entry was opened from, or undefined for
// an entry opened any other way (a bookmark, a link elsewhere).
function readWorldSearch(state: WorldReturnState | null): string | undefined {
    const worldSearch = state?.worldSearch
    return typeof worldSearch === "string" && worldSearch.startsWith("?") ? worldSearch : undefined
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
