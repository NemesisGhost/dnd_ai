import type { RecordAuthoring } from "../utils/recordAuthoring"

export type CharacterKind = "npc" | "player_character" | "character"

export interface CharacterCondition {
    condition_code: string
    source_description: string | null
}

export interface CharacterResource {
    resource_code: string
    current_amount: number
    maximum_amount: number
}

// Which of a character's reader sections the server says the caller may open (the same checks the
// section endpoints apply). They decide which links are offered; each endpoint still authorizes
// its own request.
export interface CharacterSections {
    details: boolean
    sheet: boolean
    relationships: boolean
    inventory: boolean
    parties: boolean
}

export interface CharacterDetail {
    // Absent only in an answer from a server that predates it (see utils/characterSections).
    sections?: CharacterSections
    authoring?: RecordAuthoring
    character_id: string
    name: string
    // "character" is a bare character row that is neither an NPC nor a player character.
    character_kind: CharacterKind
    // Where the record stands (the server's own status fields, as on every World detail). They let
    // a runtime panel explain why events are not taken yet without a read of the world's private
    // lifecycle view. Optional so an older answer without them is treated as unknown, never blocking.
    canon_status?: string
    lifecycle_status?: string
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