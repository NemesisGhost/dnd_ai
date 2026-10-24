import { Link } from "react-router"
import type { RetainedChange } from "../../utils/retainedChanges"

// What an edit page shows once the person has lost the right to edit or read the record: no form,
// nothing the server had sent, and no way to submit. Only what they themselves typed is shown back,
// read-only, so they can copy it (see utils/retainedChanges for what counts).
export function PermissionLost({
    noun,
    retained,
    back,
}: {
    noun: string
    retained: readonly RetainedChange[]
    back: { to: string; state?: object }
}) {
    return (
        <section className="authoring-message authoring-message--warning" aria-label="Permission lost" role="alert">
            <div>
                <h2>You no longer have permission to edit this {noun}</h2>
                <p>
                    Your access changed while you were editing. Nothing you typed was saved, and it cannot be
                    saved from here.
                </p>
                {retained.length > 0 ? (
                    <>
                        <p>What you had changed is shown below so you can copy it if you need it:</p>
                        <dl className="authoring-fact-list">
                            {retained.map((change) => (
                                <div key={change.label}>
                                    <dt>{change.label}</dt>
                                    <dd>{change.value}</dd>
                                </div>
                            ))}
                        </dl>
                    </>
                ) : null}
                <p>
                    <Link to={back.to} state={back.state}>
                        Back to the {noun}
                    </Link>
                </p>
            </div>
        </section>
    )
}
