import type { CrumbState } from "../navigation/breadcrumbModel"
import { useCarriedListSearch } from "../navigation/taskReturn"
import { useTaskLinkState } from "../navigation/useTaskLinkState"

// Router state for a link from one World entry to another, so the next entry's
// "Back to World" still returns to the original category, search and page. Inside a task (the World
// browser with its filters, a character's inventory, the Review queue) it is the validated task with
// this page added to its trail; after a direct entry, or where the page is not a task page, it
// carries nothing.
export function useWorldReturnState(): CrumbState | undefined {
    return useTaskLinkState({ requireOrigin: true })
}

// "Back to World" target for an entry opened from the World browser: the
// browser's own query (carried as the task's list state) lands on the same
// category, search and page. Opened any other way, it is the plain World address.
export function useWorldBackPath(campaignId: string): string {
    const search = useCarriedListSearch("world", "campaign.world")
    return `/app/${encodeURIComponent(campaignId)}/world${search ?? ""}`
}

// "Back to Review queue" target for a record opened from the queue, with the filters it was left
// on; null for a record opened any other way.
export function useReviewBackPath(campaignId: string): string | null {
    const search = useCarriedListSearch("review", "review.queue")
    return search === undefined ? null : `/app/${encodeURIComponent(campaignId)}/review${search}`
}
