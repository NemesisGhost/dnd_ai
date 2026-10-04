import type { EntityBlockedAction } from "./entityLifecycle"

// Typed Location authoring contracts (Phase 15.1). They mirror the server's
// authoring read model; no timeline state is part of them.

export interface LocationFieldDescriptor {
    name: "population" | "building_use"
    kind: "integer" | "text"
    label: string
    max_length: number | null
    minimum: number | null
    maximum: number | null
}

export interface LocationCategoryOption {
    code: string
    label: string
    fields: LocationFieldDescriptor[]
}

export interface LocationOptions {
    can_create: boolean
    categories: LocationCategoryOption[]
    limits: {
        name_max_length: number
        summary_max_length: number
        change_note_max_length: number
    }
}

export interface LocationParentSummary {
    location_id: string
    name: string
    canon_status: string
    lifecycle_status: string
}

export interface LocationAuthoringView {
    location_id: string
    name: string
    summary: string | null
    category: { code: string; label: string }
    parent: LocationParentSummary | null
    population: number | null
    building_use: string | null
    canon_status: string
    lifecycle_status: string
    row_version: number
    available_actions: string[]
    blocked_actions: EntityBlockedAction[]
    field_locks: string[]
    // Present on mutation responses only.
    changed?: boolean
}

export interface LocationParentOption {
    location_id: string
    name: string
    category: { code: string; label: string }
    canon_status: string
}

export interface LocationParentOptionPage {
    items: LocationParentOption[]
    next_cursor: string | null
}

export interface LocationFieldsBody {
    name: string
    summary: string | null
    parent_location_id: string | null
    population: number | null
    building_use: string | null
}

export interface CreateLocationBody extends LocationFieldsBody {
    category: string
}

export interface UpdateLocationBody extends LocationFieldsBody {
    expected_row_version: number
    change_note?: string | null
}
