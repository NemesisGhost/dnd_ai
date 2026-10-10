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

export type KnowledgeSubjectCategory =
    | "location"
    | "character"
    | "organization"
    | "religion"
    | "item"
    | "event"
    | "quest"

/** What a claim is about. The server returns it only when the caller may
 * open the subject itself; `null`/absent means "nothing to show", whether
 * the claim has no subject or one this caller may not see. */
export interface KnowledgeSubject {
    entity_id: string
    name: string
    category: KnowledgeSubjectCategory
    entity_type_code: string
}

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
    subject?: KnowledgeSubject | null
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
    /** Public knowledge is included in every view by default; only an
     * explicit `false` asks the server to leave it out. */
    includePublic?: boolean
}

// Matches the backend's KnowledgeResponse (GET .../knowledge/{id}) —
// deliberately narrower than KnowledgeListItem: no scope, discovery, or
// source ids, since the detail endpoint does not return them. The subject
// summary is the one related resource it does return (authorized).
export type CharacterKnowledgePath = "character" | "party" | "public"

/** How the selected character knows a claim, as the server resolved it: the character's own
 * record, an eligible party's record, or public lore (which has no personal record, so its
 * confidence and willingness to share are always null). */
export interface CharacterKnowledge {
    path: CharacterKnowledgePath
    awareness_level: string | null
    confidence: number | null
    willing_to_share: boolean | null
}

export interface KnowledgeDetail {
    knowledge_item_id: string
    knowledge_type_code: string
    statement: string
    truth_status_code: string | null
    sensitivity: string | null
    awareness_level: string | null
    confidence: number | null
    willing_to_share: boolean | null
    subject?: KnowledgeSubject | null
    /** Which path produced `statement` (the list's `scope`). */
    scope?: KnowledgeScope
    /** How the selected character knows the claim; `null` when no knowledge path covers it.
     * Absent only in a payload that predates the field. */
    character_knowledge?: CharacterKnowledge | null
}