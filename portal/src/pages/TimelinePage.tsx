import type { RefObject } from "react"
import { Link, useParams } from "react-router"
import { archiveTimeline, restoreTimeline, timelinePath } from "../api/timelines"
import { TransitionControls } from "../components/authoring/TransitionControls"
import { LifecycleBadge } from "../components/authoring/feedback"
import { TimelineTree } from "../components/TimelineTree"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { usePageArrival } from "../hooks/usePageArrival"
import type { TimelineDetail } from "../types/timelineAuthoring"
import { ERROR_CODE_MESSAGE } from "../utils/authoringValidation"
import "../components/authoring/authoring.css"

export function TimelinePage() {
    const { worldId = "", timelineId = "" } = useParams()
    const { state, refetch } = useAuthoringResource<TimelineDetail>(
        timelinePath(worldId, timelineId),
    )
    const headingRef = usePageArrival(state.kind === "ready")

    return (
        <div className="world-page">
            <div className="authoring-page">
                <p className="authoring-page__breadcrumb">
                    <Link to="/worlds">Worlds</Link>
                    {" / "}
                    <Link to={`/worlds/${worldId}`}>World overview</Link>
                    {" / "}
                    <Link to={`/worlds/${worldId}/timelines`}>Timelines</Link>
                </p>
                {state.kind === "loading" ? (
                    <>
                        <h1 ref={headingRef} tabIndex={-1}>
                            Timeline
                        </h1>
                        <p role="status">Loading timeline…</p>
                    </>
                ) : state.kind === "unavailable" || state.kind === "denied" ? (
                    <>
                        <h1 ref={headingRef} tabIndex={-1}>
                            Timeline not available
                        </h1>
                        <p role="alert">
                            This timeline does not exist, or you do not have access to it.
                        </p>
                    </>
                ) : state.kind === "error" ? (
                    <>
                        <h1 ref={headingRef} tabIndex={-1}>
                            Timeline
                        </h1>
                        <p role="alert">The timeline could not be loaded. Try reloading the page.</p>
                    </>
                ) : (
                    <TimelineView
                        worldId={worldId}
                        timeline={state.data}
                        headingRef={headingRef}
                        refetch={refetch}
                    />
                )}
            </div>
        </div>
    )
}

interface TimelineViewProps {
    worldId: string
    timeline: TimelineDetail
    headingRef: RefObject<HTMLHeadingElement | null>
    refetch: () => Promise<void>
}

function TimelineView({ worldId, timeline, headingRef, refetch }: TimelineViewProps) {
    const available = new Set(timeline.available_actions)
    const blocked = timeline.blocked_actions.filter(
        (b) => b.reason !== "lifecycle_transition_not_allowed",
    )

    return (
        <>
            <h1 ref={headingRef} tabIndex={-1}>
                {timeline.name}
            </h1>
            <p>
                {timeline.is_primary ? <span className="authoring-badge">Primary</span> : null}{" "}
                {timeline.lifecycle_status === "archived" ? (
                    <LifecycleBadge status="archived" />
                ) : null}
            </p>
            {timeline.description ? <p>{timeline.description}</p> : null}
            {timeline.branch_point !== null ? (
                <p className="authoring-note">
                    Branched at {timeline.branch_point.label ?? "an unlabeled point in time"}.
                </p>
            ) : null}

            <div className="authoring-actions">
                {available.has("update") ? (
                    <Link
                        className="authoring-button"
                        to={`/worlds/${worldId}/timelines/${timeline.timeline_id}/edit`}
                    >
                        Edit timeline
                    </Link>
                ) : null}
                {available.has("create_branch") ? (
                    <Link
                        className="authoring-button"
                        to={`/worlds/${worldId}/timelines/${timeline.timeline_id}/branch`}
                    >
                        Create branch
                    </Link>
                ) : null}
                {available.has("create_campaign") ? (
                    <Link
                        className="authoring-button authoring-button--primary"
                        to={`/campaigns/new?worldId=${encodeURIComponent(worldId)}&timelineId=${encodeURIComponent(timeline.timeline_id)}`}
                    >
                        New campaign
                    </Link>
                ) : null}
                <TransitionControls
                    noun="timeline"
                    scopeId={timeline.timeline_id}
                    rowVersion={timeline.row_version}
                    availableActions={timeline.available_actions}
                    archive={(body, ctx) => archiveTimeline(worldId, timeline.timeline_id, body, ctx)}
                    restore={(body, ctx) => restoreTimeline(worldId, timeline.timeline_id, body, ctx)}
                    refetch={refetch}
                    archiveDescription="No new branches or campaigns can be started on an archived timeline. Existing branches keep inheriting its history."
                    restoreDescription="The timeline accepts new branches and campaigns again."
                />
            </div>

            {blocked.length > 0 ? (
                <ul className="authoring-note" aria-label="Unavailable actions">
                    {blocked.map((item) => (
                        <li key={item.action}>
                            {item.action.replace(/_/g, " ")} unavailable:{" "}
                            {ERROR_CODE_MESSAGE[item.reason] ?? "not allowed right now."}
                        </li>
                    ))}
                </ul>
            ) : null}

            <section className="authoring-section" aria-labelledby="timeline-branches-heading">
                <h2 id="timeline-branches-heading">Branches</h2>
                {timeline.children.length === 0 ? (
                    <p>This timeline has no branches.</p>
                ) : (
                    <TimelineTree worldId={worldId} timelines={timeline.children} />
                )}
            </section>

            <section className="authoring-section" aria-labelledby="timeline-campaigns-heading">
                <h2 id="timeline-campaigns-heading">Your campaigns on this timeline</h2>
                {timeline.managed_campaigns.length === 0 ? (
                    <p>You do not manage any campaigns on this timeline yet.</p>
                ) : (
                    <ul className="authoring-list">
                        {timeline.managed_campaigns.map((campaign) => (
                            <li className="authoring-list__item" key={campaign.campaign_id}>
                                {campaign.lifecycle_status === "active" ? (
                                    <Link to={`/app/${campaign.campaign_id}/home`}>{campaign.name}</Link>
                                ) : (
                                    <span>{campaign.name}</span>
                                )}
                                {campaign.lifecycle_status === "archived" ? (
                                    <LifecycleBadge status="archived" />
                                ) : null}
                            </li>
                        ))}
                    </ul>
                )}
            </section>
        </>
    )
}
