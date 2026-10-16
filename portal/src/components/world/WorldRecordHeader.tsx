import { Link } from "react-router"
import type { RefObject } from "react"
import type { EntityLifecycleView } from "../../types/entityLifecycle"
import { LifecycleBadge } from "../authoring/feedback"

interface Props {
    name: string
    // "Building", "NPC", "Religion": the kind of record, in words.
    eyebrow: string
    summary: string | null
    // The record's real status, from the lifecycle read; null while it is unknown (never invented).
    status: Pick<EntityLifecycleView, "canon_status" | "lifecycle_status"> | null
    // Where the person came from: the Review queue (with the filters it was left on) or the World
    // browser (with its category, search and page).
    back: { href: string; label: string }
    headingRef: RefObject<HTMLHeadingElement | null>
    // The one next step, as text; where it leads is `guidanceHref`. Null when there is none.
    guidance: { text: string } | null
    // Where the guidance leads; null when it has no destination.
    guidanceHref: string | null
    linkState?: object
    // The heading's id, for a workspace whose sections name it (default: the World workspace's).
    headingId?: string
}

// The always-visible top of the World record page: where it is, what the record is, and its real
// status. Everything here is information or navigation; no lifecycle command lives in it. It uses
// the item header's styling so the guided workspaces look alike.
export function WorldRecordHeader({
    name,
    eyebrow,
    summary,
    status,
    back,
    headingRef,
    guidance,
    guidanceHref,
    linkState,
    headingId = "world-workspace-heading",
}: Props) {
    return (
        <header className="item-header">
            <p>
                <Link to={back.href}>{back.label}</Link>
            </p>
            <p className="world-detail__eyebrow">{eyebrow}</p>
            <div className="item-header__headline">
                <h1 id={headingId} ref={headingRef} tabIndex={-1} className="item-header__title">
                    {name}
                </h1>
                {status !== null ? (
                    <span className="item-header__status" role="group" aria-label="Record status">
                        <LifecycleBadge status={status.canon_status} />
                        {status.lifecycle_status === "archived" ? <LifecycleBadge status="archived" /> : null}
                    </span>
                ) : null}
            </div>
            {summary !== null ? <p className="world-detail__summary">{summary}</p> : null}
            {guidance !== null ? (
                <div className="item-header__meta">
                    <span className="item-header__next">
                        Next:{" "}
                        {guidanceHref !== null ? (
                            <Link to={guidanceHref} state={linkState}>
                                {guidance.text} ›
                            </Link>
                        ) : (
                            guidance.text
                        )}
                    </span>
                </div>
            ) : null}
        </header>
    )
}
