import { Link } from "react-router"
import type { TimelineSummary } from "../types/worldAuthoring"
import { LifecycleBadge } from "./authoring/feedback"
import "./authoring/authoring.css"

interface TimelineTreeProps {
    worldId: string
    timelines: readonly TimelineSummary[]
}

// The world's timelines as an indented lineage: each branch nests under its
// parent. Roots are timelines with no parent (the primary first, then other
// roots). A timeline whose parent is missing from the list (it cannot happen
// for a consistent response) is shown as a root rather than dropped.
export function TimelineTree({ worldId, timelines }: TimelineTreeProps) {
    const byParent = new Map<string | null, TimelineSummary[]>()
    const known = new Set(timelines.map((t) => t.timeline_id))
    for (const timeline of timelines) {
        const parent =
            timeline.parent_timeline_id !== null && known.has(timeline.parent_timeline_id)
                ? timeline.parent_timeline_id
                : null
        byParent.set(parent, [...(byParent.get(parent) ?? []), timeline])
    }

    function renderLevel(parentId: string | null) {
        const children = byParent.get(parentId) ?? []
        if (children.length === 0) {
            return null
        }
        return (
            <ul className="authoring-tree" role={parentId === null ? "tree" : "group"}>
                {children.map((timeline) => (
                    <li key={timeline.timeline_id} role="treeitem" aria-expanded={undefined}>
                        <Link to={`/worlds/${worldId}/timelines/${timeline.timeline_id}`}>
                            {timeline.name}
                        </Link>{" "}
                        {timeline.is_primary ? (
                            <span className="authoring-badge">Primary</span>
                        ) : null}{" "}
                        {timeline.lifecycle_status === "archived" ? (
                            <LifecycleBadge status="archived" />
                        ) : null}
                        {timeline.branch_point !== null ? (
                            <span className="authoring-field__hint">
                                {" "}
                                — branched at{" "}
                                {timeline.branch_point.label ?? "an unlabeled point in time"}
                            </span>
                        ) : null}
                        {renderLevel(timeline.timeline_id)}
                    </li>
                ))}
            </ul>
        )
    }

    return (
        <div className="authoring-tree__scroll">
            {timelines.length === 0 ? <p>This world has no timelines.</p> : renderLevel(null)}
        </div>
    )
}
