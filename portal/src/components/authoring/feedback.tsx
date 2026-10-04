import { useEffect, useRef } from "react"
import type { FormEvent, ReactNode } from "react"
import {
    AlertTriangle,
    Archive,
    BadgeCheck,
    CheckCircle2,
    Eye,
    FileText,
    Replace,
    XCircle,
} from "lucide-react"
import type { AuthoringError } from "../../types/apiError"
import { ERROR_CODE_MESSAGE } from "../../utils/authoringValidation"
import "./authoring.css"

export interface FieldError {
    fieldId: string
    message: string
}

interface ErrorSummaryProps {
    errors: readonly FieldError[]
    formError?: string | null
    // Incremented by the page on every failed submit attempt; the summary takes
    // focus each time it changes while it has something to say.
    attempt: number
}

// Shown after a failed submit. It is focusable and takes focus on each failed
// attempt, announces once (role="alert"), and links every field error to its
// input. Entered values are never cleared by a failure.
export function ErrorSummary({ errors, formError, attempt }: ErrorSummaryProps) {
    const ref = useRef<HTMLDivElement>(null)
    const hasContent = errors.length > 0 || Boolean(formError)

    useEffect(() => {
        if (attempt > 0 && hasContent) {
            ref.current?.focus()
        }
    }, [attempt, hasContent])

    if (!hasContent) {
        return null
    }

    return (
        <div ref={ref} className="authoring-error-summary" role="alert" tabIndex={-1}>
            <h2 className="authoring-error-summary__title">There is a problem</h2>
            {formError ? <p>{formError}</p> : null}
            {errors.length > 0 ? (
                <ul>
                    {errors.map((error) => (
                        <li key={error.fieldId}>
                            <a
                                href={`#${error.fieldId}`}
                                onClick={(event) => {
                                    event.preventDefault()
                                    document.getElementById(error.fieldId)?.focus()
                                }}
                            >
                                {error.message}
                            </a>
                        </li>
                    ))}
                </ul>
            ) : null}
        </div>
    )
}

interface FormActionsProps {
    pending: boolean
    onCancel: () => void
    saveLabel?: string
    pendingLabel?: string
    cancelLabel?: string
}

// Explicit Save and Cancel. Save is the only submit button; while pending it is
// disabled, `aria-busy`, and relabelled "Saving…". Cancel never submits.
export function FormActions({
    pending,
    onCancel,
    saveLabel = "Save",
    pendingLabel = "Saving…",
    cancelLabel = "Cancel",
}: FormActionsProps) {
    return (
        <div className="authoring-actions">
            <button
                type="submit"
                className="authoring-button authoring-button--primary"
                disabled={pending}
                aria-busy={pending}
            >
                {pending ? pendingLabel : saveLabel}
            </button>
            <button
                type="button"
                className="authoring-button"
                onClick={onCancel}
                disabled={pending}
            >
                {cancelLabel}
            </button>
        </div>
    )
}

interface AuthoringFormProps {
    onSubmit: () => void
    children: ReactNode
    label: string
}

// A <form noValidate> whose submission is handled by the page (client-side
// mirrors run first). `label` names the form for assistive technology.
export function AuthoringForm({ onSubmit, children, label }: AuthoringFormProps) {
    return (
        <form
            className="authoring-form"
            noValidate
            aria-label={label}
            onSubmit={(event: FormEvent<HTMLFormElement>) => {
                event.preventDefault()
                onSubmit()
            }}
        >
            {children}
        </form>
    )
}

interface MutationStatusMessageProps {
    error: AuthoringError
    onRetry: () => void
    onCheckSession: () => void
}

// Safe, per-kind copy for a failed write. The server's stable `code` selects a
// specific sentence when one exists; nothing from the response body is ever
// rendered. `stale` is deliberately not handled here — see StaleWriteNotice.
export function MutationStatusMessage({
    error,
    onRetry,
    onCheckSession,
}: MutationStatusMessageProps) {
    const specific = error.code !== null ? ERROR_CODE_MESSAGE[error.code] : undefined
    let message: string
    let action: ReactNode = null

    switch (error.kind) {
        case "denied":
            message =
                "You do not have permission to do this. Your access may have changed."
            action = (
                <button type="button" className="authoring-button" onClick={onCheckSession}>
                    Check my session
                </button>
            )
            break
        case "unavailable":
            message = "This record no longer exists, or you can no longer access it."
            break
        case "network":
            message = "We could not reach the server. Your input has been kept."
            action = (
                <button type="button" className="authoring-button" onClick={onRetry}>
                    Retry
                </button>
            )
            break
        case "server":
            message = "Something went wrong on our side. Your input has been kept."
            action = (
                <button type="button" className="authoring-button" onClick={onRetry}>
                    Retry
                </button>
            )
            break
        case "conflict":
            message =
                specific ??
                "That change conflicts with the record's current state. Reload and try again."
            break
        case "invalid":
            message = specific ?? "Check the details you entered and try again."
            break
        default:
            message = "That could not be completed."
    }

    return (
        <div className="authoring-message authoring-message--error" role="alert">
            <AlertTriangle aria-hidden="true" className="authoring-message__icon" />
            <div>
                <p>{message}</p>
                {error.correlationId !== null && error.kind === "server" ? (
                    <p className="authoring-field__hint">Reference: {error.correlationId}</p>
                ) : null}
                {action}
            </div>
        </div>
    )
}

interface StaleWriteNoticeProps {
    onLoadLatest: () => void
    loading?: boolean
    // The user's unsaved values, shown read-only so nothing typed is lost when
    // the form is replaced by the server's latest version.
    yourChanges?: ReactNode
}

// Shown when another person changed the record first (409 `stale_write`). The
// old row version is never resubmitted: "Load latest version" refetches and
// replaces the form with the server's values, while the user's previous
// unsaved values stay visible below so they can re-apply them.
export function StaleWriteNotice({
    onLoadLatest,
    loading = false,
    yourChanges,
}: StaleWriteNoticeProps) {
    return (
        <div className="authoring-message authoring-message--warning" role="alert">
            <AlertTriangle aria-hidden="true" className="authoring-message__icon" />
            <div>
                <p>
                    Someone else changed this record while you were editing. Load the latest
                    version, then re-apply your changes.
                </p>
                <button
                    type="button"
                    className="authoring-button authoring-button--primary"
                    onClick={onLoadLatest}
                    disabled={loading}
                    aria-busy={loading}
                >
                    {loading ? "Loading…" : "Load latest version"}
                </button>
                {yourChanges ? (
                    <section aria-label="Your unsaved changes" className="authoring-your-changes">
                        <h2>Your unsaved changes</h2>
                        {yourChanges}
                    </section>
                ) : null}
            </div>
        </div>
    )
}

const BADGES: Readonly<
    Record<string, { label: string; Icon: typeof FileText }>
> = {
    draft: { label: "Draft", Icon: FileText },
    proposed: { label: "In review", Icon: Eye },
    approved: { label: "Approved", Icon: CheckCircle2 },
    canon: { label: "Canon", Icon: BadgeCheck },
    superseded: { label: "Superseded", Icon: Replace },
    rejected: { label: "Rejected", Icon: XCircle },
    archived: { label: "Archived", Icon: Archive },
}

interface LifecycleBadgeProps {
    // A canon status code (draft, proposed, …) or `archived`.
    status: string
}

// State is communicated by text AND an icon, never color alone
// (docs/UI_STYLE_GUIDE.md accessibility rules).
export function LifecycleBadge({ status }: LifecycleBadgeProps) {
    const badge = BADGES[status]
    if (badge === undefined) {
        return <span className="authoring-badge">{status}</span>
    }
    const { label, Icon } = badge
    return (
        <span className={`authoring-badge authoring-badge--${status}`}>
            <Icon aria-hidden="true" className="authoring-badge__icon" />
            {label}
        </span>
    )
}
