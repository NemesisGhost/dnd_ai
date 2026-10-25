import { useEffect, useRef } from "react"
import { Link } from "react-router"
import type { RetainedChange } from "../../utils/retainedChanges"

// What an edit page shows once the person has lost the right to edit or read the record: no form,
// nothing the server had sent, and no way to submit. Only what they themselves typed is shown back,
// read-only, so they can copy it (see utils/retainedChanges for what counts).
export function PermissionLost({
    noun,
    retained,
    back,
    recheck,
}: {
    noun: string
    retained: readonly RetainedChange[]
    back: { to: string; state?: object; label?: string }
    // Asks the server again what the person may do (their role may have been restored); the
    // answer, not this panel, decides.
    recheck?: () => void
}) {
    // The Save or Add button that had focus is gone with the form, so focus would fall to the page.
    // Moving it to the heading once, when the panel appears, is what tells a keyboard or screen
    // reader user; it is not a live region as well, which would announce the same text twice. A
    // rerender does not move focus again, and the panel's own link and button follow in tab order.
    const headingRef = useRef<HTMLHeadingElement>(null)
    useEffect(() => {
        headingRef.current?.focus()
    }, [])
    return (
        <section className="authoring-message authoring-message--warning" aria-label="Permission lost">
            <div>
                <h2 ref={headingRef} tabIndex={-1}>You no longer have permission to edit this {noun}</h2>
                <p>
                    Your access changed while you were editing. Nothing you typed was saved, and it cannot be
                    saved from here.
                </p>
                {retained.length > 0 ? (
                    <>
                        <p>What you had changed is shown below so you can copy it if you need it:</p>
                        <dl className="authoring-fact-list">
                            {retained.map((change) => (
                                <div key={`${change.label}:${change.value}`}>
                                    <dt>{change.label}</dt>
                                    <dd>{change.value}</dd>
                                </div>
                            ))}
                        </dl>
                    </>
                ) : null}
                <p>
                    <Link to={back.to} state={back.state}>
                        {back.label ?? `Back to the ${noun}`}
                    </Link>{" "}
                    {recheck === undefined ? null : (
                        <button type="button" className="authoring-button" onClick={recheck}>
                            Check my access again
                        </button>
                    )}
                </p>
            </div>
        </section>
    )
}
