import type { ReferenceOption } from "../components/authoring/ReferenceCombobox"
import type { FieldError } from "../components/authoring/feedback"
import type {
    LocationAuthoringView,
    LocationCategoryOption,
    LocationFieldsBody,
} from "../types/locationAuthoring"
import { validateDescription, validateName } from "./authoringValidation"

// The editable Location form's values, held as the user typed them. Mirrors the
// server's closed contract (docs/PLAN.md Phase 15.1, ADR 0015); the server stays
// authoritative, these checks only surface the structural limits early.

export interface LocationFormValues {
    category: string
    name: string
    summary: string
    parent: ReferenceOption | null
    population: string
    buildingUse: string
}

export const EMPTY_LOCATION_FORM: LocationFormValues = {
    category: "",
    name: "",
    summary: "",
    parent: null,
    population: "",
    buildingUse: "",
}

export const FIELD_IDS = {
    category: "location-category",
    name: "location-name",
    summary: "location-summary",
    parent: "location-parent",
    population: "location-population",
    buildingUse: "location-building-use",
} as const

const BUILDING_USE_MAX = 200
const POPULATION_MAX = 2_147_483_647

export function statusDetail(canonStatus: string, lifecycleStatus: string): string {
    if (lifecycleStatus === "archived") return "Archived"
    return (
        { draft: "Draft", proposed: "In review", approved: "Approved", canon: "Canon" }[
            canonStatus
        ] ?? canonStatus
    )
}

export function valuesFromView(view: LocationAuthoringView): LocationFormValues {
    return {
        category: view.category.code,
        name: view.name,
        summary: view.summary ?? "",
        parent:
            view.parent === null
                ? null
                : {
                      id: view.parent.location_id,
                      label: view.parent.name,
                      detail: statusDetail(view.parent.canon_status, view.parent.lifecycle_status),
                  },
        population: view.population === null ? "" : String(view.population),
        buildingUse: view.building_use ?? "",
    }
}

export function sameValues(a: LocationFormValues, b: LocationFormValues): boolean {
    return (
        a.category === b.category &&
        a.name.trim() === b.name.trim() &&
        a.summary.trim() === b.summary.trim() &&
        (a.parent?.id ?? null) === (b.parent?.id ?? null) &&
        a.population.trim() === b.population.trim() &&
        a.buildingUse.trim() === b.buildingUse.trim()
    )
}

export function applicableFields(category: LocationCategoryOption | undefined): Set<string> {
    return new Set((category?.fields ?? []).map((f) => f.name))
}

export function validateLocationForm(
    values: LocationFormValues,
    category: LocationCategoryOption | undefined,
    options: { requireCategory: boolean },
): FieldError[] {
    const errors: FieldError[] = []
    if (options.requireCategory && values.category === "") {
        errors.push({ fieldId: FIELD_IDS.category, message: "Choose a category." })
    }
    const nameError = validateName(values.name)
    if (nameError) errors.push({ fieldId: FIELD_IDS.name, message: nameError })
    const summaryError = validateDescription(values.summary)
    if (summaryError) {
        errors.push({
            fieldId: FIELD_IDS.summary,
            message: summaryError.replace("Description", "Summary"),
        })
    }
    const applicable = applicableFields(category)
    if (applicable.has("population") && values.population.trim() !== "") {
        const text = values.population.trim()
        const number = Number(text)
        if (!/^\d+$/.test(text) || !Number.isSafeInteger(number) || number > POPULATION_MAX) {
            errors.push({
                fieldId: FIELD_IDS.population,
                message: `Population must be a whole number from 0 to ${POPULATION_MAX.toLocaleString("en-US")}.`,
            })
        }
    }
    if (applicable.has("building_use") && values.buildingUse.trim().length > BUILDING_USE_MAX) {
        errors.push({
            fieldId: FIELD_IDS.buildingUse,
            message: `Use must be ${BUILDING_USE_MAX} characters or fewer.`,
        })
    }
    return errors
}

// Hidden (inapplicable) typed fields are never sent: the server refuses a
// population on a region, so switching category must not carry one along.
export function toFieldsBody(
    values: LocationFormValues,
    category: LocationCategoryOption | undefined,
): LocationFieldsBody {
    const applicable = applicableFields(category)
    return {
        name: values.name.trim(),
        summary: values.summary.trim() === "" ? null : values.summary.trim(),
        parent_location_id: values.parent?.id ?? null,
        population:
            applicable.has("population") && values.population.trim() !== ""
                ? Number(values.population.trim())
                : null,
        building_use:
            applicable.has("building_use") && values.buildingUse.trim() !== ""
                ? values.buildingUse.trim()
                : null,
    }
}
