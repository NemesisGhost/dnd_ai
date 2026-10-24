import { useRef, useState } from "react"
import { Link } from "react-router"
import { runQuestCommand } from "../../api/questAuthoring"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import type { QuestReceipt } from "../../types/contentAuthoring"
import type { QuestAuthoringView, QuestCommand, QuestOptions } from "../../types/questAuthoring"
import {
    DESCRIPTION_MAX,
    NAME_MAX,
    fieldForErrorCode,
    ERROR_CODE_MESSAGE,
    validateDescription,
    validateName,
} from "../../utils/authoringValidation"
import { useAnnounce } from "../authoring/announcer"
import { TextAreaField, TextField } from "../authoring/fields"
import { AuthoringForm, ErrorSummary, FormActions, MutationStatusMessage, StaleWriteNotice } from "../authoring/feedback"
import type { FieldError } from "../authoring/feedback"
import { DraftConflict } from "./DraftConflict"
import { questEditBlockedText } from "./questPhases"
import { useQuestCommand } from "./useQuestCommand"
import { useSyncedDraft } from "./useSyncedDraft"
import { useUnsavedReport } from "./useUnsavedReport"
import type { ReportUnsaved } from "./useUnsavedReport"
import "../authoring/authoring.css"

interface Props {
    campaignId: string
    view: QuestAuthoringView
    options: QuestOptions
    refreshing: boolean
    // Reads the quest again (and whatever else depends on its version).
    refetch: () => Promise<unknown>
    onUnsaved: ReportUnsaved
    // The Publication section and the router state to carry, for the line that explains why the
    // quest cannot be edited.
    publicationHref: string
    linkState?: object
}

interface DetailsValues {
    name: string
    summary: string
}

// The quest's own words: its name and summary, and the planning notes only editors see. They save
// separately, and neither is part of the stages, the completion design or the lifecycle. When the
// definition cannot be changed they are text, with one line saying why.
export function QuestDetailsSection(props: Props) {
    const { view } = props
    const editable = view.available_actions.includes("update")
    return (
        <div className="section-stack">
            {!editable ? (
                <p className="authoring-message authoring-message--warning" role="note">
                    {questEditBlockedText(view)}{" "}
                    <Link to={props.publicationHref} state={props.linkState}>
                        See Publication
                    </Link>
                </p>
            ) : null}
            <DetailsForm {...props} editable={editable} />
            <NotesForm {...props} editable={editable} />
        </div>
    )
}

function DetailsForm({
    campaignId,
    view,
    refreshing,
    refetch,
    onUnsaved,
    editable,
}: Props & { editable: boolean }) {
    const { reload } = useSession()
    const announce = useAnnounce()
    // `sync` is the server state the details form was last in agreement with. Its version advances
    // with every other command only while the server's name and summary still match it, so an
    // unrelated change never makes a details save stale, while a real concurrent rename still does.
    const [sync, setSync] = useState({ name: view.name, summary: view.summary ?? "", version: view.row_version })
    const [details, setDetails] = useState<DetailsValues>({ name: view.name, summary: view.summary ?? "" })
    const [kept, setKept] = useState<DetailsValues | null>(null)
    const [resyncing, setResyncing] = useState(false)
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    if (view.name === sync.name && (view.summary ?? "") === sync.summary && sync.version !== view.row_version) {
        setSync({ ...sync, version: view.row_version })
    }
    if (resyncing && !refreshing) {
        setResyncing(false)
        setSync({ name: view.name, summary: view.summary ?? "", version: view.row_version })
        setDetails({ name: view.name, summary: view.summary ?? "" })
    }
    const dirty = details.name.trim() !== sync.name.trim() || details.summary.trim() !== sync.summary.trim()
    useUnsavedReport(onUnsaved, "details", dirty ? ["quest details"] : [])

    // What the submitted save carried, adopted as the synced state once it succeeded.
    const submitted = useRef<DetailsValues | null>(null)
    const mutation = useAuthoringMutation<QuestCommand, QuestReceipt>({
        scopeKey: `quest-details:${view.quest_id}`,
        request: (command, ctx) => runQuestCommand(campaignId, view.quest_id, command, ctx),
        onSuccess: async () => {
            await refetch()
            const saved = submitted.current
            submitted.current = null
            if (saved !== null) setSync((current) => ({ ...saved, version: current.version }))
            announce("Quest details saved")
        },
    })
    const busy = mutation.status.kind === "pending"
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const serverField = error ? fieldForErrorCode(error.code) : null
    const serverErrors: FieldError[] =
        serverField !== null && error?.code
            ? [{ fieldId: serverField, message: ERROR_CODE_MESSAGE[error.code] ?? "Check this field." }]
            : []
    const shown = [...errors, ...serverErrors]
    const errorFor = (id: string) => shown.find((e) => e.fieldId === id)?.message ?? null

    function save() {
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
        submitted.current = { name: body.name, summary: body.summary ?? "" }
        setKept(null)
        mutation.submit({ op: "update_quest", body })
    }

    if (!editable) {
        return (
            <dl className="authoring-fact-list">
                <dt>Name</dt>
                <dd>{view.name}</dd>
                <dt>Summary</dt>
                <dd>{view.summary ?? "No summary."}</dd>
            </dl>
        )
    }
    return (
        <>
            {error?.kind === "stale" ? (
                <StaleWriteNotice
                    loading={refreshing}
                    onLoadLatest={() => {
                        // Keep everything typed: the form is re-synchronised with the latest
                        // version and a copy of the person's edits stays visible.
                        if (dirty) {
                            setKept(details)
                            setResyncing(true)
                        }
                        mutation.reset()
                        void refetch()
                    }}
                    yourChanges={dirty ? <p>The values you entered stay in the form below.</p> : undefined}
                />
            ) : serverField === null && error !== null ? (
                <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
            ) : null}
            {kept !== null ? (
                <section aria-label="Your unsaved changes" className="authoring-message authoring-message--warning">
                    <div>
                        <h3>Your unsaved changes</h3>
                        <p>The details below now show the latest version. You had entered:</p>
                        <dl className="authoring-fact-list">
                            <dt>Name</dt>
                            <dd>{kept.name}</dd>
                            <dt>Summary</dt>
                            <dd>{kept.summary || "(empty)"}</dd>
                        </dl>
                        <button
                            type="button"
                            className="authoring-button"
                            onClick={() => {
                                setDetails(kept)
                                setKept(null)
                            }}
                        >
                            Re-apply my changes
                        </button>
                    </div>
                </section>
            ) : null}
            <AuthoringForm label="Quest details" onSubmit={save}>
                <ErrorSummary errors={shown} attempt={attempt} />
                <TextField
                    id="quest-name"
                    label="Name"
                    value={details.name}
                    onChange={(name) => setDetails({ ...details, name })}
                    required
                    maxLength={NAME_MAX}
                    error={errorFor("quest-name")}
                />
                <TextAreaField
                    id="quest-summary"
                    label="Summary"
                    value={details.summary}
                    onChange={(summary) => setDetails({ ...details, summary })}
                    maxLength={DESCRIPTION_MAX}
                    error={errorFor("quest-summary")}
                />
                <FormActions
                    pending={busy}
                    saveLabel="Save details"
                    onCancel={() => setDetails({ name: sync.name, summary: sync.summary })}
                    cancelLabel="Reset"
                />
            </AuthoringForm>
        </>
    )
}

// The planning notes: visible only to people who can edit canon, never to players. Saved with the
// server's own name and summary, so an unsaved details draft is never overwritten or sent.
function NotesForm({
    campaignId,
    view,
    options,
    refetch,
    onUnsaved,
    editable,
}: Props & { editable: boolean }) {
    const command = useQuestCommand({ campaignId, questId: view.quest_id, scope: "notes", refetch })
    const serverNotes = view.gm_notes ?? ""
    // The notes follow the saved text while untouched; a draft is kept, and if the saved notes
    // changed elsewhere meanwhile the person chooses before the next save.
    const draft = useSyncedDraft({ notes: serverNotes }, view.row_version)
    const notes = draft.values.notes
    const max = options.limits.gm_notes_max_length
    const tooLong = notes.trim().length > max
    useUnsavedReport(onUnsaved, "notes", editable && draft.dirty ? ["GM notes"] : [])

    if (!editable) {
        return view.gm_notes === null ? null : (
            <dl className="authoring-fact-list">
                <dt>GM notes</dt>
                <dd>{view.gm_notes}</dd>
            </dl>
        )
    }
    return (
        <section className="inset-group quest-notes" aria-label="GM notes">
            {command.notice}
            {draft.conflict ? (
                <DraftConflict what="The planning notes" onLatest={draft.loadLatest} onKeep={draft.keepMine} />
            ) : null}
            <form
                noValidate
                aria-label="GM notes"
                className="authoring-form"
                onSubmit={(event) => {
                    event.preventDefault()
                    if (tooLong || draft.conflict) return
                    draft.submitting({ notes: notes.trim() })
                    command.send(
                        {
                            op: "update_quest",
                            body: {
                                expected_row_version: draft.version,
                                name: view.name,
                                summary: view.summary,
                                gm_notes: notes.trim() === "" ? null : notes.trim(),
                            },
                        },
                        "GM notes saved",
                    )
                }}
            >
                <TextAreaField
                    id="quest-gm-notes"
                    label="Planning notes"
                    hint="Visible only to people who can edit canon. Never shown to players."
                    value={notes}
                    onChange={(next) => draft.setValues({ notes: next })}
                    maxLength={max}
                    error={tooLong ? `Notes must be ${max} characters or fewer.` : null}
                />
                <div className="authoring-actions">
                    <button type="submit" className="authoring-button" disabled={command.busy || tooLong || draft.conflict}>
                        Save notes
                    </button>
                </div>
            </form>
        </section>
    )
}
