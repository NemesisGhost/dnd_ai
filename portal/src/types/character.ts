export interface CharacterCondition {
    condition_code: string
    source_description: string | null
}

export interface CharacterResource {
    resource_code: string
    current_amount: number
    maximum_amount: number
}

export interface CharacterDetail {
    character_id: string
    name: string
    species_code: string
    size_category: string

    current_hit_points: number | null
    maximum_hit_points: number | null
    temporary_hit_points: number | null
    exhaustion_level: number | null
    death_save_successes: number | null
    death_save_failures: number | null
    current_location_id: string | null
    active_encounter_id: string | null

    conditions: CharacterCondition[] | null
    resources: CharacterResource[] | null
}