import { AlertTriangle } from "lucide-react"
import "./authoring.css"

// A read that failed for a reason worth retrying (the network or the server): nothing is wrong
// with the person's access, and trying again only reads.
export function ReadFailedNotice({
    what,
    onRetry,
    retrying = false,
}: {
    what: string
    onRetry: () => void
    retrying?: boolean
}) {
    return (
        <div className="authoring-message authoring-message--error" role="alert">
            <AlertTriangle aria-hidden="true" className="authoring-message__icon" />
            <div>
                <p>The {what} could not be loaded.</p>
                <button
                    type="button"
                    className="authoring-button"
                    onClick={onRetry}
                    disabled={retrying}
                    aria-busy={retrying}
                >
                    {retrying ? "Loading…" : "Try again"}
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
