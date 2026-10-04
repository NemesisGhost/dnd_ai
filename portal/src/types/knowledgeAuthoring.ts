import type { AuthoringReadModel, EntityReferenceSummary } from "./contentAuthoring"

// Knowledge-item definition authoring contracts (Phase 15.1). A knowledge item
// is a claim; who knows it is per-knower state and never part of these shapes.

export interface KnowledgeChoice {
    value: string
    label: string
}

export interface KnowledgeOptions {
    can_create: boolean
    knowledge_types: KnowledgeChoice[]
    truth_statuses: KnowledgeChoice[]
    sensitivities: KnowledgeChoice[]
    limits: { statement_max_length: number; change_note_max_length: number }
}

export interface KnowledgeSubjectOption {
    entity_id: string
    name: string
    kind: string
    canon_status: string
}

export interface KnowledgeSubjectOptionPage {
    items: KnowledgeSubjectOption[]
    next_cursor: string | null
}

export interface KnowledgeAuthoringView extends AuthoringReadModel {
    knowledge_item_id: string
    statement: string
    knowledge_type: string
    truth_status: string
    sensitivity: string
    subject: EntityReferenceSummary | null
    // True once anyone knows the claim; statement, type and subject are then frozen.
    in_use: boolean
}

export interface KnowledgeFieldsBody {
    statement: string
    knowledge_type: string
    truth_status: string
    sensitivity: string
    subject_entity_id: string | null
}

export type CreateKnowledgeBody = KnowledgeFieldsBody

export interface UpdateKnowledgeBody extends KnowledgeFieldsBody {
    expected_row_version: number
    change_note?: string | null
}
