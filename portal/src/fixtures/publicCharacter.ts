// Exact A4 character-detail bodies for the public, summary and full tiers, as the server sends them.
// "Markers" are distinctive values placed in fields a tier must never render.

export const RELEASED = {
    summary: "A wary river guide.",
    appearance: "Tall, with a weathered cloak.",
    background: "Raised on the Mist Road.",
    species: { code: "elf", label: "Released Elf" },
    size: { code: "medium", label: "Released Medium" },
}

export const NULL_PROFILE = { summary: null, appearance: null, background: null, species: null, size: null }

export const PUBLIC_SECTIONS = {
    details: true,
    sheet: false,
    relationships: false,
    inventory: false,
    parties: false,
    public_profile: true,
}

// Keys the public DTO does not define. A body that carries them must not render any of them.
export const MARKER_FIELDS = {
    species_code: "LIVE-SPECIES-MARKER",
    size_category: "LIVE-SIZE-MARKER",
    current_hit_points: 777,
    maximum_hit_points: 888,
    conditions: [{ condition_code: "MARKER-CONDITION", source_description: null }],
    resources: [{ resource_code: "MARKER-RESOURCE", current_amount: 1, maximum_amount: 2 }],
    authoring: { can_edit: true },
    canon_status: "MARKER-CANON",
    lifecycle_status: "MARKER-LIFECYCLE",
    active_encounter_id: "MARKER-ENCOUNTER",
    current_location_id: "MARKER-LOCATION",
}

export function publicBody(overrides: Record<string, unknown> = {}) {
    return {
        view_tier: "public_profile",
        character_id: "pc-1",
        name: "Aldric",
        character_kind: "player_character",
        sections: PUBLIC_SECTIONS,
        public_profile: RELEASED,
        ...overrides,
    }
}

export function liveBody(tier: "summary" | "full", overrides: Record<string, unknown> = {}) {
    const full = tier === "full"
    return {
        view_tier: tier,
        character_id: "pc-1",
        name: "Aldric",
        character_kind: "player_character",
        species_code: "LIVE-SPECIES-MARKER",
        size_category: "LIVE-SIZE-MARKER",
        current_hit_points: full ? 9 : null,
        maximum_hit_points: full ? 12 : null,
        temporary_hit_points: full ? 0 : null,
        exhaustion_level: full ? 0 : null,
        death_save_successes: full ? 0 : null,
        death_save_failures: full ? 0 : null,
        current_location_id: null,
        active_encounter_id: null,
        conditions: full ? [{ condition_code: "MARKER-CONDITION", source_description: null }] : null,
        resources: full ? [] : null,
        sections: {
            details: true,
            sheet: full,
            relationships: true,
            inventory: false,
            parties: false,
            public_profile: true,
        },
        public_profile: RELEASED,
        ...overrides,
    }
}
