import type { CharacterSheet } from "../types/characterSheet"

export const characterSheetFixture = {
    character_id: "character-ixamarra",
    name: "Ixamarra",
    species_code: "dragonborn",
    species_display_name: "Dragonborn",
    size_category: "medium",

    character_build_id: "build-ixamarra-primary",
    build_label: "Primary Build",
    ruleset_code: "dnd5e",
    ruleset_display_name: "Dungeons & Dragons Fifth Edition",
    ruleset_version_id: "ruleset-version-dnd5e",
    ruleset_version_label: "2014 Core Rules",

    total_level: 6,
    proficiency_bonus: 3,

    class_levels: [
        {
            class_id: "class-bard",
            class_code: "bard",
            class_display_name: "Bard",
            level: 6,
            hit_die: 8,
            subclass_id: "subclass-college-of-lore",
            subclass_code: "college_of_lore",
            subclass_display_name: "College of Lore",
        },
    ],

    ability_scores: [
        {
            ability_id: "ability-strength",
            ability_code: "strength",
            ability_display_name: "Strength",
            score: 10,
            modifier: 0,
        },
        {
            ability_id: "ability-dexterity",
            ability_code: "dexterity",
            ability_display_name: "Dexterity",
            score: 14,
            modifier: 2,
        },
        {
            ability_id: "ability-constitution",
            ability_code: "constitution",
            ability_display_name: "Constitution",
            score: 13,
            modifier: 1,
        },
        {
            ability_id: "ability-intelligence",
            ability_code: "intelligence",
            ability_display_name: "Intelligence",
            score: 12,
            modifier: 1,
        },
        {
            ability_id: "ability-wisdom",
            ability_code: "wisdom",
            ability_display_name: "Wisdom",
            score: 11,
            modifier: 0,
        },
        {
            ability_id: "ability-charisma",
            ability_code: "charisma",
            ability_display_name: "Charisma",
            score: 18,
            modifier: 4,
        },
    ],

    skills: [
        {
            skill_id: "skill-arcana",
            code: "arcana",
            display_name: "Arcana",
            governing_ability_code: "intelligence",
            governing_ability_modifier: 1,
            is_proficient: true,
            is_expertise: false,
            bonus: 4,
            passive_score: 14,
        },
        {
            skill_id: "skill-history",
            code: "history",
            display_name: "History",
            governing_ability_code: "intelligence",
            governing_ability_modifier: 1,
            is_proficient: true,
            is_expertise: true,
            bonus: 7,
            passive_score: 17,
        },
        {
            skill_id: "skill-persuasion",
            code: "persuasion",
            display_name: "Persuasion",
            governing_ability_code: "charisma",
            governing_ability_modifier: 4,
            is_proficient: true,
            is_expertise: true,
            bonus: 10,
            passive_score: 20,
        },
    ],

    saving_throws: [
        {
            ability_id: "ability-strength",
            ability_code: "strength",
            ability_display_name: "Strength",
            ability_modifier: 0,
            is_proficient: false,
            bonus: 0,
        },
        {
            ability_id: "ability-dexterity",
            ability_code: "dexterity",
            ability_display_name: "Dexterity",
            ability_modifier: 2,
            is_proficient: true,
            bonus: 5,
        },
        {
            ability_id: "ability-constitution",
            ability_code: "constitution",
            ability_display_name: "Constitution",
            ability_modifier: 1,
            is_proficient: false,
            bonus: 1,
        },
        {
            ability_id: "ability-intelligence",
            ability_code: "intelligence",
            ability_display_name: "Intelligence",
            ability_modifier: 1,
            is_proficient: false,
            bonus: 1,
        },
        {
            ability_id: "ability-wisdom",
            ability_code: "wisdom",
            ability_display_name: "Wisdom",
            ability_modifier: 0,
            is_proficient: false,
            bonus: 0,
        },
        {
            ability_id: "ability-charisma",
            ability_code: "charisma",
            ability_display_name: "Charisma",
            ability_modifier: 4,
            is_proficient: true,
            bonus: 7,
        },
    ],

    other_proficiencies: [
        {
            proficiency_type_code: "armor",
            proficiency_type_display_name: "Armor",
            target_label: "Light armor",
            is_expertise: false,
        },
        {
            proficiency_type_code: "tool",
            proficiency_type_display_name: "Tool",
            target_label: "Lute",
            is_expertise: false,
        },
    ],

    features: [
        {
            feature_id: "feature-bardic-inspiration",
            code: "bardic_inspiration",
            display_name: "Bardic Inspiration",
            description:
                "Inspire another creature with a bonus action.",
            granted_at_level: 1,
            source_category: "class",
        },
        {
            feature_id: "feature-cutting-words",
            code: "cutting_words",
            display_name: "Cutting Words",
            description:
                "Use Bardic Inspiration to distract another creature.",
            granted_at_level: 3,
            source_category: "subclass",
        },
    ],

    spellcasting_profiles: [
        {
            character_spellcasting_profile_id:
                "spellcasting-profile-bard",
            class_id: "class-bard",
            class_code: "bard",
            class_display_name: "Bard",
            spellcasting_ability_id: "ability-charisma",
            spellcasting_ability_code: "charisma",
            spellcasting_ability_display_name: "Charisma",
            spellcasting_ability_modifier: 4,
            spell_attack_bonus: 7,
            spell_save_dc: 15,
            spells: [
                {
                    spell_id: "spell-vicious-mockery",
                    code: "vicious_mockery",
                    display_name: "Vicious Mockery",
                    level: 0,
                    school: "enchantment",
                    casting_time: "1 action",
                    range: "60 feet",
                    duration: "Instantaneous",
                    description:
                        "Unleash an insult laced with subtle enchantment.",
                    damage_type_code: "psychic",
                    damage_type_display_name: "Psychic",
                    is_known: true,
                    is_prepared: true,
                },
                {
                    spell_id: "spell-detect-magic",
                    code: "detect_magic",
                    display_name: "Detect Magic",
                    level: 1,
                    school: "divination",
                    casting_time: "1 action",
                    range: "Self",
                    duration: "Concentration, up to 10 minutes",
                    description:
                        "Sense the presence of magic within range.",
                    damage_type_code: null,
                    damage_type_display_name: null,
                    is_known: true,
                    is_prepared: false,
                },
            ],
        },
    ],

    languages: [
        {
            language_id: "language-common",
            code: "common",
            display_name: "Common",
        },
        {
            language_id: "language-draconic",
            code: "draconic",
            display_name: "Draconic",
        },
    ],

    senses: [
        {
            sense_type: "darkvision",
            range_feet: 60,
        },
    ],

    movements: [
        {
            movement_type: "walk",
            speed_feet: 30,
        },
    ],
} satisfies CharacterSheet

export const sparseCharacterSheetFixture = {
    character_id: "character-sparse",
    name: "Sparse Fighter",
    species_code: "human",
    species_display_name: "Human",
    size_category: "medium",

    character_build_id: null,
    build_label: null,
    ruleset_code: null,
    ruleset_display_name: null,
    ruleset_version_id: null,
    ruleset_version_label: null,

    total_level: 0,
    proficiency_bonus: null,

    class_levels: [],
    ability_scores: [],
    skills: [],
    saving_throws: [],
    other_proficiencies: [],
    features: [],
    spellcasting_profiles: [],

    languages: [
        {
            language_id: "language-common",
            code: "common",
            display_name: "Common",
        },
    ],

    senses: [
        {
            sense_type: "darkvision",
            range_feet: 60,
        },
    ],

    movements: [
        {
            movement_type: "walk",
            speed_feet: 30,
        },
    ],
} satisfies CharacterSheet