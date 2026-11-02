import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import { scheduleSession } from "../api/sessionAuthoring"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { TextAreaField, TextField } from "../components/authoring/fields"
import {
    AuthoringForm,
    ErrorSummary,
    FormActions,
    MutationStatusMessage,
} from "../components/authoring/feedback"
import type { FieldError } from "../components/authoring/feedback"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { usePageArrival } from "../hooks/usePageArrival"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import type { SessionReceipt } from "../types/campaignSession"
import { fromLocalInput } from "../utils/sessionForm"
import {
    DESCRIPTION_MAX,
    NAME_MAX,
    validateDescription,
} from "../utils/authoringValidation"
import "../components/authoring/authoring.css"

const base = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}`

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

// The Schedule a session form. Editing an existing session happens on its
// detail page (SessionDetailPage), not here.
function SessionForm({ campaignId }: { campaignId: string }) {
    const navigate = useNavigate()
    const { reload } = useSession()
    const initial: FormValues = { title: "", scheduledFor: "", summary: "" }
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
        scopeKey: `session-form:${campaignId}:new`,
        request: (body, ctx) => scheduleSession(campaignId, body, ctx),
        onSuccess: () => {
            guard.release()
            void navigate(`${base(campaignId)}/sessions`, {
                replace: true,
                state: { announce: "Session scheduled" },
            })
        },
    })
    const pending = mutation.status.kind === "pending"
    const error = mutation.status.kind === "error" ? mutation.status.error : null
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
            <AuthoringForm label="Schedule a session" onSubmit={submit}>
                <ErrorSummary errors={errors} attempt={attempt} />
                {error !== null ? (
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
                        Optional. When the table plans to play, in your time zone.
                    </p>
                    <input
                        id="session-scheduled"
                        className="authoring-field__control"
                        type="datetime-local"
                        value={values.scheduledFor}
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
                    saveLabel="Schedule session"
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
                <SessionForm key={campaignId} campaignId={campaignId} />
            ) : (
                <p role="alert">You do not have permission to schedule sessions in this campaign.</p>
            )}
        </section>
    )
}
