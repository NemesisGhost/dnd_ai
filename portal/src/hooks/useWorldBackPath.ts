import { useLocation } from "react-router"
import type { CrumbState } from "../navigation/breadcrumbModel"
import { useTaskLinkState } from "../navigation/useTaskLinkState"
import { pickQueryStates, readQueryState } from "./returnState"

export interface WorldReturnState {
    worldSearch?: string
    // The Review queue's query string, when a record was opened from the queue.
    reviewSearch?: string
}

// The World browser's query string an entry was opened from, or undefined for
// an entry opened any other way (a bookmark, a link elsewhere).
function readWorldSearch(state: WorldReturnState | null): string | undefined {
    return readQueryState(state, "worldSearch")
}

// The valid return keys of a location state, for forwarding through in-page links.
export function pickWorldReturnState(state: unknown): WorldReturnState | undefined {
    return pickQueryStates(state, ["worldSearch", "reviewSearch"] as const)
}

// Router state for a link from one World entry to another, so the next entry's
// "Back to World" still returns to the original category, search and page. Inside a task (the World
// browser with its filters, a character's inventory, the Review queue) it is the validated task with
// this page added to its trail and the older keys beside it; after a direct entry, or where the page
// is not a task page, it is what it always was.
export function useWorldReturnState(): CrumbState | WorldReturnState | undefined {
    const task = useTaskLinkState({ requireOrigin: true })
    const { state } = useLocation() as { state: WorldReturnState | null }
    if (task !== undefined) return task
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
    const search = readQueryState(state, "reviewSearch")
    return search === undefined ? null : `/app/${encodeURIComponent(campaignId)}/review${search}`
}
