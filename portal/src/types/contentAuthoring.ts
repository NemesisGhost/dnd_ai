import type { EntityBlockedAction } from "./entityLifecycle"

// Shapes shared by every typed content-authoring read model (Phase 15.1).

export interface EntityReferenceSummary {
    entity_id: string
    name: string
    canon_status: string
    lifecycle_status: string
}

export interface ContentLimits {
    name_max_length: number
    summary_max_length: number
    change_note_max_length: number
}

export interface AuthoringReadModel {
    canon_status: string
    lifecycle_status: string
    row_version: number
    available_actions: string[]
    blocked_actions: EntityBlockedAction[]
    field_locks: string[]
    // Present on mutation responses only.
    changed?: boolean
}
