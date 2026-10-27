import { Link, useParams } from "react-router"
import { worldPath } from "../api/worlds"
import { TimelineTree } from "../components/TimelineTree"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { usePageArrival } from "../hooks/usePageArrival"
import type { WorldDetail } from "../types/worldAuthoring"
import { worldAccess } from "../utils/worldAccess"
import "../components/authoring/authoring.css"

// The world-scoped Timelines collection: every timeline the server returns for
// this world to the signed-in user (GET /worlds/{id}), as a lineage, each
// linking to its independently reloadable detail route — or, for a world the
// server returns as view only, as plain names with no authoring destination. It never narrows to a
// campaign's timeline and never lists a timeline the server did not return.
export function TimelinesPage() {
    const { worldId = "" } = useParams()
    const { state, refetch } = useAuthoringResource<WorldDetail>(worldPath(worldId))
    const headingRef = usePageArrival(state.kind !== "loading")

    return (
        <div className="world-page">
            <div className="authoring-page">
                <p className="authoring-page__breadcrumb">
                    <Link to="/worlds">Worlds</Link>
                    {state.kind === "ready" ? (
                        <>
                            {" / "}
                            <Link to={`/worlds/${worldId}`}>World overview</Link>
                        </>
                    ) : null}
                </p>
                <h1 ref={headingRef} tabIndex={-1}>
                    {state.kind === "unavailable" || state.kind === "denied"
                        ? "Timelines not available"
                        : "Timelines"}
                </h1>

                {state.kind === "loading" ? (
                    <p role="status">Loading timelines…</p>
                ) : state.kind === "unavailable" || state.kind === "denied" ? (
                    <>
                        <p role="alert">
                            This world does not exist, or you do not have access to it.
                        </p>
                        <p>
                            <Link to="/worlds">Back to your worlds</Link>
                        </p>
                    </>
                ) : state.kind === "error" ? (
                    <>
                        <p role="alert">The timelines could not be loaded.</p>
                        <p>
                            <button
                                type="button"
                                className="authoring-button"
                                onClick={() => void refetch()}
                            >
                                Try again
                            </button>
                        </p>
                    </>
                ) : (
                    <>
                        <p className="authoring-page__lead">
                            Timelines you can view in this world.
                        </p>
                        {state.data.available_actions.includes("create_timeline") ? (
                            <p>
                                <Link
                                    className="authoring-button"
                                    to={`/worlds/${worldId}/timelines/new`}
                                >
                                    New timeline
                                </Link>
                            </p>
                        ) : null}
                        <TimelineTree
                            worldId={worldId}
                            timelines={state.data.timelines}
                            linked={worldAccess(state.data) === "edit"}
                        />
                    </>
                )}
            </div>
        </div>
    )
}
