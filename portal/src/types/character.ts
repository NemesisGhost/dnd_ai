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
    // The released public profile may be read (public tier, or a summary/full reader with a release).
    // Optional: an answer from before the public tier carries no such flag, which reads as false.
    public_profile?: boolean
}

// A species or size as the released profile names it. The label is what a reader sees.
export interface CharacterIdentityValue {
    code: string
    label: string
}

// The released public profile, exactly the server's CharacterPublicProfileResponse. No release
// metadata is ever carried. A null field was not released and is omitted from the page.
export interface CharacterPublicProfile {
    summary: string | null
    appearance: string | null
    background: string | null
    species: CharacterIdentityValue | null
    size: CharacterIdentityValue | null
}

// The summary and full tiers (the existing character read). `view_tier` is absent only in a
// recognized answer from a server that predates the tiers (see api/character).
export interface CharacterDetail {
    view_tier?: "summary" | "full"
    // The latest release, or null (no release, or the section is withheld: the two are not told apart).
    public_profile?: CharacterPublicProfile | null
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

// The public tier: only these keys exist. The live definition, status, mechanics and authoring are
// not merely null but absent, and nothing here may be reconstructed from anywhere else.
export interface PublicCharacterDetail {
    view_tier: "public_profile"
    sections: CharacterSections
    character_id: string
    name: string
    character_kind: CharacterKind
    public_profile: CharacterPublicProfile
}

// What one character read answers: the public tier, or the summary/full shape.
export type CharacterRead = CharacterDetail | PublicCharacterDetail

export function isPublicTier(character: CharacterRead): character is PublicCharacterDetail {
    return character.view_tier === "public_profile"
}
