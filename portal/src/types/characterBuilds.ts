// Character build authoring contracts (Phase 15 checkpoint 15.2B-2).

export interface RuleOption {
    id: string
    name: string
    code: string
}

export interface ClassOption extends RuleOption {
    hit_die: number | null
}

export interface SubclassOption extends RuleOption {
    class_id: string
}

export interface ProficiencyTypeOption extends RuleOption {
    target_kind: "skill" | "saving_throw" | "free_text"
}

export interface FeatureOption extends RuleOption {
    class_id: string | null
    subclass_id: string | null
    granted_at_level: number | null
}

export interface SpellOption extends RuleOption {
    level: number
}

export interface BuildOptions {
    limits: {
        label_max_length: number
        ability_score_min: number
        ability_score_max: number
        class_level_min: number
        class_level_max: number
        target_label_max_length: number
        max_hit_points: number
    }
    // Rules content the server cannot hold in a build (none today).
    unsupported: string[]
    abilities: RuleOption[]
    classes: ClassOption[]
    subclasses: SubclassOption[]
    skills: RuleOption[]
    proficiency_types: ProficiencyTypeOption[]
    spells: SpellOption[]
    features: FeatureOption[]
}

export interface BuildSummary {
    character_build_id: string
    label: string | null
    ruleset_version_id: string
    created_at: string
    is_active: boolean
    counts: {
        abilities: number
        classes: number
        proficiencies: number
        features: number
        spellcasting: number
    }
}

export interface CharacterBuilds {
    character: { character_id: string; name: string; kind: "npc" | "player_character" }
    state: {
        initialized: boolean
        current_hit_points: number | null
        maximum_hit_points: number | null
    }
    active_build_id: string | null
    builds: BuildSummary[]
}

export interface CreateBuildBody {
    label: string | null
    ability_scores: { ability_id: string; score: number }[]
    class_levels: { class_id: string; subclass_id: string | null; level: number }[]
    proficiencies: {
        proficiency_type_id: string
        skill_id?: string | null
        saving_throw_ability_id?: string | null
        target_label?: string | null
        is_expertise: boolean
    }[]
    feature_ids: string[]
    spellcasting: {
        class_id: string | null
        spellcasting_ability_id: string
        known_spell_ids: string[]
        prepared_spell_ids: string[]
    }[]
}

export interface BuildReceipt {
    character_id: string
    character_build_id?: string
    event_id?: string
    created: boolean
    changed: boolean
}
