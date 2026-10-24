import "./authoring/authoring.css"

// Shown when a panel keeps the last read it had because refreshing it failed: what is shown may be
// out of date, nothing typed is lost, and trying again only reads (it never repeats a command).
export function StaleReadNotice({ what, onRetry }: { what: string; onRetry: () => void }) {
    return (
        <div className="authoring-message authoring-message--warning" role="alert">
            <p>
                The latest {what} could not be loaded, so what is shown may be out of date. What you have typed is
                kept.
            </p>
            <button type="button" className="authoring-button" onClick={onRetry}>
                Try again
            </button>
        </div>
    )
}
