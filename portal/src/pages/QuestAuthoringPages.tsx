import { Link, useParams } from "react-router"
import { createQuest, questAuthoringPath, questOptionsPath } from "../api/questAuthoring"
import { ContentCreatePage } from "../components/authoring/ContentCreatePage"
import type { ContentCreateConfig } from "../components/authoring/ContentCreatePage"
import type { FieldError } from "../components/authoring/feedback"
import { TextAreaField, TextField } from "../components/authoring/fields"
import { QuestCompletionEditor } from "../components/authoring/QuestCompletionEditor"
import { QuestEditor } from "../components/authoring/QuestEditor"
import { EntityLifecyclePanel } from "../components/EntityLifecyclePanel"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { usePageArrival } from "../hooks/usePageArrival"
import type { CreateQuestBody, QuestAuthoringView, QuestOptions } from "../types/questAuthoring"
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
        `${questsPath(campaignId)}/${encodeURIComponent(created.quest_id)}/edit`,
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
// added on the quest's own editor page, which this creation lands on.
export function CreateQuestPage() {
    return <ContentCreatePage config={createConfig} />
}

// Edit a Quest definition: /app/:campaignId/quests/:questId/edit. Loads the
// authoring aggregate keyed by the URL, so it reloads and deep-links on its own.
export function EditQuestPage() {
    const { campaignId = "", questId = "" } = useParams()
    const { state, refetch } = useAuthoringResource<QuestAuthoringView>(
        questAuthoringPath(campaignId, questId),
    )
    const options = useAuthoringResource<QuestOptions>(questOptionsPath(campaignId))
    const ready = state.kind === "ready" && options.state.kind === "ready"
    const headingRef = usePageArrival(ready)

    return (
        <section className="authoring-page" aria-labelledby="edit-quest-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={questsPath(campaignId)}>Quests</Link>
                {state.kind === "ready" ? <> / {state.data.name}</> : null}
            </p>
            <h1 id="edit-quest-heading" ref={headingRef} tabIndex={-1}>
                Edit quest
            </h1>
            {state.kind === "loading" || options.state.kind === "loading" ? (
                <p role="status">Loading quest…</p>
            ) : state.kind === "unavailable" || state.kind === "denied" ? (
                <p role="alert">This quest does not exist, or you do not have access to it.</p>
            ) : state.kind === "error" || options.state.kind !== "ready" ? (
                <p role="alert">The quest could not be loaded. Try reloading the page.</p>
            ) : (
                <>
                    <QuestEditor
                        campaignId={campaignId}
                        view={state.data}
                        options={options.state.data}
                        refreshing={state.refreshing}
                        refetch={refetch}
                    />
                    <QuestCompletionEditor
                        key={state.data.row_version}
                        campaignId={campaignId}
                        view={state.data}
                        options={options.state.data}
                        refetch={refetch}
                    />
                    <EntityLifecyclePanel
                        campaignId={campaignId}
                        entityId={questId}
                        onChanged={() => void refetch()}
                    />
                </>
            )}
        </section>
    )
}
