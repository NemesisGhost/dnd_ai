import {
    createKnowledgeItem,
    fetchKnowledgeSubjectOptions,
    knowledgeOptionsPath,
} from "../api/knowledgeAuthoring"
import { ContentCreatePage } from "../components/authoring/ContentCreatePage"
import type { ContentCreateConfig } from "../components/authoring/ContentCreatePage"
import { SelectField, TextAreaField } from "../components/authoring/fields"
import { ReferenceCombobox } from "../components/authoring/ReferenceCombobox"
import type { ReferenceOption } from "../components/authoring/ReferenceCombobox"
import type { CreateKnowledgeBody, KnowledgeOptions } from "../types/knowledgeAuthoring"
import type { KnowledgeReceipt } from "../types/contentAuthoring"
import { EMPTY, FIELD, STATEMENT_MAX, same, toBody, validate } from "../utils/knowledgeForm"
import type { KnowledgeFormValues } from "../utils/knowledgeForm"
import { statusDetail } from "../utils/locationForm"

const knowledgePath = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}/knowledge`

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
