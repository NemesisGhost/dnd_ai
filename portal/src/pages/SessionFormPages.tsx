import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import {
    archiveSession,
    restoreSession,
    scheduleSession,
    sessionPath,
    updateSession,
} from "../api/sessionAuthoring"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { useAnnounce } from "../components/authoring/announcer"
import { TextAreaField, TextField } from "../components/authoring/fields"
import {
    AuthoringForm,
    ErrorSummary,
    FormActions,
    MutationStatusMessage,
    StaleWriteNotice,
} from "../components/authoring/feedback"
import type { FieldError } from "../components/authoring/feedback"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { usePageArrival } from "../hooks/usePageArrival"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import type { CampaignSessionDetail, SessionReceipt } from "../types/campaignSession"
import { fromLocalInput, toLocalInput } from "../utils/sessionForm"
import {
    DESCRIPTION_MAX,
    NAME_MAX,
    validateDescription,
} from "../utils/authoringValidation"
import "../components/authoring/authoring.css"

const base = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}`

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    session_not_active: "This session is archived. Restore it first.",
    session_not_archived: "This session is not archived.",
    session_in_progress: "End the session before archiving it.",
    session_already_started: "This session has already started, so its planned start cannot change.",
}

interface FormValues {
    title: string
    scheduledFor: string
    summary: string
}

function validate(values: FormValues): FieldError[] {
    const errors: FieldError[] = []
    if (values.title.trim().length > NAME_MAX) {
        errors.push({
            fieldId: "session-title",
            message: `Title must be ${NAME_MAX} characters or fewer.`,
        })
    }
    if (values.scheduledFor.trim() !== "" && fromLocalInput(values.scheduledFor) === null) {
        errors.push({ fieldId: "session-scheduled", message: "Enter a valid date and time." })
    }
    const summaryError = validateDescription(values.summary)
    if (summaryError) {
        errors.push({
            fieldId: "session-summary",
            message: summaryError.replace("Description", "Summary"),
        })
    }
    return errors
}

function SessionForm({
    campaignId,
    initial,
    version,
    sessionId,
    startedAlready,
    onStale,
}: {
    campaignId: string
    initial: FormValues
    version: number | null
    sessionId: string | null
    startedAlready: boolean
    onStale: () => void
}) {
    const navigate = useNavigate()
    const { reload } = useSession()
    const [values, setValues] = useState<FormValues>(initial)
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const dirty =
        values.title !== initial.title ||
        values.scheduledFor !== initial.scheduledFor ||
        values.summary !== initial.summary
    const guard = useUnsavedChangesGuard(dirty)
    const mutation = useAuthoringMutation<
        { title: string | null; scheduled_for: string | null; summary: string | null },
        SessionReceipt
    >({
        scopeKey: `session-form:${campaignId}:${sessionId ?? "new"}:${version ?? 0}`,
        request: (body, ctx) =>
            sessionId === null || version === null
                ? scheduleSession(campaignId, body, ctx)
                : updateSession(campaignId, sessionId, { ...body, expected_row_version: version }, ctx),
        onSuccess: () => {
            guard.release()
            void navigate(`${base(campaignId)}/sessions`, {
                replace: true,
                state: { announce: sessionId === null ? "Session scheduled" : "Session saved" },
            })
        },
    })
    const pending = mutation.status.kind === "pending"
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const message = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const errorFor = (id: string) => errors.find((e) => e.fieldId === id)?.message ?? null

    function submit() {
        const found = validate(values)
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length > 0) return
        mutation.submit({
            title: values.title.trim() === "" ? null : values.title.trim(),
            scheduled_for: fromLocalInput(values.scheduledFor),
            summary: values.summary.trim() === "" ? null : values.summary.trim(),
        })
    }

    return (
        <>
            <AuthoringForm label={sessionId === null ? "Schedule a session" : "Edit session"} onSubmit={submit}>
                <ErrorSummary errors={errors} attempt={attempt} />
                {error?.kind === "stale" ? (
                    <StaleWriteNotice onLoadLatest={onStale} />
                ) : message !== null ? (
                    <p role="alert">{message}</p>
                ) : error !== null ? (
                    <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
                ) : null}
                <TextField
                    id="session-title"
                    label="Title"
                    hint="Optional. The session number is assigned for you."
                    value={values.title}
                    onChange={(title) => setValues({ ...values, title })}
                    maxLength={NAME_MAX}
                    error={errorFor("session-title")}
                />
                <div className={errorFor("session-scheduled") ? "authoring-field authoring-field--invalid" : "authoring-field"}>
                    <label className="authoring-field__label" htmlFor="session-scheduled">
                        Planned start
                    </label>
                    <p className="authoring-field__hint" id="session-scheduled-hint">
                        {startedAlready
                            ? "This session has started, so its planned start cannot change."
                            : "Optional. When the table plans to play, in your time zone."}
                    </p>
                    <input
                        id="session-scheduled"
                        className="authoring-field__control"
                        type="datetime-local"
                        value={values.scheduledFor}
                        disabled={startedAlready}
                        aria-describedby="session-scheduled-hint"
                        aria-invalid={errorFor("session-scheduled") ? true : undefined}
                        onChange={(event) => setValues({ ...values, scheduledFor: event.target.value })}
                    />
                    {errorFor("session-scheduled") ? (
                        <p className="authoring-field__error">
                            <span className="visually-hidden">Error: </span>
                            {errorFor("session-scheduled")}
                        </p>
                    ) : null}
                </div>
                <TextAreaField
                    id="session-summary"
                    label="Summary"
                    hint="A recap or plan. Visible to everyone in the campaign."
                    value={values.summary}
                    onChange={(summary) => setValues({ ...values, summary })}
                    maxLength={DESCRIPTION_MAX}
                    error={errorFor("session-summary")}
                />
                <FormActions
                    pending={pending}
                    saveLabel={sessionId === null ? "Schedule session" : "Save session"}
                    onCancel={() => void navigate(`${base(campaignId)}/sessions`)}
                />
            </AuthoringForm>
            <ConfirmDialog
                open={guard.blocked}
                title="Discard your changes?"
                description="You have entered details that have not been saved."
                confirmLabel="Discard"
                cancelLabel="Keep editing"
                onConfirm={guard.discard}
                onCancel={guard.stay}
            />
        </>
    )
}

// /app/:campaignId/sessions/new
export function CreateSessionPage() {
    const { campaignId = "" } = useParams()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const headingRef = usePageArrival(true)
    return (
        <section className="authoring-page" aria-labelledby="new-session-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={`${base(campaignId)}/sessions`}>Sessions</Link>
            </p>
            <h1 id="new-session-heading" ref={headingRef} tabIndex={-1}>
                Schedule a session
            </h1>
            {canEdit ? (
                <SessionForm
                    key={campaignId}
                    campaignId={campaignId}
                    initial={{ title: "", scheduledFor: "", summary: "" }}
                    version={null}
                    sessionId={null}
                    startedAlready={false}
                    onStale={() => undefined}
                />
            ) : (
                <p role="alert">You do not have permission to schedule sessions in this campaign.</p>
            )}
        </section>
    )
}

// /app/:campaignId/sessions/:sessionId/edit
export function EditSessionPage() {
    const { campaignId = "", sessionId = "" } = useParams()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const detail = useAuthoringResource<CampaignSessionDetail>(sessionPath(campaignId, sessionId))
    const headingRef = usePageArrival(detail.state.kind === "ready")
    const data = detail.state.kind === "ready" ? detail.state.data : null
    const actions = data?.available_actions ?? []

    return (
        <section className="authoring-page" aria-labelledby="edit-session-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={`${base(campaignId)}/sessions`}>Sessions</Link>
            </p>
            <h1 id="edit-session-heading" ref={headingRef} tabIndex={-1}>
                Edit session
            </h1>
            {!canEdit ? (
                <p role="alert">You do not have permission to edit sessions in this campaign.</p>
            ) : detail.state.kind === "loading" ? (
                <p role="status">Loading session…</p>
            ) : data === null ? (
                <p role="alert">This session does not exist, or you do not have access to it.</p>
            ) : (
                <>
                    {data.status_code === "archived" ? (
                        <p className="authoring-note">This session is archived and cannot be edited.</p>
                    ) : null}
                    {actions.includes("update") ? (
                        <SessionForm
                            key={`${data.session_id}:${data.row_version}`}
                            campaignId={campaignId}
                            initial={{
                                title: data.title ?? "",
                                scheduledFor: toLocalInput(data.scheduled_for ?? null),
                                summary: data.summary ?? "",
                            }}
                            version={data.row_version ?? null}
                            sessionId={data.session_id}
                            startedAlready={data.started_at !== null}
                            onStale={() => void detail.refetch()}
                        />
                    ) : null}
                    <SessionLifecycle
                        campaignId={campaignId}
                        session={data}
                        refetch={detail.refetch}
                    />
                </>
            )}
        </section>
    )
}

function SessionLifecycle({
    campaignId,
    session,
    refetch,
}: {
    campaignId: string
    session: CampaignSessionDetail
    refetch: () => Promise<void>
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const [dialog, setDialog] = useState<"archive" | "restore" | null>(null)
    const [reason, setReason] = useState("")
    const [reasonError, setReasonError] = useState<string | null>(null)
    const actions = session.available_actions ?? []
    const mutation = useAuthoringMutation<"archive" | "restore", SessionReceipt>({
        scopeKey: `session-lifecycle:${session.session_id}:${session.row_version ?? 0}`,
        request: (action, ctx) =>
            action === "archive"
                ? archiveSession(
                      campaignId,
                      session.session_id,
                      { expected_row_version: session.row_version ?? 1, reason: reason.trim() || null },
                      ctx,
                  )
                : restoreSession(
                      campaignId,
                      session.session_id,
                      { expected_row_version: session.row_version ?? 1, reason: reason.trim() },
                      ctx,
                  ),
        onSuccess: async () => {
            const done = dialog === "archive" ? "Session archived" : "Session restored"
            setDialog(null)
            setReason("")
            await refetch()
            announce(done)
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const message = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const inProgress = session.play_status === "in_progress"

    if (!actions.includes("archive") && !actions.includes("restore") && !inProgress) return null
    return (
        <section aria-labelledby="session-lifecycle-heading">
            <h2 id="session-lifecycle-heading">Archive</h2>
            {inProgress ? (
                <p className="authoring-note">End the session before archiving it.</p>
            ) : null}
            {actions.includes("archive") ? (
                <button
                    type="button"
                    className="authoring-button"
                    onClick={() => {
                        mutation.reset()
                        setDialog("archive")
                    }}
                >
                    Archive session
                </button>
            ) : null}
            {actions.includes("restore") ? (
                <button
                    type="button"
                    className="authoring-button"
                    onClick={() => {
                        mutation.reset()
                        setDialog("restore")
                    }}
                >
                    Restore session
                </button>
            ) : null}
            <ConfirmDialog
                open={dialog !== null}
                title={dialog === "restore" ? "Restore this session?" : "Archive this session?"}
                description={
                    dialog === "restore"
                        ? "The session is visible to the campaign again."
                        : "The session is hidden from players. It can be restored later."
                }
                confirmLabel={dialog === "restore" ? "Restore session" : "Archive session"}
                pending={mutation.status.kind === "pending"}
                reason={{
                    label: dialog === "restore" ? "Reason" : "Reason (optional)",
                    required: dialog === "restore",
                    value: reason,
                    onChange: (value) => {
                        setReason(value)
                        setReasonError(null)
                    },
                    error: reasonError,
                }}
                error={
                    error?.kind === "stale" ? (
                        <StaleWriteNotice
                            onLoadLatest={() => {
                                mutation.reset()
                                setDialog(null)
                                void refetch()
                            }}
                        />
                    ) : message !== null ? (
                        <p role="alert">{message}</p>
                    ) : error !== null ? (
                        <MutationStatusMessage
                            error={error}
                            onRetry={mutation.retry}
                            onCheckSession={reload}
                        />
                    ) : null
                }
                onConfirm={() => {
                    if (dialog === "restore" && reason.trim() === "") {
                        setReasonError("Enter a reason.")
                        return
                    }
                    if (dialog !== null) mutation.submit(dialog)
                }}
                onCancel={() => {
                    setDialog(null)
                    setReason("")
                    setReasonError(null)
                    mutation.reset()
                }}
            />
        </section>
    )
}
