// The reader projection of a character's relationships (GET .../characters/{id}/relationships).
// It carries no description, treaty terms, notes, perspectives, visibility flags, lifecycle or
// version: those never leave the server for this view.

export interface ReaderRelationshipParticipant {
    entity_id: string
    name: string
    entity_type_code: string
    // The World category the participant browses under; a link is built from it only when can_open.
    category: string | null
    role: string
    role_label: string
    is_self: boolean
    can_open: boolean
}

export interface ReaderRelationshipDetails {
    family_unit_name?: string | null
    job_title?: string | null
    ownership_share?: number | null
    office?: string | null
    rank?: string | null
    in_force?: boolean | null
    distance_text?: string | null
    travel_time_text?: string | null
    travel_mode?: string | null
}

export interface CharacterRelationship {
    relationship_id: string
    kind: string
    kind_label: string
    relationship_type: string
    relationship_type_label: string
    symmetric: boolean
    participants: ReaderRelationshipParticipant[]
    started: string | null
    ended_at: string | null
    period_status: string
    current_status_label: string | null
    details: ReaderRelationshipDetails
}

export interface CharacterRelationships {
    character_id: string
    as_of: string | null
    truncated: boolean
    items: CharacterRelationship[]
}
