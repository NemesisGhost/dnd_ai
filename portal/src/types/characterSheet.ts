export interface CharacterSheetClassLevel {
    class_id: string
    class_code: string
    class_display_name: string
    level: number
    hit_die: number
    subclass_id: string | null
    subclass_code: string | null
    subclass_display_name: string | null
}

export interface CharacterSheetAbilityScore {
    ability_id: string
    ability_code: string
    ability_display_name: string
    score: number
    modifier: number | null
}

export interface CharacterSheetSkill {
    skill_id: string
    code: string
    display_name: string
    governing_ability_code: string
    governing_ability_modifier: number | null
    is_proficient: boolean
    is_expertise: boolean
    bonus: number | null
    passive_score: number | null
}

export interface CharacterSheetSavingThrow {
    ability_id: string
    ability_code: string
    ability_display_name: string
    ability_modifier: number | null
    is_proficient: boolean
    bonus: number | null
}

export interface CharacterSheetProficiency {
    proficiency_type_code: string
    proficiency_type_display_name: string
    target_label: string
    is_expertise: boolean
}

export interface CharacterSheetFeature {
    feature_id: string
    code: string
    display_name: string
    description: string | null
    granted_at_level: number | null
    source_category: string
}

export interface CharacterSheetSpell {
    spell_id: string
    code: string
    display_name: string
    level: number
    school: string | null
    casting_time: string | null
    range: string | null
    duration: string | null
    description: string | null
    damage_type_code: string | null
    damage_type_display_name: string | null
    is_known: boolean
    is_prepared: boolean
}

export interface CharacterSheetSpellcastingProfile {
    character_spellcasting_profile_id: string
    class_id: string | null
    class_code: string | null
    class_display_name: string | null
    spellcasting_ability_id: string
    spellcasting_ability_code: string
    spellcasting_ability_display_name: string
    spellcasting_ability_modifier: number | null
    spell_attack_bonus: number | null
    spell_save_dc: number | null
    spells: CharacterSheetSpell[]
}

export interface CharacterSheetLanguage {
    language_id: string
    code: string
    display_name: string
}

export interface CharacterSheetSense {
    sense_type: string
    range_feet: number
}

export interface CharacterSheetMovement {
    movement_type: string
    speed_feet: number
}

export interface CharacterSheet {
    character_id: string
    name: string
    species_code: string
    species_display_name: string
    size_category: string

    character_build_id: string | null
    build_label: string | null
    ruleset_code: string | null
    ruleset_display_name: string | null
    ruleset_version_id: string | null
    ruleset_version_label: string | null

    total_level: number
    proficiency_bonus: number | null

    class_levels: CharacterSheetClassLevel[]
    ability_scores: CharacterSheetAbilityScore[]
    skills: CharacterSheetSkill[]
    saving_throws: CharacterSheetSavingThrow[]
    other_proficiencies: CharacterSheetProficiency[]
    features: CharacterSheetFeature[]
    spellcasting_profiles: CharacterSheetSpellcastingProfile[]
    languages: CharacterSheetLanguage[]
    senses: CharacterSheetSense[]
    movements: CharacterSheetMovement[]
}