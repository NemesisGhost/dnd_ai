// Encounter preparation contracts (Phase 15 checkpoint 15.3B-2a).

export interface EncounterParticipant {
    encounter_participant_id: string
    participant_entity_id: string
    name: string
    entity_type_code: string
    side: string
    initiative: number | null
    outcome: string | null
    current_hit_points: number | null
    maximum_hit_points: number | null
}

export interface EncounterTurn {
    turn_order: number
    actor_name: string
    target_name: string | null
    action_kind: string | null
    hit: boolean | null
    damage_amount: number | null
}

export interface EncounterRound {
    round_number: number
    turns: EncounterTurn[]
}

export interface PreparedEncounter {
    encounter_id: string
    session_id: string | null
    status: string
    // True only while the encounter is pending: nothing can be prepared after it starts.
    can_prepare: boolean
    summary: string | null
    location_id: string | null
    location_name: string | null
    world_time_id: string
    current_round: number
    resulting_event_id: string | null
    participants: EncounterParticipant[]
    rounds: EncounterRound[]
    changed?: boolean
    event_id?: string | null
}

export interface EncounterSummary {
    encounter_id: string
    status: string
    summary: string | null
    location_name: string | null
    participant_count: number
}

export interface EncounterOptions {
    sides: { value: string; label: string }[]
    action_kinds: { value: string; label: string }[]
    outcomes: { value: string; label: string }[]
    limits: {
        summary_max_length: number
        initiative_min: number
        initiative_max: number
        max_participants: number
    }
}

export interface PrepareEncounterBody {
    session_id: string
    location_id: string | null
    summary: string | null
}
