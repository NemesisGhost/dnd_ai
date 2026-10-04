import type { ReferenceOption } from "../components/authoring/ReferenceCombobox"
import type { FieldError } from "../components/authoring/feedback"
import type {
    OrganizationAuthoringView,
    OrganizationFieldDescriptor,
    OrganizationFieldsBody,
    OrganizationKindOption,
} from "../types/organizationAuthoring"
import { validateDescription, validateName } from "./authoringValidation"
import { statusDetail } from "./locationForm"

// The Organization form's values, held as typed. Kind-specific fields live in
// `typed` keyed by the server catalog's field names, so a new field never needs
// a new component. The server stays authoritative; these checks surface the
// structural limits early.

export interface OrganizationFormValues {
    kind: string
    name: string
    summary: string
    publicDescription: string
    internalDescription: string
    parent: ReferenceOption | null
    headquarters: ReferenceOption | null
    religion: ReferenceOption | null
    typed: Record<string, string>
}

export const EMPTY_ORGANIZATION_FORM: OrganizationFormValues = {
    kind: "",
    name: "",
    summary: "",
    publicDescription: "",
    internalDescription: "",
    parent: null,
    headquarters: null,
    religion: null,
    typed: {},
}

export const ORG_FIELD_IDS = {
    kind: "org-kind",
    name: "org-name",
    summary: "org-summary",
    publicDescription: "org-public-description",
    internalDescription: "org-internal-description",
    parent: "org-parent",
    headquarters: "org-headquarters",
    religion: "org-religion",
} as const

export const typedFieldId = (name: string): string => `org-field-${name}`

const DESCRIPTION_MAX = 4000

function reference(
    value: { entity_id: string; name: string; canon_status: string; lifecycle_status: string } | null,
): ReferenceOption | null {
    return value === null
        ? null
        : {
              id: value.entity_id,
              label: value.name,
              detail: statusDetail(value.canon_status, value.lifecycle_status),
          }
}

export function valuesFromOrganizationView(view: OrganizationAuthoringView): OrganizationFormValues {
    const typed: Record<string, string> = {}
    for (const [key, value] of Object.entries(view.typed)) {
        typed[key] = value === null ? "" : String(value)
    }
    return {
        kind: view.kind.code,
        name: view.name,
        summary: view.summary ?? "",
        publicDescription: view.public_description ?? "",
        internalDescription: view.internal_description ?? "",
        parent: reference(view.parent),
        headquarters: reference(view.headquarters),
        religion: reference(view.religion),
        typed,
    }
}

export function sameOrganizationValues(a: OrganizationFormValues, b: OrganizationFormValues): boolean {
    const keys = new Set([...Object.keys(a.typed), ...Object.keys(b.typed)])
    for (const key of keys) {
        if ((a.typed[key] ?? "").trim() !== (b.typed[key] ?? "").trim()) return false
    }
    return (
        a.kind === b.kind &&
        a.name.trim() === b.name.trim() &&
        a.summary.trim() === b.summary.trim() &&
        a.publicDescription.trim() === b.publicDescription.trim() &&
        a.internalDescription.trim() === b.internalDescription.trim() &&
        (a.parent?.id ?? null) === (b.parent?.id ?? null) &&
        (a.headquarters?.id ?? null) === (b.headquarters?.id ?? null) &&
        (a.religion?.id ?? null) === (b.religion?.id ?? null)
    )
}

function validateTypedField(
    descriptor: OrganizationFieldDescriptor,
    raw: string,
): FieldError | null {
    const id = typedFieldId(descriptor.name)
    const text = raw.trim()
    if (descriptor.kind === "integer") {
        if (text === "") return null
        const number = Number(text)
        const min = descriptor.minimum ?? Number.MIN_SAFE_INTEGER
        const max = descriptor.maximum ?? Number.MAX_SAFE_INTEGER
        if (!/^-?\d+$/.test(text) || number < min || number > max) {
            return {
                fieldId: id,
                message: `${descriptor.label} must be a whole number from ${min} to ${max}.`,
            }
        }
        return null
    }
    if (descriptor.kind === "select") {
        if (text === "") {
            return descriptor.required ? { fieldId: id, message: `Choose a ${descriptor.label.toLowerCase()}.` } : null
        }
        return descriptor.options.some((o) => o.value === text)
            ? null
            : { fieldId: id, message: `${descriptor.label} is not an allowed choice.` }
    }
    const max = descriptor.max_length ?? 200
    return text.length > max
        ? { fieldId: id, message: `${descriptor.label} must be ${max} characters or fewer.` }
        : null
}

export function validateOrganizationForm(
    values: OrganizationFormValues,
    kind: OrganizationKindOption | undefined,
    options: { requireKind: boolean },
): FieldError[] {
    const errors: FieldError[] = []
    if (options.requireKind && values.kind === "") {
        errors.push({ fieldId: ORG_FIELD_IDS.kind, message: "Choose a kind of organization." })
    }
    const nameError = validateName(values.name)
    if (nameError) errors.push({ fieldId: ORG_FIELD_IDS.name, message: nameError })
    const summaryError = validateDescription(values.summary)
    if (summaryError) {
        errors.push({
            fieldId: ORG_FIELD_IDS.summary,
            message: summaryError.replace("Description", "Summary"),
        })
    }
    if (values.publicDescription.trim().length > DESCRIPTION_MAX) {
        errors.push({
            fieldId: ORG_FIELD_IDS.publicDescription,
            message: `Public description must be ${DESCRIPTION_MAX} characters or fewer.`,
        })
    }
    if (values.internalDescription.trim().length > DESCRIPTION_MAX) {
        errors.push({
            fieldId: ORG_FIELD_IDS.internalDescription,
            message: `GM notes must be ${DESCRIPTION_MAX} characters or fewer.`,
        })
    }
    if (kind?.needs_religion && values.religion === null) {
        errors.push({ fieldId: ORG_FIELD_IDS.religion, message: "Choose the religion this organization serves." })
    }
    for (const descriptor of kind?.fields ?? []) {
        const problem = validateTypedField(descriptor, values.typed[descriptor.name] ?? "")
        if (problem) errors.push(problem)
    }
    return errors
}

// Only the fields the kind carries are sent; a hidden one is never carried over
// from a kind the user switched away from.
export function toOrganizationBody(
    values: OrganizationFormValues,
    kind: OrganizationKindOption | undefined,
): OrganizationFieldsBody {
    const body: OrganizationFieldsBody = {
        name: values.name.trim(),
        summary: values.summary.trim() === "" ? null : values.summary.trim(),
        public_description: values.publicDescription.trim() === "" ? null : values.publicDescription.trim(),
        internal_description:
            values.internalDescription.trim() === "" ? null : values.internalDescription.trim(),
        parent_organization_id: values.parent?.id ?? null,
        headquarters_location_id: values.headquarters?.id ?? null,
        religion_id: kind?.needs_religion ? (values.religion?.id ?? null) : null,
    }
    const target = body as unknown as Record<string, string | number | null>
    for (const descriptor of kind?.fields ?? []) {
        const text = (values.typed[descriptor.name] ?? "").trim()
        target[descriptor.name] =
            text === "" ? null : descriptor.kind === "integer" ? Number(text) : text
    }
    return body
}
