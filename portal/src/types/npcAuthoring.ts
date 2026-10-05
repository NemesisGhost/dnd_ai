import type { AuthoringReadModel, ContentLimits, EntityReferenceSummary } from "./contentAuthoring"

// NPC identity authoring contracts (Phase 15.1).

export interface NpcSpeciesOption {
    species_id: string
    name: string
    ruleset_name: string
}

export interface NpcOptions {
    can_create: boolean
    species: NpcSpeciesOption[]
    sizes: { code: string; label: string }[]
    limits: ContentLimits & { text_max_length: number }
}

export interface NpcAuthoringView extends AuthoringReadModel {
    npc_id: string
    name: string
    summary: string | null
    species: { species_id: string; name: string }
    size: { code: string; label: string | null }
    origin: EntityReferenceSummary | null
    background: string | null
    appearance: string | null
    // GM-only; the audience-safe character reads never carry it.
    notes: string | null
}

export interface NpcFieldsBody {
    name: string
    summary: string | null
    species_id: string
    size_category: string
    origin_location_id: string | null
    background: string | null
    appearance: string | null
    notes: string | null
}

export type CreateNpcBody = NpcFieldsBody

export interface UpdateNpcBody extends NpcFieldsBody {
    expected_row_version: number
    change_note?: string | null
}
