import type { EntityLifecycleView } from "../types/entityLifecycle"

// The label of a canon status, as the lifecycle controls show it.
export function canonStatusLabel(status: string): string {
    switch (status) {
        case "draft":
            return "a draft"
        case "proposed":
            return "in review"
        case "approved":
            return "approved but not yet published"
        case "rejected":
            return "rejected"
        case "superseded":
            return "superseded"
        default:
            return status
    }
}

// What the person can actually do next to get the record published, from the server's own
// `available_actions` (the state machine is draft → in review → approved → canon). Null when
// nothing is available to them, which is stated as such rather than pointing at an action that
// is not there.
export function lifecycleNextStep(view: EntityLifecycleView): string | null {
    const available = new Set(view.available_actions)
    if (view.lifecycle_status === "archived") {
        return available.has("restore") ? "restore it" : null
    }
    if (available.has("publish")) return "publish it"
    if (available.has("approve")) return "approve it, then publish it"
    if (available.has("submit_for_review")) return "submit it for review, then approve and publish it"
    if (available.has("return_to_draft")) return "return it to draft, then submit it for review"
    return null
}
