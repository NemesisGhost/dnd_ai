import { createQuest, questOptionsPath } from "../api/questAuthoring"
import { ContentCreatePage } from "../components/authoring/ContentCreatePage"
import type { ContentCreateConfig } from "../components/authoring/ContentCreatePage"
import type { FieldError } from "../components/authoring/feedback"
import { TextAreaField, TextField } from "../components/authoring/fields"
import type { CreateQuestBody, QuestOptions } from "../types/questAuthoring"
import {
    DESCRIPTION_MAX,
    NAME_MAX,
    validateDescription,
    validateName,
} from "../utils/authoringValidation"
import "../components/authoring/authoring.css"
import type { QuestReceipt } from "../types/contentAuthoring"

interface QuestFormValues {
    name: string
    summary: string
}

const EMPTY: QuestFormValues = { name: "", summary: "" }

const questsPath = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}/quests`

const createConfig: ContentCreateConfig<
    QuestOptions,
    QuestFormValues,
    CreateQuestBody,
    QuestReceipt
> = {
    noun: "quest",
    heading: "New quest",
    lead: "A new quest is saved as a draft. Next you add its stages and objectives. Only people who can edit canon see it until it is published.",
    breadcrumbLabel: "Quests",
    worldPath: questsPath,
    optionsPath: questOptionsPath,
    canCreate: (options) => options.can_create,
    initialValues: () => EMPTY,
    isDirty: (values, initial) =>
        values.name.trim() !== initial.name || values.summary.trim() !== initial.summary,
    validate: (values) => {
        const errors: FieldError[] = []
        const name = validateName(values.name)
        if (name) errors.push({ fieldId: "new-quest-name", message: name })
        const summary = validateDescription(values.summary)
        if (summary) {
            errors.push({
                fieldId: "new-quest-summary",
                message: summary.replace("Description", "Summary"),
            })
        }
        return errors
    },
    toBody: (values) => ({
        name: values.name.trim(),
        summary: values.summary.trim() === "" ? null : values.summary.trim(),
    }),
    create: createQuest,
    resultPath: (campaignId, created) =>
        `${questsPath(campaignId)}/${encodeURIComponent(created.quest_id)}?section=structure`,
    announce: "Quest created as a draft. Add its stages and objectives.",
    saveLabel: "Create quest",
    pendingLabel: "Creating…",
    renderFields: ({ values, setValues, errorFor }) => (
        <>
            <TextField
                id="new-quest-name"
                label="Name"
                value={values.name}
                onChange={(name) => setValues({ ...values, name })}
                required
                maxLength={NAME_MAX}
                error={errorFor("new-quest-name")}
            />
            <TextAreaField
                id="new-quest-summary"
                label="Summary"
                value={values.summary}
                onChange={(summary) => setValues({ ...values, summary })}
                maxLength={DESCRIPTION_MAX}
                error={errorFor("new-quest-summary")}
            />
        </>
    ),
}

// Create a Quest draft: /app/:campaignId/quests/new. Stages and objectives are
// added in the quest's own workspace (its Stages and objectives section), which this
// creation lands on.
export function CreateQuestPage() {
    return <ContentCreatePage config={createConfig} />
}
