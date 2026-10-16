// Knowledge audience and runtime commands (Phase 15 checkpoint 15.2E-3).

export interface PartyAudience {
    party_knowledge_id: string
    party_id: string
    party_name: string
    awareness_level: string
}

export interface KnowerAudience {
    entity_knowledge_id: string
    knower_entity_id: string
    knower_name: string
    knower_type: string
    awareness_level: string
    confidence: number | null
    interpretation: string | null
    willing_to_share: boolean
    // The event that last wrote this belief; the token a belief change names.
    last_event_id: string | null
}

export interface PublicAudience {
    public_knowledge_id: string
    location_id: string
    location_name: string
    awareness_level: string
}

export interface KnowledgeAudience {
    knowledge_item_id: string
    awareness_levels: string[]
    transfer_methods: string[]
    parties: PartyAudience[]
    knowers: KnowerAudience[]
    public: PublicAudience[]
}

export interface KnowledgeRuntimeReceipt {
    knowledge_item_id: string
    record_id: string
    changed: boolean
    event_id?: string
    knower_entity_id?: string
}

export interface BeliefChanges {
    awareness_level?: string
    confidence?: number | null
    interpretation?: string | null
    willing_to_share?: boolean
}

export type KnowledgeCommand =
    | { op: "reveal"; party_id: string; awareness_level: string }
    | {
          op: "learn"
          knower_entity_id: string
          awareness_level: string
          confidence: number | null
          interpretation: string | null
      }
    | {
          op: "transfer"
          source_entity_id: string
          recipient_entity_id: string
          transfer_method: string
          awareness_level: string
          modified_interpretation: string | null
      }
    | { op: "public"; location_id: string; awareness_level: string }
    | {
          op: "belief"
          entity_knowledge_id: string
          expected_last_event_id: string | null
          changes: BeliefChanges
      }
