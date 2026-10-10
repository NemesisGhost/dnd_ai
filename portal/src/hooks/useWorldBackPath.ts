import { useLocation } from "react-router"

export interface WorldReturnState {
    worldSearch?: string
}

// "Back to World" target for an entry opened from the World browser: the
// browser's own query string rides along as router state, so returning lands
// on the same category, search and page. Opened any other way (a bookmark, a
// link elsewhere), it is the plain World address.
export function useWorldBackPath(campaignId: string): string {
    const { state } = useLocation() as { state: WorldReturnState | null }
    const worldSearch = state?.worldSearch
    const suffix = typeof worldSearch === "string" && worldSearch.startsWith("?") ? worldSearch : ""
    return `/app/${encodeURIComponent(campaignId)}/world${suffix}`
}
