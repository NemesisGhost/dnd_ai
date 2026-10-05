import {
    createKnowledgeItem,
    fetchKnowledgeSubjectOptions,
    knowledgeAuthoringPath,
    knowledgeOptionsPath,
    updateKnowledgeItem,
} from "../api/knowledgeAuthoring"
import { ContentCreatePage } from "../components/authoring/ContentCreatePage"
import type { ContentCreateConfig } from "../components/authoring/ContentCreatePage"
import { ContentEditPage } from "../components/authoring/ContentEditPage"
import type { ContentEditConfig } from "../components/authoring/ContentEditPage"
import type { FieldError } from "../components/authoring/feedback"
import { SelectField, TextAreaField } from "../components/authoring/fields"
import { ReferenceCombobox } from "../components/authoring/ReferenceCombobox"
import type { ReferenceOption } from "../components/authoring/ReferenceCombobox"
import type {
    CreateKnowledgeBody,
    KnowledgeAuthoringView,
    KnowledgeFieldsBody,
    KnowledgeOptions,
} from "../types/knowledgeAuthoring"
import { statusDetail } from "../utils/locationForm"
import type { KnowledgeReceipt } from "../types/contentAuthoring"

interface KnowledgeFormValues {
    statement: string
    knowledgeType: string
    truthStatus: string
    sensitivity: string
    subject: ReferenceOption | null
}

const EMPTY: KnowledgeFormValues = {
    statement: "",
    knowledgeType: "",
    truthStatus: "",
    sensitivity: "",
    subject: null,
}

const FIELD = {
    statement: "knowledge-statement",
    type: "knowledge-type",
    truth: "knowledge-truth",
    sensitivity: "knowledge-sensitivity",
    subject: "knowledge-subject",
} as const

const STATEMENT_MAX = 4000

const knowledgePath = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}/knowledge`

function same(a: KnowledgeFormValues, b: KnowledgeFormValues): boolean {
    return (
        a.statement.trim() === b.statement.trim() &&
        a.knowledgeType === b.knowledgeType &&
        a.truthStatus === b.truthStatus &&
        a.sensitivity === b.sensitivity &&
        (a.subject?.id ?? null) === (b.subject?.id ?? null)
    )
}

function validate(values: KnowledgeFormValues): FieldError[] {
    const errors: FieldError[] = []
    const statement = values.statement.trim()
    if (statement === "") {
        errors.push({ fieldId: FIELD.statement, message: "Statement is required." })
    } else if (statement.length > STATEMENT_MAX) {
        errors.push({
            fieldId: FIELD.statement,
            message: `Statement must be ${STATEMENT_MAX} characters or fewer.`,
        })
    }
    if (values.knowledgeType === "") errors.push({ fieldId: FIELD.type, message: "Choose a type." })
    if (values.truthStatus === "") {
        errors.push({ fieldId: FIELD.truth, message: "Choose whether the claim is true." })
    }
    if (values.sensitivity === "") {
        errors.push({ fieldId: FIELD.sensitivity, message: "Choose a sensitivity." })
    }
    return errors
}

function toBody(values: KnowledgeFormValues): KnowledgeFieldsBody {
    return {
        statement: values.statement.trim(),
        knowledge_type: values.knowledgeType,
        truth_status: values.truthStatus,
        sensitivity: values.sensitivity,
        subject_entity_id: values.subject?.id ?? null,
    }
}

function fromView(view: KnowledgeAuthoringView): KnowledgeFormValues {
    return {
        statement: view.statement,
        knowledgeType: view.knowledge_type,
        truthStatus: view.truth_status,
        sensitivity: view.sensitivity,
        subject:
            view.subject === null
                ? null
                : {
                      id: view.subject.entity_id,
                      label: view.subject.name,
                      detail: statusDetail(view.subject.canon_status, view.subject.lifecycle_status),
                  },
    }
}

function Fields({
    campaignId,
    options,
    values,
    setValues,
    errorFor,
    locked,
}: {
    campaignId: string
    options: KnowledgeOptions
    values: KnowledgeFormValues
    setValues: (values: KnowledgeFormValues) => void
    errorFor: (fieldId: string) => string | null
    // True once someone knows the claim: statement, type and subject are frozen.
    locked: boolean
}) {
    async function searchSubjects(query: string, signal: AbortSignal): Promise<ReferenceOption[]> {
        const page = await fetchKnowledgeSubjectOptions(campaignId, query, signal)
        return page.items.map((item) => ({
            id: item.entity_id,
            label: item.name,
            detail: `${item.kind.replace(/_/g, " ")}, ${statusDetail(item.canon_status, "active")}`,
        }))
    }

    const lockHint = "Someone already knows this claim, so this cannot change."

    return (
        <>
            <TextAreaField
                id={FIELD.statement}
                label="Statement"
                hint={locked ? lockHint : "The claim itself, in one or two sentences."}
                value={values.statement}
                onChange={(statement) => setValues({ ...values, statement })}
                required
                disabled={locked}
                maxLength={STATEMENT_MAX}
                error={errorFor(FIELD.statement)}
            />
            <SelectField
                id={FIELD.type}
                label="Type"
                hint={locked ? lockHint : undefined}
                value={values.knowledgeType}
                placeholder="Choose a type"
                required
                disabled={locked}
                options={options.knowledge_types}
                error={errorFor(FIELD.type)}
                onChange={(knowledgeType) => setValues({ ...values, knowledgeType })}
            />
            <SelectField
                id={FIELD.truth}
                label="Truth"
                hint="What is actually true in the world, whatever anyone believes."
                value={values.truthStatus}
                placeholder="Choose"
                required
                options={options.truth_statuses}
                error={errorFor(FIELD.truth)}
                onChange={(truthStatus) => setValues({ ...values, truthStatus })}
            />
            <SelectField
                id={FIELD.sensitivity}
                label="Sensitivity"
                value={values.sensitivity}
                placeholder="Choose a sensitivity"
                required
                options={options.sensitivities}
                error={errorFor(FIELD.sensitivity)}
                onChange={(sensitivity) => setValues({ ...values, sensitivity })}
            />
            <ReferenceCombobox
                id={FIELD.subject}
                label="Subject"
                hint={locked ? lockHint : "What this claim is about. Optional."}
                value={values.subject}
                onChange={(subject) => setValues({ ...values, subject })}
                search={searchSubjects}
                error={errorFor(FIELD.subject)}
                placeholder="Search places, organizations, religions, characters, quests"
                disabled={locked}
            />
        </>
    )
}

const createConfig: ContentCreateConfig<
    KnowledgeOptions,
    KnowledgeFormValues,
    CreateKnowledgeBody,
    KnowledgeReceipt
> = {
    noun: "knowledge claim",
    heading: "New knowledge claim",
    lead: "A new claim is saved as a draft. Only people who can edit canon see it until it is published. This writes the claim only; who knows it is recorded separately.",
    breadcrumbLabel: "Knowledge",
    worldPath: knowledgePath,
    optionsPath: knowledgeOptionsPath,
    canCreate: (options) => options.can_create,
    initialValues: () => EMPTY,
    isDirty: (values, initial) => !same(values, initial),
    validate: (values) => validate(values),
    toBody: (values) => toBody(values),
    create: createKnowledgeItem,
    resultPath: (campaignId, created) =>
        `${knowledgePath(campaignId)}/${encodeURIComponent(created.knowledge_item_id)}`,
    announce: "Knowledge claim created as a draft",
    saveLabel: "Create claim",
    pendingLabel: "Creating…",
    renderFields: ({ campaignId, options, values, setValues, errorFor }) => (
        <Fields
            campaignId={campaignId}
            options={options}
            values={values}
            setValues={setValues}
            errorFor={errorFor}
            locked={false}
        />
    ),
}

// Create a knowledge claim draft: /app/:campaignId/knowledge/new.
export function CreateKnowledgePage() {
    return <ContentCreatePage config={createConfig} />
}

const editConfig: ContentEditConfig<
    KnowledgeAuthoringView,
    KnowledgeOptions,
    KnowledgeFormValues,
    KnowledgeFieldsBody
> = {
    noun: "knowledge claim",
    heading: "Edit knowledge claim",
    entityParam: "knowledgeItemId",
    breadcrumbLabel: "Knowledge",
    worldPath: knowledgePath,
    detailPath: (campaignId, id) => `${knowledgePath(campaignId)}/${encodeURIComponent(id)}`,
    viewPath: knowledgeAuthoringPath,
    optionsPath: knowledgeOptionsPath,
    name: (view) => (view.statement.length > 60 ? `${view.statement.slice(0, 57)}…` : view.statement),
    valuesFromView: fromView,
    same,
    validate: (values) => validate(values),
    toBody: (values) => toBody(values),
    update: updateKnowledgeItem,
    renderFields: ({ campaignId, view, options, values, setValues, errorFor }) => (
        <Fields
            campaignId={campaignId}
            options={options}
            values={values}
            setValues={setValues}
            errorFor={errorFor}
            locked={view.in_use}
        />
    ),
    summarize: (values) => (
        <dl className="authoring-fact-list">
            <dt>Statement</dt>
            <dd>{values.statement || "(empty)"}</dd>
            <dt>Type</dt>
            <dd>{values.knowledgeType || "(none)"}</dd>
            <dt>Truth</dt>
            <dd>{values.truthStatus || "(none)"}</dd>
            <dt>Sensitivity</dt>
            <dd>{values.sensitivity || "(none)"}</dd>
            <dt>Subject</dt>
            <dd>{values.subject?.label ?? "(none)"}</dd>
        </dl>
    ),
    canonWarning:
        "This claim is published. People with access will see the change. For a change in meaning, create a replacement claim instead.",
    saved: "Knowledge claim saved",
}

// Edit a knowledge claim: /app/:campaignId/knowledge/:knowledgeItemId/edit.
export function EditKnowledgePage() {
    return <ContentEditPage config={editConfig} />
}
