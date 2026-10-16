// The notice for a conflict, in the section that holds the form.
export function DraftConflict({
    what,
    onLatest,
    onKeep,
}: {
    what: string
    onLatest: () => void
    onKeep: () => void
}) {
    return (
        <div className="authoring-message authoring-message--warning" role="alert">
            <p>
                {what} changed elsewhere while you were editing it. Your unsent changes are kept, and saving is paused
                until you choose.
            </p>
            <div className="authoring-actions">
                <button type="button" className="authoring-button" onClick={onLatest}>
                    Load the latest saved version
                </button>
                <button type="button" className="authoring-button" onClick={onKeep}>
                    Keep my changes and save over it
                </button>
            </div>
        </div>
    )
}
