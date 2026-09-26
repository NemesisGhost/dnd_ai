import { useId, useState } from "react"

interface OneTimeSecretPanelProps {
    heading: string
    description: string
    secretLabel: string
    secret: string
    onDismiss: () => void
}

// A one-time secret (activation token, reset token) held in React memory
// only, for the life of this panel — never written to any storage, never
// re-fetchable once dismissed. Mirrors InvitationsSection's identical
// "Copy invitation token now" panel; factored out here so CP 10's account
// lifecycle secrets follow the exact same discipline without duplicating
// it a third time.
export function OneTimeSecretPanel({
    heading,
    description,
    secretLabel,
    secret,
    onDismiss,
}: OneTimeSecretPanelProps) {
    const headingId = useId()
    const statusId = useId()
    const [copyStatus, setCopyStatus] = useState<"idle" | "success" | "error">("idle")

    async function handleCopy(): Promise<void> {
        try {
            await navigator.clipboard.writeText(secret)
            setCopyStatus("success")
        } catch {
            setCopyStatus("error")
        }
    }

    return (
        <section aria-labelledby={headingId} className="access-member-card__body">
            <h3 id={headingId}>{heading}</h3>
            <p>{description}</p>
            <input type="text" value={secret} readOnly aria-label={secretLabel} />
            <div className="access-role-editor__actions">
                <button type="button" onClick={() => void handleCopy()}>
                    Copy
                </button>
                <button type="button" onClick={onDismiss}>
                    Dismiss
                </button>
            </div>
            <p id={statusId} className="access-role-editor__status" role="status" aria-live="polite">
                {copyStatus === "idle"
                    ? ""
                    : copyStatus === "success"
                      ? "Copied."
                      : "Could not copy. Copy it manually."}
            </p>
        </section>
    )
}
