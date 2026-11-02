import { AlertTriangle } from "lucide-react"
import { useState } from "react"
import { Link } from "react-router"
import { describeBlockedReason } from "../../utils/blockedReason"
import { useDocumentTitle } from "../../hooks/useDocumentTitle"
import { useRetryFocus } from "../../hooks/useRetryFocus"
import type { Recovery } from "../terminalRecovery"
import "./authoring.css"

// A read that failed for a reason worth retrying (the network or the server): nothing is wrong
// with the person's access, and trying again only reads.
export function ReadFailedNotice({
    what,
    onRetry,
    retrying = false,
}: {
    what: string
    // May return the read it starts; the button then reports "Loading…" until it settles.
    onRetry: () => void | Promise<unknown>
    retrying?: boolean
}) {
    const [reading, setReading] = useState(false)
    const { ref: retryRef, used: retryUsed, left: retryLeft } = useRetryFocus<HTMLButtonElement>()
    const busy = retrying || reading
    const retry = () => {
        if (busy) {
            return
        }
        retryUsed()
        const started = onRetry()
        if (started instanceof Promise) {
            setReading(true)
            void started.finally(() => setReading(false))
        }
    }
    return (
        <div className="authoring-message authoring-message--error" role="alert">
            <AlertTriangle aria-hidden="true" className="authoring-message__icon" />
            <div>
                <p>The {what} could not be loaded.</p>
                <button
                    type="button"
                    className="authoring-button"
                    ref={retryRef}
                    onClick={retry}
                    onBlur={retryLeft}
                    // aria-disabled, not disabled: a disabled button that has focus drops it to the page.
                    aria-disabled={busy ? true : undefined}
                    aria-busy={busy}
                >
                    {busy ? "Loading…" : "Try again"}
                </button>
            </div>
        </div>
    )
}

// A read the server refused (403) or answered as not available (404, which deliberately does not
// say whether the record exists). Neither is fixed by retrying, and nothing loaded earlier is shown.
export function ReadClosedNotice({ what, denied }: { what: string; denied: boolean }) {
    return (
        <p role="alert">
            {denied
                ? `You do not have access to the ${what}.`
                : `The ${what} is not available, or you can no longer access it.`}
        </p>
    )
}

// What a first read that did not return the record shows, in place of the page's content. The
// kinds stay apart: a 404 (not found, or not accessible — the server does not say which, so the
// text does not either) and a 403 are closed and retrying cannot help; a network or server failure
// is not about the person's access at all and offers a retry that only reads. When several reads
// back one page the least revealing closed answer wins, then a refusal, then a failure.
export function ReadTerminal({
    states,
    what,
    onRetry,
    back,
    pageTitle = true,
}: {
    states: readonly { kind: string }[]
    what: string
    onRetry: () => void | Promise<unknown>
    back?: Recovery
    // False for a panel inside a page that is otherwise working, which must not retitle the page.
    pageTitle?: boolean
}) {
    const kinds = states.map((state) => state.kind)
    const kind = kinds.includes("unavailable") ? "unavailable" : kinds.includes("denied") ? "denied" : "error"
    useDocumentTitle(
        !pageTitle ? null : kind === "error" ? "Could not load" : kind === "denied" ? "Access denied" : "Not available",
    )
    return (
        <>
            {kind === "error" ? (
                <ReadFailedNotice what={what} onRetry={onRetry} />
            ) : (
                <ReadClosedNotice what={what} denied={kind === "denied"} />
            )}
            {back === undefined ? null : (
                <p>
                    <Link to={back.to}>{back.label}</Link>
                </p>
            )}
        </>
    )
}

// A record the person may read that does not offer an action. Only what the server sent about the
// caller's own access is used: its `blocked_actions` reason (the record's lifecycle or state) when
// there is one, then its archived status, otherwise the plain fact that their role does not include the action.
export function ActionUnavailableNotice({
    noun,
    action,
    reason,
    archived = false,
    back,
}: {
    noun: string
    action: string
    reason?: string
    // The record's own lifecycle status, which the person can read, is archived.
    archived?: boolean
    back?: Recovery
}) {
    useDocumentTitle("Action unavailable")
    return (
        <>
            <p role="alert">
                {reason !== undefined
                    ? `You cannot ${action} this ${noun} right now: ${describeBlockedReason(reason)}`
                    : archived
                      ? `You cannot ${action} this ${noun} because it is archived.`
                      : `Your role on this ${noun} does not include being able to ${action} it.`}
            </p>
            {back === undefined ? null : (
                <p>
                    <Link to={back.to}>{back.label}</Link>
                </p>
            )}
        </>
    )
}
