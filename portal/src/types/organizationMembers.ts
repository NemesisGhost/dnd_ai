// Organization roster and status (Phase 15 checkpoint 15.3A-2b).

import type { RecordAuthoring } from "../utils/recordAuthoring"

export interface MemberRow {
    relationship_id: string
    member_entity_id: string
    member_name: string
    member_type_code: string
    role: string | null
    rank: string | null
    is_public: boolean
    started: string
    ended: string | null
    current: boolean
    lifecycle_status: string
    row_version: number
    // Where the caller's timeline clock sits against the stint: "in_effect", "ended",
    // "not_started", "undated" or "clock_unset". Optional for an older server.
    period_status?: string
    // The member's World category ("character", "organization", ...), and whether the server
    // says the caller can open the member's own page.
    category?: string | null
    can_open?: boolean
}

export interface OrganizationMembers {
    organization_id: string
    status: string | null
    // Member and office changes (shared world canon): campaign editor and world Editor.
    can_edit: boolean
    // The operational status is campaign state; absent from an older server (then `can_edit`).
    can_set_status?: boolean
    authoring?: RecordAuthoring
    // The caller's effective timeline clock as display text; null when it is unset.
    as_of?: string | null
    status_choices: { value: string; label: string }[]
    members: MemberRow[]
}

export interface StatusReceipt {
    organization_state_id: string
    event_id: string
    previous_status_code: string | null
    new_status_code: string
}
