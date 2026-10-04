export interface EntityBlockedAction {
    action: string
    reason: string
}

export interface EntityLifecycleView {
    entity_id: string
    entity_type_code: string
    canonical_name: string
    canon_status: string
    lifecycle_status: string
    row_version: number
    lifecycle_managed: boolean
    superseded_by: { entity_id: string; canonical_name: string } | null
    available_actions: string[]
    blocked_actions: EntityBlockedAction[]
}

export interface ReplacementCandidate {
    entity_id: string
    canonical_name: string
    canon_status: string
    row_version: number
}

export interface ReplacementCandidatePage {
    items: ReplacementCandidate[]
    next_cursor: string | null
}

export interface EntityTransitionResponse {
    entity_id: string
    canon_status?: string
    lifecycle_status?: string
    row_version?: number
    deleted?: boolean
}

export interface EntityTransitionBody {
    expected_row_version: number
    reason?: string | null
}

export interface SupersedeBody {
    expected_row_version: number
    replacement_entity_id: string
    replacement_expected_row_version: number
}
