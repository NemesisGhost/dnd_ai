import { useEffect, useId, useRef, useState } from "react"
import type { ReactNode } from "react"

interface OneTimeSecretPanelProps {
    heading: string
    description: string
    secretLabel: string
    secret: string
    // Called by the default Dismiss button; unused when `actions` replace it.
    onDismiss?: () => void
    // Replaces the Dismiss button (Copy stays) for a page that offers its own ways onward.
    actions?: ReactNode
    // Takes focus for the heading when the panel appears, but only if focus was lost with the control that
    // produced it (the document body); a control the person moved to meanwhile keeps it.
    focusHeading?: boolean
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
    actions,
    focusHeading = false,
}: OneTimeSecretPanelProps) {
    const headingId = useId()
    const headingRef = useRef<HTMLHeadingElement>(null)
    useEffect(() => {
        if (!focusHeading) {
            return
        }
        const active = document.activeElement
        if (active === null || active === document.body) {
            headingRef.current?.focus()
        }
    }, [focusHeading])
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
        <section aria-labelledby={headingId} className="one-time-secret">
            <h2 id={headingId} ref={headingRef} tabIndex={focusHeading ? -1 : undefined}>
                {heading}
            </h2>
            <p>{description}</p>
            <input type="text" value={secret} readOnly aria-label={secretLabel} />
            <div className="access-role-editor__actions">
                <button type="button" onClick={() => void handleCopy()}>
                    Copy
                </button>
                {actions ?? (
                    <button type="button" onClick={onDismiss}>
                        Dismiss
                    </button>
                )}
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
