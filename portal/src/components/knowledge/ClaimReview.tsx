import type { ReactNode } from "react"
import { Link } from "react-router"
import type { KnowledgeAuthoringView, KnowledgeOptions } from "../../types/knowledgeAuthoring"
import { humanizeCode } from "../../utils/humanize"
import { LifecycleBadge } from "../authoring/feedback"

const readable = (choices: { value: string; label: string }[] | undefined, value: string): string =>
    choices?.find((c) => c.value === value)?.label ?? humanizeCode(value)

interface Props {
    // The saved claim, as the reviewer would approve it. Null while it loads or when it could not.
    view: KnowledgeAuthoringView | null
    options: KnowledgeOptions | null
    // How many sources are attached now; null while unknown.
    sourceCount: number | null
    // The Claim and Sources sections, for the links that leave this read-only summary.
    claimHref: string
    sourcesHref: string
    // The claim has edits that are not saved, and so are not part of what is reviewed.
    unsavedEdits: boolean
    // The approve or publish button, when the person may take that step.
    children?: ReactNode
}

// A read-only summary of exactly what a reviewer approves: the saved claim, its subject and that
// subject's own status. Nothing here changes the claim or its status except the decision button
// the page passes in.
export function ClaimReview({ view, options, sourceCount, claimHref, sourcesHref, unsavedEdits, children }: Props) {
    if (view === null) {
        return <p className="authoring-note">The claim could not be loaded for review.</p>
    }
    return (
        <>
            {unsavedEdits ? (
                <p className="authoring-note" role="status">
                    You have unsaved changes to the claim. They are not part of review or publication.{" "}
                    <Link to={claimHref}>Save or discard them in Claim</Link>
                </p>
            ) : null}
            <dl className="authoring-fact-list knowledge-review__facts">
                <dt>Claim</dt>
                <dd className="knowledge-review__statement">{view.statement}</dd>
                <dt>About</dt>
                <dd>
                    {view.subject === null ? (
                        "No subject"
                    ) : (
                        <>
                            {view.subject.name}{" "}
                            <LifecycleBadge
                                status={view.subject.lifecycle_status === "archived" ? "archived" : view.subject.canon_status}
                            />
                        </>
                    )}
                </dd>
                <dt>Kind</dt>
                <dd>{readable(options?.knowledge_types, view.knowledge_type)}</dd>
                <dt>Truth</dt>
                <dd>{readable(options?.truth_statuses, view.truth_status)}</dd>
                <dt>Sensitivity</dt>
                <dd>{readable(options?.sensitivities, view.sensitivity)}</dd>
                <dt>Sources</dt>
                <dd>
                    {sourceCount === null
                        ? "Not loaded"
                        : sourceCount === 0
                          ? "None attached (sources are optional)"
                          : `${sourceCount} attached`}{" "}
                    <Link to={sourcesHref}>Open Sources</Link>
                </dd>
                <dt>Known by anyone</dt>
                <dd>{view.in_use ? "Yes. Someone has already been recorded as knowing it." : "No one yet."}</dd>
            </dl>
            <p>
                <Link to={claimHref}>Edit in Claim</Link>
            </p>
            {children}
        </>
    )
}
