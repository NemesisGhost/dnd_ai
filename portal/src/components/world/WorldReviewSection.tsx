import type { ReactNode } from "react"
import { Link } from "react-router"
import type { UseAuthoringResourceResult } from "../../hooks/useAuthoringResource"
import type { EntityLifecycleView } from "../../types/entityLifecycle"
import type { RevisionHistory } from "../../types/review"
import { LifecycleBlockedReasons, LifecycleReviewAction } from "../EntityLifecyclePanel"
import { describeRevision, comparisonLinks } from "./reviewLinks"
import { PublicationExplanation } from "./WorldPublication"

interface Props {
    lifecycleView: EntityLifecycleView | null
    revisions: UseAuthoringResourceResult<RevisionHistory>
    // The record's history address; a comparison adds `?from=&to=`.
    historyHref: string
    // The Details and Publication sections, for the links that leave this summary.
    detailsHref: string
    publicationHref: string
    linkState?: object
    // See PublicationExplanation.
    publishedText?: string
    // What else a reviewer should check, from the record itself (a quest's structure).
    summary?: ReactNode
}

const when = (iso: string): string => new Date(iso).toLocaleString()

// What a reviewer needs to decide, and the decision: where the record stands, the latest change
// and who made it, links to compare versions, whatever must happen first, and the approve or
// publish button when the server offers that step to this person. Nothing here is derived from
// the stage: the button comes only from the server's available actions. Rendered inside a
// LifecycleActionsProvider.
export function WorldReviewSection({
    lifecycleView,
    revisions,
    historyHref,
    detailsHref,
    publicationHref,
    linkState,
    publishedText,
    summary,
}: Props) {
    const state = revisions.state
    const list = state.kind === "ready" ? state.data.revisions : null
    const latest = list?.[0]
    const links = list === null ? [] : comparisonLinks(list)
    return (
        <>
            {lifecycleView === null ? (
                <p className="authoring-note" role="status">
                    The record&apos;s lifecycle could not be loaded, so no decision is shown. Try again from
                    Publication.
                </p>
            ) : (
                <PublicationExplanation view={lifecycleView} publishedText={publishedText} />
            )}
            {summary}
            <dl className="authoring-fact-list">
                <dt>Latest change</dt>
                <dd>
                    {state.kind === "loading"
                        ? "Loading…"
                        : list === null
                          ? "The revision history could not be loaded."
                          : latest === undefined
                            ? "No revisions are recorded."
                            : describeRevision(latest, when)}
                </dd>
                {links.length > 0 ? (
                    <>
                        <dt>Compare</dt>
                        <dd>
                            <ul className="world-detail__links">
                                {links.map((link) => (
                                    <li key={`${link.from}-${link.to}`}>
                                        <Link to={`${historyHref}?from=${link.from}&to=${link.to}`} state={linkState}>
                                            {link.label}
                                        </Link>
                                    </li>
                                ))}
                            </ul>
                        </dd>
                    </>
                ) : null}
            </dl>
            <LifecycleBlockedReasons />
            <LifecycleReviewAction />
            <p>
                <Link to={detailsHref} state={linkState}>
                    Check the details
                </Link>
                {" · "}
                <Link to={publicationHref} state={linkState}>
                    Other steps are in Publication
                </Link>
            </p>
        </>
    )
}
