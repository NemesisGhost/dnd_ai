import { Link } from "react-router"
import type { EntityLifecycleView } from "../../types/entityLifecycle"
import { LifecycleActionList } from "../EntityLifecyclePanel"
import { subjectBlocksPublish } from "./claimStages"

interface Props {
    view: EntityLifecycleView
    // The claim's subject, for the one blocker that names it. Null when the server returned none.
    subject: { name: string; href: string } | null
    // Where recording who knows the claim happens, and where the replacing claim is.
    whoKnowsHref: string
    replacementHref: string | null
    claimHref: string
    unsavedEdits: boolean
}

// The status in words, and the one thing that matters about it. Never claims publishing tells
// anyone: that is recorded separately in Use in play.
function Explanation({ view, subject, whoKnowsHref, replacementHref }: Omit<Props, "claimHref" | "unsavedEdits">) {
    if (view.lifecycle_status === "archived") {
        return (
            <p>
                Archived. It is hidden from players and lists, and kept as history. What was recorded about who knows
                it is kept, but nothing new can be recorded until it is restored.
            </p>
        )
    }
    switch (view.canon_status) {
        case "draft":
            return <p>Draft. Only people who can edit canon can see it. Submit it for review when it is ready.</p>
        case "proposed":
            return <p>In review. A reviewer can approve or reject it, or send it back to draft to change it.</p>
        case "approved":
            return subjectBlocksPublish(view) ? (
                <p role="status">
                    Approved, but not yet published. Its subject{subject !== null ? `, ${subject.name},` : ""} must be
                    published first.{" "}
                    {subject !== null ? <Link to={subject.href}>Open World entry</Link> : null}
                </p>
            ) : (
                <p>Approved, but not yet published. Publish it to make it part of canon.</p>
            )
        case "canon":
            return (
                <p>
                    Published. Publishing does not tell anyone; <Link to={whoKnowsHref}>record who knows it</Link> in
                    Use in play.
                </p>
            )
        case "rejected":
            return <p>Rejected. Return it to draft to rework it, or archive it.</p>
        case "superseded":
            return (
                <p>
                    Replaced
                    {view.superseded_by !== null ? (
                        <>
                            {" "}
                            by{" "}
                            {replacementHref !== null ? (
                                <Link to={replacementHref}>{view.superseded_by.canonical_name}</Link>
                            ) : (
                                view.superseded_by.canonical_name
                            )}
                        </>
                    ) : null}
                    . What was recorded here is kept; record new knowledge on the replacement.
                </p>
            )
        default:
            return <p>No further review steps apply to this status.</p>
    }
}

// The one place the claim's lifecycle steps live (besides the review decision): the status
// explained, then the steps the server offers this person, with their existing confirmations.
// Rendered inside a LifecycleActionsProvider.
export function ClaimPublication({ claimHref, unsavedEdits, ...rest }: Props) {
    return (
        <>
            <Explanation {...rest} />
            {unsavedEdits ? (
                <p className="authoring-note" role="status">
                    You have unsaved changes to the claim. They are not part of any step here.{" "}
                    <Link to={claimHref}>Save or discard them in Claim</Link>
                </p>
            ) : null}
            <LifecycleActionList compact />
        </>
    )
}
