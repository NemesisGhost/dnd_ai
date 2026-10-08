import { useState } from "react"
import { Link } from "react-router"
import { updateSession } from "../api/sessionAuthoring"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { useAnnounce } from "../components/authoring/announcer"
import { TextAreaField, TextField } from "../components/authoring/fields"
import {
    AuthoringForm,
    ErrorSummary,
    MutationStatusMessage,
    StaleWriteNotice,
} from "../components/authoring/feedback"
import type { FieldError } from "../components/authoring/feedback"
import { SessionLifecycleControls } from "../components/SessionLifecycleControls"
import { SortableTable } from "../components/SortableTable"
import type { SortableTableColumn } from "../components/SortableTable"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import type {
    CampaignSessionDetail,
    CampaignSessionEvent,
    SessionReceipt,
} from "../types/campaignSession"
import {
    DESCRIPTION_MAX,
    NAME_MAX,
    validateDescription,
} from "../utils/authoringValidation"
import { SESSION_ERROR_MESSAGE, fromLocalInput, toLocalInput } from "../utils/sessionForm"
import { applyDirection } from "../utils/sorting"
import type { SortDirection } from "../utils/sorting"
import "../components/authoring/authoring.css"

interface SessionDetailPageProps {
    campaignId: string
    session: CampaignSessionDetail
    // Re-fetches the canonical session in place (no loading state), resolving
    // true when fresh data was applied.
    refresh: () => Promise<boolean>
}

function compareStrings(
    a: string,
    b: string,
    direction: SortDirection,
): number {
    return applyDirection(direction, a.localeCompare(b))
}

const eventColumns: SortableTableColumn<CampaignSessionEvent>[] = [
    {
        key: "event_name",
        label: "Name",
        compare: (a, b, direction) =>
            compareStrings(a.name, b.name, direction),
        render: (event) => event.name,
    },
    {
        key: "event_type",
        label: "Type",
        compare: (a, b, direction) =>
            compareStrings(
                a.event_type_code,
                b.event_type_code,
                direction,
            ),
        render: (event) => event.event_type_code,
    },
    {
        key: "event_status",
        label: "Status",
        compare: (a, b, direction) =>
            compareStrings(
                a.event_status_code,
                b.event_status_code,
                direction,
            ),
        render: (event) => event.event_status_code,
    },
    {
        key: "event_summary",
        label: "Summary",
        render: (event) => event.summary ?? "No summary recorded",
    },
    {
        key: "event_details",
        label: "Details",
        render: (event) =>
            event.details ?? "No details recorded",
    },
]

function formatTimestamp(timestamp: string): string {
    return new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
    }).format(new Date(timestamp))
}

function renderTimestamp(timestamp: string | null) {
    return timestamp !== null ? (
        <time dateTime={timestamp}>{formatTimestamp(timestamp)}</time>
    ) : (
        "Not recorded"
    )
}

type FieldName = "title" | "scheduledFor" | "summary"
type FormValues = Record<FieldName, string>

const FIELD_IDS: Readonly<Record<FieldName, string>> = {
    title: "session-title",
    scheduledFor: "session-scheduled",
    summary: "session-summary",
}

function baselineOf(session: CampaignSessionDetail): FormValues {
    return {
        title: session.title ?? "",
        scheduledFor: toLocalInput(session.scheduled_for ?? null),
        summary: session.summary ?? "",
    }
}

function validate(values: FormValues, fields: readonly FieldName[]): FieldError[] {
    const errors: FieldError[] = []
    if (fields.includes("title") && values.title.trim().length > NAME_MAX) {
        errors.push({
            fieldId: FIELD_IDS.title,
            message: `Title must be ${NAME_MAX} characters or fewer.`,
        })
    }
    if (
        fields.includes("scheduledFor") &&
        values.scheduledFor.trim() !== "" &&
        fromLocalInput(values.scheduledFor) === null
    ) {
        errors.push({ fieldId: FIELD_IDS.scheduledFor, message: "Enter a valid date and time." })
    }
    if (fields.includes("summary")) {
        const summaryError = validateDescription(values.summary)
        if (summaryError) {
            errors.push({
                fieldId: FIELD_IDS.summary,
                message: summaryError.replace("Description", "Summary"),
            })
        }
    }
    return errors
}

interface SaveBody {
    title: string | null
    scheduled_for: string | null
    summary: string | null
}

const blankToNull = (value: string): string | null =>
    value.trim() === "" ? null : value.trim()

// Why the session's fields cannot be edited, or null when they can. Missing
// action metadata never grants editing: only an explicit "update" does.
function editBlocker(
    session: CampaignSessionDetail,
    hasCapability: boolean,
): string | null {
    if (session.status_code === "archived") {
        const restorable = hasCapability && (session.available_actions ?? []).includes("restore")
        return restorable
            ? "This session is archived, so its fields are read-only. Restore it to edit them."
            : "This session is archived, so its fields are read-only."
    }
    if (!hasCapability) {
        return "You can view this session but you do not have permission to edit it."
    }
    if (
        !(session.available_actions ?? []).includes("update") ||
        typeof session.row_version !== "number"
    ) {
        return "This session cannot be edited right now."
    }
    return null
}

export function SessionDetailPage({
    campaignId,
    session,
    refresh,
}: SessionDetailPageProps) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const hasCapability = useCampaignCapability(campaignId, "canon.edit")
    const title = session.title ?? `Session ${session.session_number}`
    const events = session.events

    const blocker = editBlocker(session, hasCapability)
    const canEdit = blocker === null
    const started = session.started_at !== null
    const scheduledEditable = canEdit && !started

    // Only the fields the person has changed are held here; everything else
    // follows the latest loaded session. A background refresh therefore never
    // overwrites typed input, and Discard simply forgets the overrides.
    const baseline = baselineOf(session)
    const [edits, setEdits] = useState<Partial<FormValues>>({})
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const [savedNotice, setSavedNotice] = useState(false)
    const [refreshFailed, setRefreshFailed] = useState(false)
    const [saved, setSaved] = useState<Partial<FormValues>>({})

    const valueOf = (field: FieldName): string => edits[field] ?? baseline[field]
    const dirtyFields = (Object.keys(edits) as FieldName[]).filter(
        (field) => edits[field] !== undefined && edits[field] !== baseline[field],
    )
    const dirty = dirtyFields.length > 0
    const guard = useUnsavedChangesGuard(dirty)
    const errorFor = (field: FieldName) =>
        errors.find((e) => e.fieldId === FIELD_IDS[field])?.message ?? null

    function setField(field: FieldName, value: string) {
        if (field === "scheduledFor" ? !scheduledEditable : !canEdit) return
        setEdits((current) => ({ ...current, [field]: value }))
        setSavedNotice(false)
    }

    function forgetSaved(submitted: Partial<FormValues>) {
        setEdits((current) => {
            const next = { ...current }
            for (const field of Object.keys(submitted) as FieldName[]) {
                if (next[field] === submitted[field]) delete next[field]
            }
            return next
        })
    }

    const mutation = useAuthoringMutation<SaveBody, SessionReceipt>({
        scopeKey: `session-detail:${campaignId}:${session.session_id}:${session.row_version ?? 0}`,
        request: (body, ctx) =>
            updateSession(
                campaignId,
                session.session_id,
                { ...body, expected_row_version: session.row_version ?? 0 },
                ctx,
            ),
        onSuccess: async () => {
            const fresh = await refresh()
            if (fresh) {
                forgetSaved(saved)
                setSaved({})
                setRefreshFailed(false)
            } else {
                setRefreshFailed(true)
            }
            setSavedNotice(true)
            announce("Session saved")
        },
    })
    const pending = mutation.status.kind === "pending"
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const specificMessage = error?.code ? (SESSION_ERROR_MESSAGE[error.code] ?? null) : null

    // Only fields the person may edit are ever sent as changes; the rest are
    // sent exactly as the server last returned them. The planned start in
    // particular is echoed verbatim (not round-tripped through the local
    // input) so a started session's unchanged value is never rejected.
    function submit() {
        if (!canEdit) return
        const editable = dirtyFields.filter((field) => field !== "scheduledFor" || scheduledEditable)
        const values: FormValues = {
            title: valueOf("title"),
            scheduledFor: valueOf("scheduledFor"),
            summary: valueOf("summary"),
        }
        const found = validate(values, editable)
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length > 0 || editable.length === 0) return
        const submitted: Partial<FormValues> = {}
        for (const field of editable) submitted[field] = values[field]
        setSaved(submitted)
        mutation.submit({
            title: editable.includes("title") ? blankToNull(values.title) : session.title,
            scheduled_for: editable.includes("scheduledFor")
                ? fromLocalInput(values.scheduledFor)
                : (session.scheduled_for ?? null),
            summary: editable.includes("summary") ? blankToNull(values.summary) : session.summary,
        })
    }

    function discard() {
        setEdits({})
        setErrors([])
        setSaved({})
        setSavedNotice(false)
        mutation.reset()
    }

    async function loadLatest() {
        await refresh()
        mutation.reset()
    }

    async function reloadAfterSave() {
        if (await refresh()) {
            forgetSaved(saved)
            setSaved({})
            setRefreshFailed(false)
        }
    }

    const startedNote = "This session has started, so its planned start cannot change."

    return (
        <section aria-labelledby="session-heading">
            <Link to=".." relative="path">
                Back to sessions
            </Link>
            <h1 id="session-heading">{title}</h1>
            <section aria-labelledby="session-overview-heading">
                <h2 id="session-overview-heading">Overview</h2>
                <dl>
                    <div>
                        <dt>Session number</dt>
                        <dd>{session.session_number}</dd>
                    </div>

                    <div>
                        <dt>Status</dt>
                        <dd>{session.status_code}</dd>
                    </div>

                    <div>
                        <dt>Start time</dt>
                        <dd>{renderTimestamp(session.started_at)}</dd>
                    </div>

                    <div>
                        <dt>End time</dt>
                        <dd>{renderTimestamp(session.ended_at)}</dd>
                    </div>
                </dl>
            </section>
            <section aria-labelledby="session-details-heading">
                <h2 id="session-details-heading">Details</h2>
                {blocker !== null ? <p className="authoring-note">{blocker}</p> : null}
                <AuthoringForm label="Session details" onSubmit={submit}>
                    <ErrorSummary errors={errors} attempt={attempt} />
                    {error?.kind === "stale" ? (
                        <StaleWriteNotice onLoadLatest={() => void loadLatest()} />
                    ) : specificMessage !== null ? (
                        <p role="alert">{specificMessage}</p>
                    ) : error !== null ? (
                        <MutationStatusMessage
                            error={error}
                            onRetry={mutation.retry}
                            onCheckSession={reload}
                        />
                    ) : null}
                    {refreshFailed ? (
                        <div role="alert">
                            <p>
                                Your changes were saved, but the latest version could not be
                                loaded.
                            </p>
                            <button
                                type="button"
                                className="authoring-button"
                                onClick={() => void reloadAfterSave()}
                            >
                                Reload session
                            </button>
                        </div>
                    ) : null}
                    {savedNotice && !refreshFailed ? <p role="status">Session saved.</p> : null}
                    <TextField
                        id={FIELD_IDS.title}
                        label="Title"
                        hint={
                            canEdit
                                ? "Optional. The session number is assigned for you."
                                : undefined
                        }
                        value={valueOf("title")}
                        onChange={(value) => setField("title", value)}
                        readOnly={!canEdit}
                        maxLength={canEdit ? NAME_MAX : undefined}
                        error={errorFor("title")}
                    />
                    <div
                        className={
                            errorFor("scheduledFor")
                                ? "authoring-field authoring-field--invalid"
                                : "authoring-field"
                        }
                    >
                        <label className="authoring-field__label" htmlFor={FIELD_IDS.scheduledFor}>
                            Planned start
                        </label>
                        {scheduledEditable || (canEdit && started) ? (
                            <p className="authoring-field__hint" id="session-scheduled-hint">
                                {started
                                    ? startedNote
                                    : "Optional. When the table plans to play, in your time zone."}
                            </p>
                        ) : null}
                        <input
                            id={FIELD_IDS.scheduledFor}
                            className="authoring-field__control"
                            type="datetime-local"
                            value={valueOf("scheduledFor")}
                            readOnly={!scheduledEditable}
                            aria-describedby={
                                scheduledEditable || (canEdit && started)
                                    ? "session-scheduled-hint"
                                    : undefined
                            }
                            aria-invalid={errorFor("scheduledFor") ? true : undefined}
                            onChange={(event) => setField("scheduledFor", event.target.value)}
                        />
                        {errorFor("scheduledFor") ? (
                            <p className="authoring-field__error">
                                <span className="visually-hidden">Error: </span>
                                {errorFor("scheduledFor")}
                            </p>
                        ) : null}
                    </div>
                    <TextAreaField
                        id={FIELD_IDS.summary}
                        label="Summary"
                        hint={
                            canEdit
                                ? "A recap or plan. Visible to everyone in the campaign."
                                : undefined
                        }
                        value={valueOf("summary")}
                        onChange={(value) => setField("summary", value)}
                        readOnly={!canEdit}
                        maxLength={canEdit ? DESCRIPTION_MAX : undefined}
                        error={errorFor("summary")}
                    />
                    {dirty ? (
                        <div className="authoring-actions">
                            <button
                                type="submit"
                                className="authoring-button authoring-button--primary"
                                disabled={pending || !canEdit}
                                aria-busy={pending}
                            >
                                {pending ? "Saving…" : "Save"}
                            </button>
                            <button
                                type="button"
                                className="authoring-button"
                                onClick={discard}
                                disabled={pending}
                            >
                                Discard changes
                            </button>
                        </div>
                    ) : null}
                </AuthoringForm>
            </section>
            <SessionLifecycleControls
                campaignId={campaignId}
                session={session}
                canManage={hasCapability}
                refresh={refresh}
                blockedReason={dirty ? "Save or discard your changes before archiving." : null}
            />
            <section aria-labelledby="session-events-heading">
                <h2 id="session-events-heading">Events</h2>
                {events.length > 0 ? (
                    <SortableTable
                        caption="Session events"
                        columns={eventColumns}
                        rows={events}
                        getRowKey={(event) => event.event_id}
                    />
                ) : (
                    <p>No events are recorded for this session.</p>
                )}
            </section>
            <ConfirmDialog
                open={guard.blocked}
                title="Discard your changes?"
                description="You have entered details that have not been saved."
                confirmLabel="Discard"
                cancelLabel="Keep editing"
                onConfirm={guard.discard}
                onCancel={guard.stay}
            />
        </section>
    )
}
