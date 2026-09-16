export type KnowledgeView =
    | "known"
    | "rumors"
    | "party_shared"
    | "character_private"
    | "recent"
    | "public"

export type KnowledgeScope =
    | "canonical"
    | "party"
    | "character"
    | "public"

export interface KnowledgeListItem {
    knowledge_item_id: string
    knowledge_type_code: string
    statement: string
    truth_status_code: string | null
    sensitivity: string | null
    awareness_level: string | null
    confidence: number | null
    willing_to_share: boolean | null
    scope: KnowledgeScope
    discovery_world_time_id: string | null
    source_event_id: string | null
    source_interaction_id: string | null
    subject_entity_id: string | null
}

export interface KnowledgePage {
    items: KnowledgeListItem[]
    next_cursor: string | null
}

export interface KnowledgeSearchParameters {
    view: KnowledgeView
    characterId: string | null
    partyId: string | null
    query: string
    knowledgeType: string | null
    cursor?: string | null
    limit?: number
}

// Matches the backend's KnowledgeResponse (GET .../knowledge/{id}) —
// deliberately narrower than KnowledgeListItem: no scope, discovery, or
// source/subject ids, since the detail endpoint does not return them.
export interface KnowledgeDetail {
    knowledge_item_id: string
    knowledge_type_code: string
    statement: string
    truth_status_code: string | null
    sensitivity: string | null
    awareness_level: string | null
    confidence: number | null
    willing_to_share: boolean | null
}