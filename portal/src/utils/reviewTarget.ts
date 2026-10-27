// Where a Review queue row leads: the record's own workspace, opened at the section where a
// reviewer decides. The section only chooses where the page opens; every target page re-reads the
// record and fails closed for anyone who may not see it. Nothing here calls the API or changes a
// status.

export interface ReviewRowIdentity {
    entity_id: string
    entity_type_code: string
    // The World category with a detail page, or null (a quest, a knowledge item).
    category: string | null
    canon_status: string
    lifecycle_status: string
}

export interface ReviewTarget {
    // The record's address, with `?section=` where the page has sections.
    path: string
    // "Review" when the record is waiting for a decision here; "Open" otherwise.
    action: "Review" | "Open"
    // Router state to carry, so the record can lead back to the queue as it was left.
    carriesReturn: boolean
}

const WORLD_WORKSPACE_CATEGORIES = new Set(["location", "organization", "religion", "character"])

const enc = encodeURIComponent

type Phase = "decide" | "publication" | "start"

// Where in its life the record stands, in terms of the page section that handles it.
function phaseOf(row: ReviewRowIdentity): Phase {
    if (row.lifecycle_status === "archived") return "publication"
    switch (row.canon_status) {
        case "proposed":
        case "approved":
            return "decide"
        case "rejected":
        case "superseded":
            return "publication"
        default:
            return "start"
    }
}

// `null` for a record with no page (a future eligible type): the queue then shows its name and its
// history only.
export function reviewTarget(campaignId: string, row: ReviewRowIdentity): ReviewTarget | null {
    const base = `/app/${enc(campaignId)}`
    const phase = phaseOf(row)
    const action = phase === "decide" ? "Review" : "Open"
    const id = enc(row.entity_id)

    if (row.entity_type_code === "quest") {
        // The quest workspace: Review where a decision is waiting, Publication for a quest that
        // was rejected, replaced or archived, Details for a draft.
        const section = phase === "decide" ? "review" : phase === "publication" ? "publication" : "details"
        return { path: `${base}/quests/${id}?section=${section}`, action, carriesReturn: true }
    }
    if (row.entity_type_code === "knowledge_item") {
        const section = phase === "decide" ? "review" : phase === "publication" ? "publication" : "claim"
        return { path: `${base}/knowledge/${id}?section=${section}`, action, carriesReturn: false }
    }
    if (row.category === "item") {
        // The item workspace has no review section; its Publication section holds the decision.
        const section = phase === "start" ? "details" : "publication"
        return { path: `${base}/items/${id}?section=${section}`, action, carriesReturn: false }
    }
    if (row.category !== null && WORLD_WORKSPACE_CATEGORIES.has(row.category)) {
        const section = phase === "decide" ? "review" : phase === "publication" ? "publication" : "details"
        return {
            path: `${base}/world/${enc(row.category)}/${id}?section=${section}`,
            action,
            carriesReturn: true,
        }
    }
    return null
}

// The record's own page without any section, for the history page's link back (a revision history
// carries a type code but no status).
export function recordPath(campaignId: string, entityId: string, entityTypeCode: string, category: string | null): string | null {
    const base = `/app/${enc(campaignId)}`
    const id = enc(entityId)
    if (entityTypeCode === "quest") return `${base}/quests/${id}`
    if (entityTypeCode === "knowledge_item") return `${base}/knowledge/${id}`
    if (category !== null && category !== "record") return `${base}/world/${enc(category)}/${id}`
    return null
}
