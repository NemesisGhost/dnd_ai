import type { FieldError } from "../components/authoring/feedback"
import type { BuildOptions, CreateBuildBody } from "../types/characterBuilds"

// Form state and mirrors of the server's build validation (the server is
// authoritative; these only catch the obvious before a request is sent).

export interface ClassRow {
    classId: string
    subclassId: string
    level: string
}

export interface FreeTextProficiencyRow {
    typeId: string
    label: string
}

export interface SpellcastingRow {
    classId: string
    abilityId: string
    known: string[]
    prepared: string[]
}

export interface BuildFormValues {
    label: string
    scores: Record<string, string> // ability id -> score text ("" = not set)
    classes: ClassRow[]
    skills: string[] // skill ids
    saves: string[] // ability ids
    freeText: FreeTextProficiencyRow[]
    features: string[]
    spellcasting: SpellcastingRow[]
}

export const EMPTY_BUILD: BuildFormValues = {
    label: "",
    scores: {},
    classes: [],
    skills: [],
    saves: [],
    freeText: [],
    features: [],
    spellcasting: [],
}

export function isWholeNumber(text: string): boolean {
    return /^\d+$/.test(text.trim())
}

export function validateBuild(values: BuildFormValues, options: BuildOptions): FieldError[] {
    const errors: FieldError[] = []
    const { limits } = options
    if (values.label.trim().length > limits.label_max_length) {
        errors.push({
            fieldId: "build-label",
            message: `Label must be ${limits.label_max_length} characters or fewer.`,
        })
    }
    for (const ability of options.abilities) {
        const text = (values.scores[ability.id] ?? "").trim()
        if (text === "") continue
        const score = Number(text)
        if (
            !isWholeNumber(text) ||
            score < limits.ability_score_min ||
            score > limits.ability_score_max
        ) {
            errors.push({
                fieldId: `build-score-${ability.id}`,
                message: `${ability.name} must be a whole number from ${limits.ability_score_min} to ${limits.ability_score_max}.`,
            })
        }
    }
    const seen = new Set<string>()
    values.classes.forEach((row, index) => {
        const id = `build-class-${index}`
        if (row.classId === "") {
            errors.push({ fieldId: id, message: "Choose a class." })
        } else if (seen.has(row.classId)) {
            errors.push({ fieldId: id, message: "Each class can be added once." })
        }
        seen.add(row.classId)
        const level = Number(row.level)
        if (
            !isWholeNumber(row.level) ||
            level < limits.class_level_min ||
            level > limits.class_level_max
        ) {
            errors.push({
                fieldId: `build-level-${index}`,
                message: `Level must be a whole number from ${limits.class_level_min} to ${limits.class_level_max}.`,
            })
        }
    })
    values.freeText.forEach((row, index) => {
        if (row.typeId === "") {
            errors.push({ fieldId: `build-free-type-${index}`, message: "Choose a kind." })
        }
        if (row.label.trim() === "") {
            errors.push({ fieldId: `build-free-label-${index}`, message: "Enter a name." })
        } else if (row.label.trim().length > limits.target_label_max_length) {
            errors.push({
                fieldId: `build-free-label-${index}`,
                message: `Name must be ${limits.target_label_max_length} characters or fewer.`,
            })
        }
    })
    values.spellcasting.forEach((row, index) => {
        if (row.abilityId === "") {
            errors.push({
                fieldId: `build-cast-ability-${index}`,
                message: "Choose a spellcasting ability.",
            })
        }
    })
    return errors
}

export function toBuildBody(values: BuildFormValues, options: BuildOptions): CreateBuildBody {
    const skillType = options.proficiency_types.find((t) => t.target_kind === "skill")
    const saveType = options.proficiency_types.find((t) => t.target_kind === "saving_throw")
    const proficiencies: CreateBuildBody["proficiencies"] = []
    if (skillType !== undefined) {
        for (const skillId of values.skills) {
            proficiencies.push({
                proficiency_type_id: skillType.id,
                skill_id: skillId,
                is_expertise: false,
            })
        }
    }
    if (saveType !== undefined) {
        for (const abilityId of values.saves) {
            proficiencies.push({
                proficiency_type_id: saveType.id,
                saving_throw_ability_id: abilityId,
                is_expertise: false,
            })
        }
    }
    for (const row of values.freeText) {
        proficiencies.push({
            proficiency_type_id: row.typeId,
            target_label: row.label.trim(),
            is_expertise: false,
        })
    }
    return {
        label: values.label.trim() === "" ? null : values.label.trim(),
        ability_scores: options.abilities
            .filter((a) => (values.scores[a.id] ?? "").trim() !== "")
            .map((a) => ({ ability_id: a.id, score: Number(values.scores[a.id]) })),
        class_levels: values.classes.map((row) => ({
            class_id: row.classId,
            subclass_id: row.subclassId === "" ? null : row.subclassId,
            level: Number(row.level),
        })),
        proficiencies,
        feature_ids: values.features,
        spellcasting: values.spellcasting.map((row) => ({
            class_id: row.classId === "" ? null : row.classId,
            spellcasting_ability_id: row.abilityId,
            known_spell_ids: row.known,
            prepared_spell_ids: row.prepared,
        })),
    }
}

export function isBuildDirty(values: BuildFormValues): boolean {
    return (
        values.label.trim() !== "" ||
        Object.values(values.scores).some((s) => s.trim() !== "") ||
        values.classes.length > 0 ||
        values.skills.length > 0 ||
        values.saves.length > 0 ||
        values.freeText.length > 0 ||
        values.features.length > 0 ||
        values.spellcasting.length > 0
    )
}
