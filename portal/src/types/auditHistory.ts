// Mirrors dnd_ai.api.audit_history.AuditHistoryItemResponse /
// AuditHistoryListResponse (docs/AUDIT_HISTORY_API.md). Every field here is
// already a server-generated, safe-presentation projection — never raw
// audit.change_log JSON, never an unreviewed metadata field. See that
// module's docstring for the exact allowlist.

export type AuditHistoryCategory =
    | "membership"
    | "role"
    | "character_relationship"
    | "resource_grant"
    | "invitation"
    | "campaign"

export const AUDIT_HISTORY_CATEGORIES: AuditHistoryCategory[] = [
    "membership",
    "role",
    "character_relationship",
    "resource_grant",
    "invitation",
    "campaign",
]

export type AuditActorType = "user" | "service" | "unknown"

export type AuditTargetType = "account" | "character" | "access_group"

export interface AuditHistoryItem {
    // Identity only — for a React list key. Never rendered as page text.
    change_log_id: number
    occurred_at: string
    category: AuditHistoryCategory
    action_label: string
    actor_label: string
    actor_type: AuditActorType
    target_label: string | null
    target_type: AuditTargetType | null
    change_summary: string | null
    outcome: string | null
}

export interface AuditHistoryPage {
    items: AuditHistoryItem[]
    next_cursor: string | null
}

export interface AuditHistoryFilters {
    category: AuditHistoryCategory | null
    actorUserId: string | null
    occurredFrom: string | null
    occurredTo: string | null
}

export const EMPTY_AUDIT_HISTORY_FILTERS: AuditHistoryFilters = {
    category: null,
    actorUserId: null,
    occurredFrom: null,
    occurredTo: null,
}
