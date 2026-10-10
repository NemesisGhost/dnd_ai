// Review queue and revision history contracts (Phase 15 checkpoint 15.3C-2).

export interface ReviewRow {
    entity_id: string
    name: string
    entity_type_code: string
    // The World category with a detail page, or null (a quest, for example).
    category: string | null
    canon_status: string
    lifecycle_status: string
    row_version: number
    updated_at: string
    last_change_by: string | null
    last_change_by_me: boolean
}

export interface ReviewQueue {
    items: ReviewRow[]
    next_cursor: string | null
    status: string
    statuses: { value: string; label: string }[]
    types: string[]
    counts: Record<string, number>
}

export interface RevisionRow {
    row_version: number
    kind: string
    created_at: string
    created_by_name: string | null
    canon_status: string | null
    lifecycle_status: string | null
}

export interface RevisionHistory {
    entity_id: string
    name: string
    entity_type_code: string
    canon_status: string
    lifecycle_status: string
    row_version: number
    revisions: RevisionRow[]
}

export interface RevisionChange {
    path: string
    kind: "added" | "removed" | "changed"
    before: unknown
    after: unknown
    truncated: boolean
}

export interface RevisionComparison {
    entity_id: string
    name: string
    from_version: number
    to_version: number
    from_authored_version: number | null
    to_authored_version: number | null
    changes: RevisionChange[]
}
