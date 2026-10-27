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


// Typed authoring writes answer with a receipt (ids, version, flags) and never
// echo content; the portal refetches the authoritative view after a write.
export interface WriteReceipt {
    row_version: number
    created: boolean
    changed: boolean
    // A child record (quest stage or objective) the command wrote.
    record_id?: string
}
export interface LocationReceipt extends WriteReceipt {
    location_id: string
}
export interface OrganizationReceipt extends WriteReceipt {
    organization_id: string
}
export interface ReligionReceipt extends WriteReceipt {
    religion_id: string
}
export interface PlayerCharacterReceipt extends WriteReceipt {
    player_character_id: string
}

export interface NpcReceipt extends WriteReceipt {
    npc_id: string
}
export interface KnowledgeReceipt extends WriteReceipt {
    knowledge_item_id: string
}
export interface QuestReceipt extends WriteReceipt {
    quest_id: string
}
