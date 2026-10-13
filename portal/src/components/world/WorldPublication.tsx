import type { EntityLifecycleView } from "../../types/entityLifecycle"
import { Link } from "react-router"
import { LifecycleActionList, LifecycleBlockedReasons } from "../EntityLifecyclePanel"

type StatusView = Pick<EntityLifecycleView, "canon_status" | "lifecycle_status">

// The status in words. Never claims publishing hands the record to anyone: who can see it follows
// their own access, and what happens to it in play is recorded separately.
export function PublicationExplanation({ view }: { view: StatusView }) {
    if (view.lifecycle_status === "archived") {
        return (
            <p>
                Archived. It is hidden from players and lists, and kept as history. Nothing can change until it
                is restored.
            </p>
        )
    }
    switch (view.canon_status) {
        case "draft":
            return <p>Draft. Only people who can edit canon can see it. Submit it for review when it is ready.</p>
        case "proposed":
            return <p>In review. A reviewer can approve or reject it, or send it back to draft to change it.</p>
        case "approved":
            return <p>Approved, but not yet published. Publish it to make it part of canon.</p>
        case "canon":
            return <p>Published. Players can see it wherever their access allows.</p>
        case "rejected":
            return <p>Rejected. Return it to draft to rework it, or archive it.</p>
        case "superseded":
            return <p>Replaced. What was recorded here is kept.</p>
        default:
            return <p>No further review steps apply to this status.</p>
    }
}

interface Props {
    // Null when the lifecycle read failed: nothing is offered then, and the person can try again.
    lifecycleView: EntityLifecycleView | null
    historyHref: string
    linkState?: object
    onRetry: () => void
}

// Where the record is in its life and every step the server offers (the one lifecycle rule: the
// next step as the primary button, the rest under More, actionable reasons inline). Rendered
// inside a LifecycleActionsProvider.
export function WorldPublicationSection({ lifecycleView, historyHref, linkState, onRetry }: Props) {
    return (
        <>
            {lifecycleView === null ? (
                <div className="authoring-note" role="status">
                    <p>The record&apos;s lifecycle could not be loaded, so no step is shown.</p>
                    <button type="button" className="authoring-button" onClick={onRetry}>
                        Try again
                    </button>
                </div>
            ) : (
                <>
                    <PublicationExplanation view={lifecycleView} />
                    {lifecycleView.superseded_by !== null ? (
                        <p>Replaced by {lifecycleView.superseded_by.canonical_name}.</p>
                    ) : null}
                    <LifecycleActionList />
                    <LifecycleBlockedReasons />
                </>
            )}
            <p>
                <Link to={historyHref} state={linkState}>
                    Revision history and comparison
                </Link>
            </p>
        </>
    )
}
