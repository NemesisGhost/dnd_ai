// World relationship authoring contracts (Phase 15 checkpoint 15.3A-2a).

export interface RelationshipKindOption {
    code: string
    label: string
    types: string[]
    roles: string[]
    fixed_roles: string[] | null
}

export interface RelationshipOptions {
    can_create: boolean
    kinds: RelationshipKindOption[]
    limits: {
        text_max_length: number
        short_text_max_length: number
        stance_min: number
        stance_max: number
        min_participants: number
        max_participants: number
    }
}

export interface RelationshipParticipant {
    entity_id: string
    name: string
    entity_type_code: string
    canon_status: string
    lifecycle_status: string
    role: string
    role_label: string
}

export interface RelationshipSummary {
    relationship_id: string
    kind: string
    relationship_type: string
    relationship_type_label: string
    description: string | null
    lifecycle_status: string
    ended: boolean
    is_public: boolean | null
    row_version: number
    participants: RelationshipParticipant[]
}

export interface RelationshipList {
    items: RelationshipSummary[]
}

export interface PerspectiveView {
    holder_entity_id: string
    holder_name: string
    affinity: number | null
    trust: number | null
    respect: number | null
    fear: number | null
    obligation: number | null
    emotional_tone: string | null
    private_interpretation: string | null
}

export interface RelationshipView {
    relationship_id: string
    kind: string
    kind_label: string
    relationship_type: string
    relationship_type_label: string
    description: string | null
    started_world_time_id: string | null
    started: string | null
    ended_world_time_id: string | null
    ended: string | null
    lifecycle_status: string
    row_version: number
    typed: Record<string, unknown>
    participants: RelationshipParticipant[]
    perspectives: PerspectiveView[]
    current_status: string | null
    available_actions: string[]
    changed?: boolean
}

export interface TypedFields {
    family_unit_name?: string | null
    job_title?: string | null
    ownership_share?: number | null
    is_public?: boolean
    is_active?: boolean
    treaty_terms?: string | null
    role?: string | null
    rank?: string | null
}

export interface CreateRelationshipBody extends TypedFields {
    kind: string
    relationship_type: string
    participants: { entity_id: string; role: string }[]
    description: string | null
    started_world_time_id: string | null
}

export interface PerspectiveBody {
    holder_entity_id: string
    affinity: number | null
    trust: number | null
    respect: number | null
    fear: number | null
    obligation: number | null
    emotional_tone: string | null
    private_interpretation: string | null
}

export type RelationshipCommand =
    | {
          op: "update"
          body: TypedFields & {
              expected_row_version: number
              description: string | null
              started_world_time_id: string | null
          }
      }
    | { op: "end"; body: { expected_row_version: number; ended_world_time_id: string } }
    | { op: "archive"; body: { expected_row_version: number } }
    | { op: "restore"; body: { expected_row_version: number } }
    | { op: "perspective"; body: PerspectiveBody & { expected_row_version: number } }
