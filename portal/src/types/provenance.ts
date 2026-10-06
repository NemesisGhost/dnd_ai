// Source and provenance contracts (Phase 15 checkpoint 15.3C-1).

export interface SourceItem {
    source_id: string
    source_type: string
    source_type_label: string
    title: string
    // GM-only locator text; shown only to people who can edit canon.
    reference: string | null
    created_by_name: string | null
    attached_count: number
}

export interface SourceList {
    items: SourceItem[]
    source_types: { value: string; label: string }[]
    limits: { title_max_length: number; reference_max_length: number }
}

export interface SourceLink {
    source_id: string
    source_type_label: string
    title: string
    reference: string | null
    attached_at: string
    attached_by_name: string | null
    detached_at: string | null
    detached_by_name: string | null
    is_attached: boolean
}

export interface ProvenanceTransition {
    label: string
    previous_status: string | null
    new_status: string | null
    actor_name: string | null
    recorded_at: string
}

export interface Provenance {
    entity_id: string
    name: string
    entity_type_code: string
    canon_status: string
    lifecycle_status: string
    created_at: string
    created_by_name: string | null
    origin: SourceItem | null
    links: SourceLink[]
    transitions: ProvenanceTransition[]
    superseded_by: { entity_id: string; name: string } | null
    supersedes: { entity_id: string; name: string }[]
}
