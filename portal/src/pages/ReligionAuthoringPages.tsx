import {
    createReligion,
    religionAuthoringPath,
    religionOptionsPath,
    updateReligion,
} from "../api/organizationAuthoring"
import { ContentCreatePage } from "../components/authoring/ContentCreatePage"
import type { ContentCreateConfig } from "../components/authoring/ContentCreatePage"
import { ContentEditPage } from "../components/authoring/ContentEditPage"
import type { ContentEditConfig } from "../components/authoring/ContentEditPage"
import type { FieldError } from "../components/authoring/feedback"
import { TextAreaField, TextField } from "../components/authoring/fields"
import type {
    CreateReligionBody,
    ReligionAuthoringView,
    ReligionFieldsBody,
    ReligionOptions,
} from "../types/organizationAuthoring"
import {
    DESCRIPTION_MAX,
    NAME_MAX,
    validateDescription,
    validateName,
} from "../utils/authoringValidation"

interface ReligionFormValues {
    name: string
    summary: string
    pantheon: string
}

const EMPTY: ReligionFormValues = { name: "", summary: "", pantheon: "" }

const FIELD = {
    name: "religion-name",
    summary: "religion-summary",
    pantheon: "religion-pantheon",
} as const

const worldPath = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}/world`

const same = (a: ReligionFormValues, b: ReligionFormValues): boolean =>
    a.name.trim() === b.name.trim() &&
    a.summary.trim() === b.summary.trim() &&
    a.pantheon.trim() === b.pantheon.trim()

function validate(values: ReligionFormValues): FieldError[] {
    const errors: FieldError[] = []
    const nameError = validateName(values.name)
    if (nameError) errors.push({ fieldId: FIELD.name, message: nameError })
    const summaryError = validateDescription(values.summary)
    if (summaryError) {
        errors.push({ fieldId: FIELD.summary, message: summaryError.replace("Description", "Summary") })
    }
    if (values.pantheon.trim().length > DESCRIPTION_MAX) {
        errors.push({
            fieldId: FIELD.pantheon,
            message: `Pantheon structure must be ${DESCRIPTION_MAX} characters or fewer.`,
        })
    }
    return errors
}

function toBody(values: ReligionFormValues): ReligionFieldsBody {
    return {
        name: values.name.trim(),
        summary: values.summary.trim() === "" ? null : values.summary.trim(),
        pantheon_structure: values.pantheon.trim() === "" ? null : values.pantheon.trim(),
    }
}

function Fields({
    values,
    setValues,
    errorFor,
}: {
    values: ReligionFormValues
    setValues: (values: ReligionFormValues) => void
    errorFor: (fieldId: string) => string | null
}) {
    return (
        <>
            <TextField
                id={FIELD.name}
                label="Name"
                value={values.name}
                onChange={(name) => setValues({ ...values, name })}
                required
                maxLength={NAME_MAX}
                error={errorFor(FIELD.name)}
            />
            <TextAreaField
                id={FIELD.summary}
                label="Summary"
                value={values.summary}
                onChange={(summary) => setValues({ ...values, summary })}
                maxLength={DESCRIPTION_MAX}
                error={errorFor(FIELD.summary)}
            />
            <TextAreaField
                id={FIELD.pantheon}
                label="Pantheon structure"
                hint="How the divine is organised: a single god, a pantheon, ancestors, and so on."
                value={values.pantheon}
                onChange={(pantheon) => setValues({ ...values, pantheon })}
                maxLength={DESCRIPTION_MAX}
                error={errorFor(FIELD.pantheon)}
            />
        </>
    )
}

const createConfig: ContentCreateConfig<
    ReligionOptions,
    ReligionFormValues,
    CreateReligionBody,
    ReligionAuthoringView
> = {
    noun: "religion",
    heading: "New religion",
    lead: "A new religion is saved as a draft. Only people who can edit canon see it until it is published.",
    breadcrumbLabel: "World",
    worldPath,
    optionsPath: religionOptionsPath,
    canCreate: (options) => options.can_create,
    initialValues: () => EMPTY,
    isDirty: (values, initial) => !same(values, initial),
    validate: (values) => validate(values),
    toBody: (values) => toBody(values),
    create: createReligion,
    resultPath: (campaignId, created) =>
        `${worldPath(campaignId)}/religion/${encodeURIComponent(created.religion_id)}`,
    announce: "Religion created as a draft",
    saveLabel: "Create religion",
    pendingLabel: "Creating…",
    renderFields: ({ values, setValues, errorFor }) => (
        <Fields values={values} setValues={setValues} errorFor={errorFor} />
    ),
}

// Create a Religion draft: /app/:campaignId/world/religion/new.
export function CreateReligionPage() {
    return <ContentCreatePage config={createConfig} />
}

const editConfig: ContentEditConfig<
    ReligionAuthoringView,
    ReligionOptions,
    ReligionFormValues,
    ReligionFieldsBody
> = {
    noun: "religion",
    heading: "Edit religion",
    entityParam: "entityId",
    breadcrumbLabel: "World",
    worldPath,
    detailPath: (campaignId, id) => `${worldPath(campaignId)}/religion/${encodeURIComponent(id)}`,
    viewPath: religionAuthoringPath,
    optionsPath: religionOptionsPath,
    name: (view) => view.name,
    valuesFromView: (view) => ({
        name: view.name,
        summary: view.summary ?? "",
        pantheon: view.pantheon_structure ?? "",
    }),
    same,
    validate: (values) => validate(values),
    toBody: (values) => toBody(values),
    update: updateReligion,
    renderFields: ({ values, setValues, errorFor }) => (
        <Fields values={values} setValues={setValues} errorFor={errorFor} />
    ),
    summarize: (values) => (
        <dl className="authoring-fact-list">
            <dt>Name</dt>
            <dd>{values.name}</dd>
            <dt>Summary</dt>
            <dd>{values.summary || "(empty)"}</dd>
            <dt>Pantheon structure</dt>
            <dd>{values.pantheon || "(empty)"}</dd>
        </dl>
    ),
    canonWarning:
        "This religion is published. People with access will see the change. For a change in meaning, create a replacement and supersede this religion instead.",
    saved: "Religion saved",
}

// Edit a Religion definition: /app/:campaignId/world/religion/:entityId/edit.
export function EditReligionPage() {
    return <ContentEditPage config={editConfig} />
}
