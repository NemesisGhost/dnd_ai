import { Link } from "react-router"
import type { ReactNode, RefObject } from "react"
import type { EntityLifecycleView } from "../../types/entityLifecycle"
import { LifecycleBadge } from "../authoring/feedback"

// The record's real status as badges: its canon status, and Archived once it is. `extra` is for a
// status only this kind of record has (an item's "Destroyed"). Nothing here is invented: a record
// whose status is not known yet shows none.
export function RecordStatus({
    status,
    extra = null,
}: {
    status: Pick<EntityLifecycleView, "canon_status" | "lifecycle_status">
    extra?: ReactNode
}) {
    return (
        <span className="item-header__status" role="group" aria-label="Record status">
            <LifecycleBadge status={status.canon_status} />
            {status.lifecycle_status === "archived" ? <LifecycleBadge status="archived" /> : null}
            {extra}
        </span>
    )
}

interface Props {
    // Where the person came from, as the domain words it: a link, or a breadcrumb.
    back: ReactNode
    // "Building", "NPC", "Item": the kind of record, in words.
    eyebrow: string
    // The place the record sits in, as a link (an area's dungeon): where the person can go up to.
    context?: { label: string; href: string; state?: object } | null
    name: string
    headingId: string
    headingRef: RefObject<HTMLHeadingElement | null>
    status: ReactNode
    summary: string | null
    // Facts about the record that sit before the next step (an item's kind).
    meta?: ReactNode
    // The one next step, as text; where it leads is `href`. Null when there is none.
    next: { text: string; href: string | null; state?: object } | null
}

// The always-visible top of a guided record page: where it is, what the record is, and its real
// status. Everything here is information or navigation; no lifecycle command or operation lives in
// it. The World, quest and item workspaces share it; each supplies its own back link, status and
// facts, so the frame is the only thing they have in common.
export function RecordHeader({ back, eyebrow, context = null, name, headingId, headingRef, status, summary, meta, next }: Props) {
    return (
        <header className="item-header">
            {back}
            <p className="world-detail__eyebrow">{eyebrow}</p>
            {context !== null ? (
                <p className="world-detail__context">
                    In{" "}
                    <Link to={context.href} state={context.state}>
                        {context.label}
                    </Link>
                </p>
            ) : null}
            <div className="item-header__headline">
                <h1 id={headingId} ref={headingRef} tabIndex={-1} className="item-header__title">
                    {name}
                </h1>
                {status}
            </div>
            {summary !== null ? <p className="world-detail__summary">{summary}</p> : null}
            {meta !== undefined || next !== null ? (
                <div className="item-header__meta">
                    {meta}
                    {next !== null ? (
                        <span className="item-header__next">
                            Next:{" "}
                            {next.href !== null ? (
                                <Link to={next.href} state={next.state}>
                                    {next.text} ›
                                </Link>
                            ) : (
                                next.text
                            )}
                        </span>
                    ) : null}
                </div>
            ) : null}
        </header>
    )
}
