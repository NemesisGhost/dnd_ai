// NPC portrayal and runtime-option contracts (Phase 15 checkpoint 15.3A-3).

export interface PortrayalVersion {
    version_number: number
    created_at: string
    change_note: string | null
}

export interface NpcPortrayalView {
    npc_id: string
    name: string
    detail_level: string
    detail_levels: { value: string; label: string }[]
    row_version: number
    canon_status: string
    lifecycle_status: string
    current_version: number
    shown_version: number
    fields: Record<string, string | null>
    field_labels: { name: string; label: string }[]
    limits: { field_max_length: number; note_max_length: number }
    versions: PortrayalVersion[]
    can_edit: boolean
    changed?: boolean
}

export interface RuntimeChoice {
    value: string
    label: string
    code: string
}

export interface RuntimeOptions {
    conditions: RuntimeChoice[]
    resources: RuntimeChoice[]
}
