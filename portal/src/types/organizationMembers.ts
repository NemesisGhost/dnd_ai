// Organization roster and status (Phase 15 checkpoint 15.3A-2b).

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
}

export interface OrganizationMembers {
    organization_id: string
    status: string | null
    can_edit: boolean
    status_choices: { value: string; label: string }[]
    members: MemberRow[]
}

export interface StatusReceipt {
    organization_state_id: string
    event_id: string
    previous_status_code: string | null
    new_status_code: string
}
