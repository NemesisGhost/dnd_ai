import { useRef, useState } from "react"
import { useNavigate } from "react-router"
import { fetchQuestTargetOptions, runQuestCommand } from "../../api/questAuthoring"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import { useUnsavedChangesGuard } from "../../hooks/useUnsavedChangesGuard"
import type {
    ObjectiveBody,
    QuestAuthoringView,
    QuestChoice,
    QuestCommand,
    QuestObjectiveView,
    QuestOptions,
    QuestStageView,
    StageBody,
} from "../../types/questAuthoring"
import {
    DESCRIPTION_MAX,
    ERROR_CODE_MESSAGE,
    NAME_MAX,
    fieldForErrorCode,
    validateDescription,
    validateName,
} from "../../utils/authoringValidation"
import { statusDetail } from "../../utils/locationForm"
import { reorderedStageIds, steppedStageIds } from "../../utils/stageOrder"
import { useAnnounce } from "./announcer"
import { ConfirmDialog } from "./ConfirmDialog"
import { SelectField, TextAreaField, TextField } from "./fields"
import {
    AuthoringForm,
    ErrorSummary,
    FormActions,
    MutationStatusMessage,
    StaleWriteNotice,
} from "./feedback"
import type { FieldError } from "./feedback"
import { ReferenceCombobox } from "./ReferenceCombobox"
import type { ReferenceOption } from "./ReferenceCombobox"
import "./authoring.css"

// The Quest definition editor: one reloadable page with the quest's details and
// its stages and objectives as inline panels. Every change is one idempotent
// command carrying the quest's row version; the page re-fetches the authoritative
// aggregate after each. Structure that recorded progress depends on is shown
// locked, with the reason, never silently hidden.

interface DetailsValues {
    name: string
    summary: string
}

interface StageValues {
    name: string
    description: string
    stageType: string
}

interface ObjectiveValues {
    name: string
    description: string
    objectiveType: string
    requirementLevel: string
    completionMode: string
    visibilityPolicy: string
    quantity: string
    target: ReferenceOption | null
}

type Panel =
    | { kind: "stage"; stageId: string | null; values: StageValues; initial: StageValues }
    | {
          kind: "objective"
          stageId: string
          objectiveId: string | null
          values: ObjectiveValues
          initial: ObjectiveValues
      }

type Removal =
    | { kind: "stage"; stage: QuestStageView }
    | { kind: "objective"; stage: QuestStageView; objective: QuestObjectiveView }

const EMPTY_OBJECTIVE_DEFAULTS = {
    requirementLevel: "required",
    completionMode: "automatic",
    visibilityPolicy: "visible",
}

const sameStage = (a: StageValues, b: StageValues) =>
    a.name.trim() === b.name.trim() &&
    a.description.trim() === b.description.trim() &&
    a.stageType === b.stageType

const sameObjective = (a: ObjectiveValues, b: ObjectiveValues) =>
    a.name.trim() === b.name.trim() &&
    a.description.trim() === b.description.trim() &&
    a.objectiveType === b.objectiveType &&
    a.requirementLevel === b.requirementLevel &&
    a.completionMode === b.completionMode &&
    a.visibilityPolicy === b.visibilityPolicy &&
    a.quantity.trim() === b.quantity.trim() &&
    (a.target?.id ?? null) === (b.target?.id ?? null)

const label = (choices: QuestChoice[], value: string): string =>
    choices.find((c) => c.value === value)?.label ?? value

function stageValues(stage: QuestStageView | null, options: QuestOptions): StageValues {
    return {
        name: stage?.name ?? "",
        description: stage?.description ?? "",
        stageType: stage?.stage_type ?? options.stage_types[0]?.value ?? "sequential",
    }
}

function objectiveValues(
    objective: QuestObjectiveView | null,
    options: QuestOptions,
): ObjectiveValues {
    if (objective === null) {
        return {
            name: "",
            description: "",
            objectiveType: options.objective_types.find((t) => t.value === "other")?.value ?? "",
            ...EMPTY_OBJECTIVE_DEFAULTS,
            quantity: "",
            target: null,
        }
    }
    return {
        name: objective.name,
        description: objective.description ?? "",
        objectiveType: objective.objective_type,
        requirementLevel: objective.requirement_level,
        completionMode: objective.completion_mode,
        visibilityPolicy: objective.visibility_policy,
        quantity: objective.quantity_required === null ? "" : String(objective.quantity_required),
        target:
            objective.target === null
                ? null
                : {
                      id: objective.target.entity_id,
                      label: objective.target.name,
                      detail: statusDetail(
                          objective.target.canon_status,
                          objective.target.lifecycle_status,
                      ),
                  },
    }
}

function validateStage(values: StageValues): FieldError[] {
    const errors: FieldError[] = []
    const name = validateName(values.name)
    if (name) errors.push({ fieldId: "stage-name", message: name })
    const description = validateDescription(values.description)
    if (description) errors.push({ fieldId: "stage-description", message: description })
    return errors
}

function validateObjective(values: ObjectiveValues, options: QuestOptions): FieldError[] {
    const errors: FieldError[] = []
    const name = validateName(values.name)
    if (name) errors.push({ fieldId: "objective-name", message: name })
    const description = validateDescription(values.description)
    if (description) errors.push({ fieldId: "objective-description", message: description })
    if (values.objectiveType === "") {
        errors.push({ fieldId: "objective-type", message: "Choose a kind of objective." })
    }
    const quantity = values.quantity.trim()
    if (quantity !== "") {
        const max = options.limits.quantity_max
        const number = Number(quantity)
        if (!/^\d+$/.test(quantity) || number < 1 || number > max) {
            errors.push({
                fieldId: "objective-quantity",
                message: `Quantity must be a whole number from 1 to ${max.toLocaleString("en-US")}.`,
            })
        }
    }
    return errors
}

interface QuestEditorProps {
    campaignId: string
    view: QuestAuthoringView
    options: QuestOptions
    refreshing: boolean
    refetch: () => Promise<void>
}

export function QuestEditor({ campaignId, view, options, refreshing, refetch }: QuestEditorProps) {
    const navigate = useNavigate()
    const announce = useAnnounce()
    const { reload } = useSession()
    const editable = view.available_actions.includes("update")
    const structureLocked = view.has_progress
    const can = (action: string) => view.available_actions.includes(action)

    // --- details --------------------------------------------------------------------------------
    // `sync` is the server state the details form was last in agreement with. Its
    // version advances with every child command only while the server's name and
    // summary still match it, so an unrelated change never makes a details save
    // stale, while a real concurrent rename still does.
    const [sync, setSync] = useState({
        name: view.name,
        summary: view.summary ?? "",
        version: view.row_version,
    })
    const [details, setDetails] = useState<DetailsValues>({
        name: view.name,
        summary: view.summary ?? "",
    })
    const [keptDetails, setKeptDetails] = useState<DetailsValues | null>(null)
    const [resyncing, setResyncing] = useState(false)
    const serverDetailsMatchSync =
        view.name === sync.name && (view.summary ?? "") === sync.summary
    if (serverDetailsMatchSync && sync.version !== view.row_version) {
        setSync({ ...sync, version: view.row_version })
    }
    if (resyncing && !refreshing) {
        setResyncing(false)
        setSync({ name: view.name, summary: view.summary ?? "", version: view.row_version })
        setDetails({ name: view.name, summary: view.summary ?? "" })
    }
    const detailsDirty =
        details.name.trim() !== sync.name.trim() || details.summary.trim() !== sync.summary.trim()

    // --- panels, removal, and the single command mutation --------------------------------------
    const [panel, setPanel] = useState<Panel | null>(null)
    const [removal, setRemoval] = useState<Removal | null>(null)
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    // Presentation only: which stages the author expanded (all start collapsed),
    // and the drag in progress. Neither is persisted or sent to the server.
    const [opened, setOpened] = useState<ReadonlySet<string>>(new Set())
    const allOpen =
        view.stages.length > 0 &&
        view.stages.every(
            (s) =>
                opened.has(s.quest_stage_id) ||
                (panel !== null && panel.stageId === s.quest_stage_id),
        )
    const [drag, setDrag] = useState<{
        id: string
        overId: string | null
        after: boolean
    } | null>(null)
    const pending = useRef<{ message: string; after: () => void; focusId: string | null } | null>(
        null,
    )

    const mutation = useAuthoringMutation<QuestCommand, QuestAuthoringView>({
        scopeKey: `quest:${view.quest_id}`,
        request: (command, ctx) => runQuestCommand(campaignId, view.quest_id, command, ctx),
        onSuccess: async () => {
            const done = pending.current
            pending.current = null
            await refetch()
            done?.after()
            if (done?.message) announce(done.message)
            if (done?.focusId) {
                const id = done.focusId
                window.setTimeout(() => document.getElementById(id)?.focus(), 0)
            }
        },
    })
    const busy = mutation.status.kind === "pending"
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const serverField = error ? fieldForErrorCode(error.code) : null
    const panelDirty =
        panel === null
            ? false
            : panel.kind === "stage"
              ? !sameStage(panel.values, panel.initial)
              : !sameObjective(panel.values, panel.initial)
    const guard = useUnsavedChangesGuard(detailsDirty || panelDirty)

    function send(
        command: QuestCommand,
        message: string,
        after: () => void = () => {},
        focusId: string | null = null,
    ) {
        pending.current = { message, after, focusId }
        mutation.submit(command)
    }

    function closePanel() {
        setPanel(null)
        setErrors([])
        mutation.reset()
    }

    function openPanel(next: Panel) {
        setErrors([])
        mutation.reset()
        setPanel(next)
    }

    const loadLatest = () => {
        mutation.reset()
        void refetch()
    }

    const serverErrors: FieldError[] =
        serverField !== null && error?.code
            ? [{ fieldId: serverField, message: ERROR_CODE_MESSAGE[error.code] ?? "Check this field." }]
            : []
    const shownErrors = [...errors, ...serverErrors]
    const errorFor = (id: string) => shownErrors.find((e) => e.fieldId === id)?.message ?? null

    // --- details actions ------------------------------------------------------------------------
    function saveDetails() {
        const found: FieldError[] = []
        const name = validateName(details.name)
        if (name) found.push({ fieldId: "quest-name", message: name })
        const summary = validateDescription(details.summary)
        if (summary) found.push({ fieldId: "quest-summary", message: summary })
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length > 0) return
        const body = {
            expected_row_version: sync.version,
            name: details.name.trim(),
            summary: details.summary.trim() === "" ? null : details.summary.trim(),
        }
        send({ op: "update_quest", body }, "Quest details saved", () => {
            setSync({ name: body.name, summary: body.summary ?? "", version: sync.version })
            setKeptDetails(null)
        })
    }

    // --- stage and objective actions ------------------------------------------------------------
    function saveStage() {
        if (panel?.kind !== "stage") return
        const found = validateStage(panel.values)
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length > 0) return
        const body: StageBody = {
            expected_row_version: view.row_version,
            name: panel.values.name.trim(),
            description: panel.values.description.trim() === "" ? null : panel.values.description.trim(),
            stage_type: panel.values.stageType,
        }
        const stageId = panel.stageId
        send(
            stageId === null ? { op: "add_stage", body } : { op: "update_stage", stageId, body },
            stageId === null ? "Stage added" : "Stage saved",
            closePanel,
            stageId === null ? "add-stage" : `stage-${stageId}`,
        )
    }

    function saveObjective() {
        if (panel?.kind !== "objective") return
        const found = validateObjective(panel.values, options)
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length > 0) return
        const v = panel.values
        const body: ObjectiveBody = {
            expected_row_version: view.row_version,
            name: v.name.trim(),
            description: v.description.trim() === "" ? null : v.description.trim(),
            objective_type: v.objectiveType,
            requirement_level: v.requirementLevel,
            completion_mode: v.completionMode,
            visibility_policy: v.visibilityPolicy,
            quantity_required: v.quantity.trim() === "" ? null : Number(v.quantity.trim()),
            target_entity_id: v.target?.id ?? null,
        }
        const { stageId, objectiveId } = panel
        send(
            objectiveId === null
                ? { op: "add_objective", stageId, body }
                : { op: "update_objective", stageId, objectiveId, body },
            objectiveId === null ? "Objective added" : "Objective saved",
            closePanel,
            objectiveId === null ? `add-objective-${stageId}` : `objective-${objectiveId}`,
        )
    }

    // One reorder path for the side buttons and for drag and drop: the full new
    // stage order goes to the server with the loaded row version, and the page
    // shows whatever order the authoritative refetch returns. Nothing is
    // reordered optimistically, so a failure leaves the server's order on screen.
    function reorder(ids: string[] | null, message: string, focusId: string) {
        if (ids === null || busy) return
        send(
            { op: "reorder_stages", expected_row_version: view.row_version, stage_ids: ids },
            message,
            () => {},
            focusId,
        )
    }

    function move(index: number, delta: -1 | 1) {
        const ids = view.stages.map((s) => s.quest_stage_id)
        reorder(
            steppedStageIds(ids, index, delta),
            delta < 0 ? "Stage moved up" : "Stage moved down",
            `stage-${ids[index]!}`,
        )
    }

    function dropStage(dragId: string, targetId: string, after: boolean) {
        const ids = view.stages.map((s) => s.quest_stage_id)
        reorder(reorderedStageIds(ids, dragId, targetId, after), "Stage moved", `stage-${dragId}`)
    }

    function confirmRemoval() {
        if (removal === null) return
        const done = () => setRemoval(null)
        if (removal.kind === "stage") {
            send(
                {
                    op: "remove_stage",
                    stageId: removal.stage.quest_stage_id,
                    expected_row_version: view.row_version,
                },
                "Stage removed",
                done,
                "add-stage",
            )
        } else {
            send(
                {
                    op: "remove_objective",
                    stageId: removal.stage.quest_stage_id,
                    objectiveId: removal.objective.quest_objective_id,
                    expected_row_version: view.row_version,
                },
                "Objective removed",
                done,
                `add-objective-${removal.stage.quest_stage_id}`,
            )
        }
    }

    async function searchTargets(query: string, signal: AbortSignal): Promise<ReferenceOption[]> {
        const page = await fetchQuestTargetOptions(campaignId, query, signal)
        return page.items.map((item) => ({
            id: item.entity_id,
            label: item.name,
            detail: `${item.kind.replace(/_/g, " ")}, ${statusDetail(item.canon_status, "active")}`,
        }))
    }

    const topError =
        error === null ? null : error.kind === "stale" ? (
            <StaleWriteNotice
                loading={refreshing}
                onLoadLatest={() => {
                    // Keep everything typed: panels hold their own values; the details
                    // form is re-synchronized with a copy of the user's edits kept.
                    if (detailsDirty) {
                        setKeptDetails(details)
                        setResyncing(true)
                    }
                    loadLatest()
                }}
                yourChanges={
                    panel !== null || detailsDirty ? (
                        <p>The values you entered stay in the form below.</p>
                    ) : undefined
                }
            />
        ) : serverField === null && removal === null ? (
            <MutationStatusMessage
                error={error}
                onRetry={mutation.retry}
                onCheckSession={reload}
            />
        ) : null

    return (
        <>
            {structureLocked ? (
                <p className="authoring-message authoring-message--warning" role="note">
                    This quest already has progress recorded in a timeline, so stages cannot be
                    removed or reordered and objectives cannot be removed or have their kind,
                    requirement, completion, quantity, or target changed. Wording and visibility can
                    still be edited, and stages and objectives can be added. To restructure the
                    quest, create a replacement and supersede this one.
                </p>
            ) : null}
            {!editable ? (
                <p className="authoring-message authoring-message--warning" role="note">
                    This quest cannot be edited right now
                    {view.blocked_actions.find((b) => b.action === "update")
                        ? ` (${view.blocked_actions.find((b) => b.action === "update")!.reason.replace(/_/g, " ")})`
                        : ""}
                    . Return it to draft first.
                </p>
            ) : null}
            {topError}

            {keptDetails !== null ? (
                <section
                    aria-label="Your unsaved changes"
                    className="authoring-message authoring-message--warning"
                >
                    <div>
                        <h2>Your unsaved changes</h2>
                        <p>The details below now show the latest version. You had entered:</p>
                        <dl className="authoring-fact-list">
                            <dt>Name</dt>
                            <dd>{keptDetails.name}</dd>
                            <dt>Summary</dt>
                            <dd>{keptDetails.summary || "(empty)"}</dd>
                        </dl>
                        <button
                            type="button"
                            className="authoring-button"
                            onClick={() => {
                                setDetails(keptDetails)
                                setKeptDetails(null)
                            }}
                        >
                            Re-apply my changes
                        </button>
                    </div>
                </section>
            ) : null}

            <section className="authoring-section" aria-labelledby="quest-details-heading">
                <h2 id="quest-details-heading">Details</h2>
                <AuthoringForm label="Quest details" onSubmit={saveDetails}>
                    {panel === null ? <ErrorSummary errors={shownErrors} attempt={attempt} /> : null}
                    <TextField
                        id="quest-name"
                        label="Name"
                        value={details.name}
                        onChange={(name) => setDetails({ ...details, name })}
                        required
                        maxLength={NAME_MAX}
                        disabled={!editable}
                        error={errorFor("quest-name")}
                    />
                    <TextAreaField
                        id="quest-summary"
                        label="Summary"
                        value={details.summary}
                        onChange={(summary) => setDetails({ ...details, summary })}
                        maxLength={DESCRIPTION_MAX}
                        disabled={!editable}
                        error={errorFor("quest-summary")}
                    />
                    {editable ? (
                        <FormActions
                            pending={busy}
                            saveLabel="Save details"
                            onCancel={() =>
                                setDetails({ name: sync.name, summary: sync.summary })
                            }
                            cancelLabel="Reset"
                        />
                    ) : null}
                </AuthoringForm>
            </section>

            <section className="authoring-section" aria-labelledby="quest-stages-heading">
                <h2 id="quest-stages-heading">Stages</h2>
                {view.stages.length === 0 ? (
                    <p className="authoring-note">
                        This quest has no stages yet. A quest needs at least one stage with an
                        objective before it can be published.
                    </p>
                ) : (
                    <>
                    <p>
                        <button
                            type="button"
                            className="authoring-button"
                            onClick={() =>
                                setOpened(allOpen ? new Set() : new Set(view.stages.map((s) => s.quest_stage_id)))
                            }
                        >
                            {allOpen ? "Collapse all" : "Expand all"}
                        </button>
                    </p>
                    <ol className="quest-stage-list">
                        {view.stages.map((stage, index) => {
                            const stageId = stage.quest_stage_id
                            const reorderable = editable && can("reorder_stages")
                            // A stage holding an open form (and with it any validation or
                            // stale-write notice) is never collapsed out from under the author.
                            const hasPanel = panel !== null && panel.stageId === stageId
                            const expanded = hasPanel || opened.has(stageId)
                            const bodyId = `stage-body-${stageId}`
                            const requiredCount = stage.objectives.filter(
                                (o) => o.requirement_level === "required",
                            ).length
                            const total = stage.objectives.length
                            const wouldDrop =
                                drag !== null &&
                                drag.overId === stageId &&
                                reorderedStageIds(
                                    view.stages.map((s) => s.quest_stage_id),
                                    drag.id,
                                    stageId,
                                    drag.after,
                                ) !== null
                            const rowClass = [
                                "quest-stage-row",
                                reorderable ? "" : "quest-stage-row--static",
                                drag?.id === stageId ? "quest-stage-row--dragging" : "",
                                wouldDrop
                                    ? drag!.after
                                        ? "quest-stage-row--drop-after"
                                        : "quest-stage-row--drop-before"
                                    : "",
                            ]
                                .filter(Boolean)
                                .join(" ")
                            return (
                                <li
                                    key={stageId}
                                    className={rowClass}
                                    onDragOver={(e) => {
                                        if (drag === null || drag.id === stageId) return
                                        e.preventDefault()
                                        const rect = e.currentTarget.getBoundingClientRect()
                                        const after = e.clientY >= rect.top + rect.height / 2
                                        if (drag.overId !== stageId || drag.after !== after) {
                                            setDrag({ ...drag, overId: stageId, after })
                                        }
                                    }}
                                    onDrop={(e) => {
                                        if (drag === null) return
                                        e.preventDefault()
                                        const { id, after } = drag
                                        setDrag(null)
                                        dropStage(id, stageId, after)
                                    }}
                                >
                                    <div className="quest-stage-card">
                                        <div
                                            className="quest-stage-card__header"
                                            draggable={reorderable && !busy}
                                            onDragStart={(e) => {
                                                e.dataTransfer.effectAllowed = "move"
                                                e.dataTransfer.setData("text/plain", "")
                                                const row = e.currentTarget.closest("li")
                                                if (row) e.dataTransfer.setDragImage(row, 16, 16)
                                                setDrag({ id: stageId, overId: null, after: false })
                                            }}
                                            onDragEnd={() => setDrag(null)}
                                        >
                                            {reorderable ? (
                                                <span
                                                    className="quest-stage-card__handle"
                                                    aria-hidden="true"
                                                    title="Drag to reorder"
                                                >
                                                    ⠿
                                                </span>
                                            ) : null}
                                            <h3 className="quest-stage-card__title">
                                                <button
                                                    type="button"
                                                    id={`stage-${stageId}`}
                                                    className="quest-stage-card__toggle"
                                                    aria-expanded={expanded}
                                                    aria-controls={bodyId}
                                                    onClick={() => {
                                                        if (hasPanel) return
                                                        setOpened((prev) => {
                                                            const next = new Set(prev)
                                                            if (next.has(stageId)) next.delete(stageId)
                                                            else next.add(stageId)
                                                            return next
                                                        })
                                                    }}
                                                >
                                                    <span className="quest-stage-card__name">
                                                        <span className="quest-stage-card__number">
                                                            {stage.sequence_number}.
                                                        </span>{" "}
                                                        {stage.name}
                                                    </span>
                                                    <span className="quest-stage-card__summary">
                                                        {label(options.stage_types, stage.stage_type)} stage
                                                        {" · "}
                                                        {total === 0
                                                            ? "No objectives yet"
                                                            : `${total} objective${total === 1 ? "" : "s"}, ${requiredCount} required`}
                                                    </span>
                                                    <span
                                                        className="quest-stage-card__chevron"
                                                        aria-hidden="true"
                                                    >
                                                        {expanded ? "Collapse −" : "Expand +"}
                                                    </span>
                                                </button>
                                            </h3>
                                        </div>
                                        <div
                                            id={bodyId}
                                            className="quest-stage-card__body"
                                            hidden={!expanded}
                                        >
                                            {stage.description ? <p>{stage.description}</p> : null}
                                            {editable ? (
                                                <div className="authoring-actions">
                                                    {can("update_stage") ? (
                                                        <button
                                                            type="button"
                                                            className="authoring-button"
                                                            disabled={busy}
                                                            aria-label={`Edit stage ${stage.name}`}
                                                            onClick={() =>
                                                                openPanel({
                                                                    kind: "stage",
                                                                    stageId,
                                                                    values: stageValues(stage, options),
                                                                    initial: stageValues(stage, options),
                                                                })
                                                            }
                                                        >
                                                            Edit stage
                                                        </button>
                                                    ) : null}
                                                    {can("remove_stage") ? (
                                                        <button
                                                            type="button"
                                                            className="authoring-button authoring-button--danger"
                                                            disabled={busy}
                                                            onClick={() => setRemoval({ kind: "stage", stage })}
                                                            aria-label={`Remove stage ${stage.name}`}
                                                        >
                                                            Remove stage
                                                        </button>
                                                    ) : null}
                                                </div>
                                            ) : null}

                                    {panel?.kind === "stage" && panel.stageId === stage.quest_stage_id ? (
                                        <StagePanel
                                            panel={panel}
                                            options={options}
                                            structureLocked={structureLocked}
                                            onChange={(values) => setPanel({ ...panel, values })}
                                            errors={shownErrors}
                                            attempt={attempt}
                                            pending={busy}
                                            onSave={saveStage}
                                            onCancel={closePanel}
                                        />
                                    ) : null}

                                    <h4>Objectives</h4>
                                    {stage.objectives.length === 0 ? (
                                        <p className="authoring-note">No objectives in this stage.</p>
                                    ) : (
                                        <ul className="quest-objective-list">
                                            {stage.objectives.map((objective) => (
                                                <li
                                                    key={objective.quest_objective_id}
                                                    className="quest-objective-list__item"
                                                >
                                                    <div>
                                                        <h5
                                                            id={`objective-${objective.quest_objective_id}`}
                                                            tabIndex={-1}
                                                        >
                                                            {objective.name}
                                                        </h5>
                                                        <p className="authoring-field__hint">
                                                            {objective.objective_type_label} ·{" "}
                                                            <strong>
                                                                {label(
                                                                    options.requirement_levels,
                                                                    objective.requirement_level,
                                                                )}
                                                            </strong>{" "}
                                                            ·{" "}
                                                            {label(
                                                                options.completion_modes,
                                                                objective.completion_mode,
                                                            )}{" "}
                                                            ·{" "}
                                                            {label(
                                                                options.visibility_policies,
                                                                objective.visibility_policy,
                                                            )}
                                                            {objective.quantity_required !== null
                                                                ? ` · Quantity ${objective.quantity_required}`
                                                                : ""}
                                                        </p>
                                                        {objective.target ? (
                                                            <p>
                                                                Target: {objective.target.name}{" "}
                                                                <span className="authoring-field__hint">
                                                                    (
                                                                    {statusDetail(
                                                                        objective.target.canon_status,
                                                                        objective.target.lifecycle_status,
                                                                    )}
                                                                    )
                                                                </span>
                                                            </p>
                                                        ) : null}
                                                        {objective.description ? (
                                                            <p>{objective.description}</p>
                                                        ) : null}
                                                        {editable ? (
                                                            <div className="authoring-actions">
                                                                {can("update_objective") ? (
                                                                    <button
                                                                        type="button"
                                                                        className="authoring-button"
                                                                        disabled={busy}
                                                                        aria-label={`Edit objective ${objective.name}`}
                                                                        onClick={() =>
                                                                            openPanel({
                                                                                kind: "objective",
                                                                                stageId: stage.quest_stage_id,
                                                                                objectiveId:
                                                                                    objective.quest_objective_id,
                                                                                values: objectiveValues(
                                                                                    objective,
                                                                                    options,
                                                                                ),
                                                                                initial: objectiveValues(
                                                                                    objective,
                                                                                    options,
                                                                                ),
                                                                            })
                                                                        }
                                                                    >
                                                                        Edit objective
                                                                    </button>
                                                                ) : null}
                                                                {can("remove_objective") ? (
                                                                    <button
                                                                        type="button"
                                                                        className="authoring-button authoring-button--danger"
                                                                        disabled={busy}
                                                                        aria-label={`Remove objective ${objective.name}`}
                                                                        onClick={() =>
                                                                            setRemoval({
                                                                                kind: "objective",
                                                                                stage,
                                                                                objective,
                                                                            })
                                                                        }
                                                                    >
                                                                        Remove objective
                                                                    </button>
                                                                ) : null}
                                                            </div>
                                                        ) : null}
                                                        {panel?.kind === "objective" &&
                                                        panel.objectiveId ===
                                                            objective.quest_objective_id ? (
                                                            <ObjectivePanel
                                                                panel={panel}
                                                                options={options}
                                                                structureLocked={structureLocked}
                                                                search={searchTargets}
                                                                onChange={(values) =>
                                                                    setPanel({ ...panel, values })
                                                                }
                                                                errors={shownErrors}
                                                                attempt={attempt}
                                                                pending={busy}
                                                                onSave={saveObjective}
                                                                onCancel={closePanel}
                                                            />
                                                        ) : null}
                                                    </div>
                                                </li>
                                            ))}
                                        </ul>
                                    )}
                                    {editable && can("add_objective") ? (
                                        <p>
                                            <button
                                                type="button"
                                                id={`add-objective-${stage.quest_stage_id}`}
                                                className="authoring-button"
                                                aria-label={`Add objective to ${stage.name}`}
                                                disabled={busy || stage.objectives.length >= options.limits.max_objectives_per_stage}
                                                onClick={() =>
                                                    openPanel({
                                                        kind: "objective",
                                                        stageId: stage.quest_stage_id,
                                                        objectiveId: null,
                                                        values: objectiveValues(null, options),
                                                        initial: objectiveValues(null, options),
                                                    })
                                                }
                                            >
                                                Add objective
                                            </button>
                                        </p>
                                    ) : null}
                                    {panel?.kind === "objective" &&
                                    panel.objectiveId === null &&
                                    panel.stageId === stage.quest_stage_id ? (
                                        <ObjectivePanel
                                            panel={panel}
                                            options={options}
                                            structureLocked={false}
                                            search={searchTargets}
                                            onChange={(values) => setPanel({ ...panel, values })}
                                            errors={shownErrors}
                                            attempt={attempt}
                                            pending={busy}
                                            onSave={saveObjective}
                                            onCancel={closePanel}
                                        />
                                    ) : null}
                                        </div>
                                    </div>
                                    {reorderable ? (
                                        <div className="quest-stage-row__moves">
                                            <button
                                                type="button"
                                                className="authoring-button quest-stage-row__move"
                                                disabled={busy || index === 0}
                                                onClick={() => move(index, -1)}
                                                aria-label={`Move up ${stage.name}`}
                                            >
                                                <span aria-hidden="true">▲</span>
                                            </button>
                                            <button
                                                type="button"
                                                className="authoring-button quest-stage-row__move"
                                                disabled={busy || index === view.stages.length - 1}
                                                onClick={() => move(index, 1)}
                                                aria-label={`Move down ${stage.name}`}
                                            >
                                                <span aria-hidden="true">▼</span>
                                            </button>
                                        </div>
                                    ) : null}
                                </li>
                            )
                        })}
                    </ol>
                    </>
                )}
                {editable && can("add_stage") ? (
                    <>
                        {panel?.kind === "stage" && panel.stageId === null ? (
                            <StagePanel
                                panel={panel}
                                options={options}
                                structureLocked={false}
                                onChange={(values) => setPanel({ ...panel, values })}
                                errors={shownErrors}
                                attempt={attempt}
                                pending={busy}
                                onSave={saveStage}
                                onCancel={closePanel}
                            />
                        ) : (
                            <p>
                                <button
                                    type="button"
                                    id="add-stage"
                                    className="authoring-button authoring-button--primary"
                                    disabled={busy || view.stages.length >= options.limits.max_stages}
                                    onClick={() =>
                                        openPanel({
                                            kind: "stage",
                                            stageId: null,
                                            values: stageValues(null, options),
                                            initial: stageValues(null, options),
                                        })
                                    }
                                >
                                    Add stage
                                </button>
                            </p>
                        )}
                    </>
                ) : null}
            </section>

            <p>
                <button
                    type="button"
                    className="authoring-button"
                    onClick={() => void navigate(`/app/${encodeURIComponent(campaignId)}/quests`)}
                >
                    Back to quests
                </button>
            </p>

            <ConfirmDialog
                open={removal !== null}
                title={removal?.kind === "stage" ? "Remove this stage?" : "Remove this objective?"}
                description={
                    removal?.kind === "stage"
                        ? `"${removal.stage.name}" and its ${removal.stage.objectives.length} objective${removal.stage.objectives.length === 1 ? "" : "s"} will be permanently removed. This cannot be undone.`
                        : removal?.kind === "objective"
                          ? `"${removal.objective.name}" will be permanently removed. This cannot be undone.`
                          : ""
                }
                confirmLabel={removal?.kind === "stage" ? "Remove stage" : "Remove objective"}
                cancelLabel="Keep it"
                pending={busy}
                error={
                    removal !== null && error !== null && error.kind !== "stale" ? (
                        <MutationStatusMessage
                            error={error}
                            onRetry={mutation.retry}
                            onCheckSession={reload}
                        />
                    ) : error !== null && error.kind === "stale" && removal !== null ? (
                        <StaleWriteNotice loading={refreshing} onLoadLatest={() => { setRemoval(null); loadLatest() }} />
                    ) : undefined
                }
                onConfirm={confirmRemoval}
                onCancel={() => {
                    setRemoval(null)
                    mutation.reset()
                }}
            />
            <ConfirmDialog
                open={guard.blocked}
                title="Discard unsaved changes?"
                description="You have edits to this quest that have not been saved."
                confirmLabel="Discard changes"
                cancelLabel="Keep editing"
                onConfirm={guard.discard}
                onCancel={guard.stay}
            />
        </>
    )
}

// --- inline panels ----------------------------------------------------------------------------

interface StagePanelProps {
    panel: Extract<Panel, { kind: "stage" }>
    options: QuestOptions
    structureLocked: boolean
    onChange: (values: StageValues) => void
    errors: FieldError[]
    attempt: number
    pending: boolean
    onSave: () => void
    onCancel: () => void
}

function StagePanel({
    panel,
    options,
    structureLocked,
    onChange,
    errors,
    attempt,
    pending,
    onSave,
    onCancel,
}: StagePanelProps) {
    const v = panel.values
    const errorFor = (id: string) => errors.find((e) => e.fieldId === id)?.message ?? null
    const locked = structureLocked && panel.stageId !== null
    return (
        <section className="authoring-aside" aria-label={panel.stageId === null ? "New stage" : "Edit stage"}>
            <AuthoringForm label={panel.stageId === null ? "New stage" : "Edit stage"} onSubmit={onSave}>
                <ErrorSummary errors={errors} attempt={attempt} />
                <TextField
                    id="stage-name"
                    label="Stage name"
                    value={v.name}
                    onChange={(name) => onChange({ ...v, name })}
                    required
                    maxLength={NAME_MAX}
                    error={errorFor("stage-name")}
                />
                <TextAreaField
                    id="stage-description"
                    label="Stage description"
                    value={v.description}
                    onChange={(description) => onChange({ ...v, description })}
                    maxLength={DESCRIPTION_MAX}
                    error={errorFor("stage-description")}
                />
                <SelectField
                    id="stage-type"
                    label="Stage type"
                    value={v.stageType}
                    options={options.stage_types}
                    disabled={locked}
                    hint={locked ? "Locked: this quest has recorded progress." : undefined}
                    onChange={(stageType) => onChange({ ...v, stageType })}
                />
                <FormActions
                    pending={pending}
                    saveLabel={panel.stageId === null ? "Add stage" : "Save stage"}
                    onCancel={onCancel}
                />
            </AuthoringForm>
        </section>
    )
}

interface ObjectivePanelProps {
    panel: Extract<Panel, { kind: "objective" }>
    options: QuestOptions
    structureLocked: boolean
    search: (query: string, signal: AbortSignal) => Promise<ReferenceOption[]>
    onChange: (values: ObjectiveValues) => void
    errors: FieldError[]
    attempt: number
    pending: boolean
    onSave: () => void
    onCancel: () => void
}

function ObjectivePanel({
    panel,
    options,
    structureLocked,
    search,
    onChange,
    errors,
    attempt,
    pending,
    onSave,
    onCancel,
}: ObjectivePanelProps) {
    const v = panel.values
    const errorFor = (id: string) => errors.find((e) => e.fieldId === id)?.message ?? null
    const locked = structureLocked && panel.objectiveId !== null
    const lockHint = locked ? "Locked: this quest has recorded progress." : undefined
    const title = panel.objectiveId === null ? "New objective" : "Edit objective"
    return (
        <section className="authoring-aside" aria-label={title}>
            <AuthoringForm label={title} onSubmit={onSave}>
                <ErrorSummary errors={errors} attempt={attempt} />
                <TextField
                    id="objective-name"
                    label="Objective name"
                    value={v.name}
                    onChange={(name) => onChange({ ...v, name })}
                    required
                    maxLength={NAME_MAX}
                    error={errorFor("objective-name")}
                />
                <TextAreaField
                    id="objective-description"
                    label="Objective description"
                    value={v.description}
                    onChange={(description) => onChange({ ...v, description })}
                    maxLength={DESCRIPTION_MAX}
                    error={errorFor("objective-description")}
                />
                <SelectField
                    id="objective-type"
                    label="Kind of objective"
                    value={v.objectiveType}
                    options={options.objective_types}
                    disabled={locked}
                    hint={lockHint}
                    required
                    error={errorFor("objective-type")}
                    onChange={(objectiveType) => onChange({ ...v, objectiveType })}
                />
                <SelectField
                    id="objective-requirement"
                    label="Requirement"
                    value={v.requirementLevel}
                    options={options.requirement_levels}
                    disabled={locked}
                    hint={lockHint}
                    onChange={(requirementLevel) => onChange({ ...v, requirementLevel })}
                />
                <SelectField
                    id="objective-completion"
                    label="Completion"
                    value={v.completionMode}
                    options={options.completion_modes}
                    disabled={locked}
                    hint={lockHint}
                    onChange={(completionMode) => onChange({ ...v, completionMode })}
                />
                <SelectField
                    id="objective-visibility"
                    label="Visibility"
                    value={v.visibilityPolicy}
                    options={options.visibility_policies}
                    onChange={(visibilityPolicy) => onChange({ ...v, visibilityPolicy })}
                />
                <TextField
                    id="objective-quantity"
                    label="Quantity required"
                    hint={lockHint ?? "A whole number. Leave empty if the objective is not counted."}
                    value={v.quantity}
                    onChange={(quantity) => onChange({ ...v, quantity })}
                    disabled={locked}
                    error={errorFor("objective-quantity")}
                />
                <ReferenceCombobox
                    id="objective-target"
                    label="Target"
                    hint={lockHint ?? "The place, organization, character, or other record this objective concerns."}
                    value={v.target}
                    onChange={(target) => onChange({ ...v, target })}
                    search={search}
                    disabled={locked}
                    error={errorFor("objective-target")}
                    placeholder="Search records"
                />
                <FormActions
                    pending={pending}
                    saveLabel={panel.objectiveId === null ? "Add objective" : "Save objective"}
                    onCancel={onCancel}
                />
            </AuthoringForm>
        </section>
    )
}
