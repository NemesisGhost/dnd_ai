import { Link } from "react-router"
import type { RefObject } from "react"
import type { EntityLifecycleView } from "../../types/entityLifecycle"
import { RecordHeader, RecordStatus } from "../records/RecordHeader"

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
    // The place the record sits in, as a link (an area's dungeon): where the person can go up to.
    context?: { label: string; href: string; state?: object } | null
    // The heading's id, for a workspace whose sections name it (default: the World workspace's).
    headingId?: string
}

// The always-visible top of the World record page, in the frame the item page shares
// (`RecordHeader`) so the guided workspaces look alike. This is the World and quest wording of it:
// a plain back link and a status that may not be known yet.
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
    context = null,
    headingId = "world-workspace-heading",
}: Props) {
    return (
        <RecordHeader
            back={
                <p>
                    <Link to={back.href}>{back.label}</Link>
                </p>
            }
            eyebrow={eyebrow}
            context={context}
            name={name}
            headingId={headingId}
            headingRef={headingRef}
            status={status !== null ? <RecordStatus status={status} /> : null}
            summary={summary}
            next={guidance === null ? null : { text: guidance.text, href: guidanceHref, state: linkState }}
        />
    )
}
