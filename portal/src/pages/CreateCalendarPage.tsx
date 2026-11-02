import { Link, useParams } from "react-router"
import { ActionUnavailableNotice, ReadTerminal } from "../components/authoring/ReadState"
import { CalendarCreation } from "../components/calendar/CalendarCreation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { usePageArrival } from "../hooks/usePageArrival"
import type { WorldDetail } from "../types/worldAuthoring"
import { worldPath } from "../api/worlds"
import { blockedReasonFor } from "../utils/blockedReason"
import "../components/authoring/authoring.css"

// /worlds/:worldId/calendars/new — a world owner defines a calendar: its name,
// optional epoch and days per week, and its months in order, in three local steps
// (Basics, Months, Review & create). A calendar is created whole, in one request;
// editing one after times refer to it is not offered. The form is keyed by the
// route's world, so a draft can never be shown or sent under another world.
export function CreateCalendarPage() {
    const { worldId } = useParams<{ worldId: string }>()
    const id = worldId ?? ""
    const { state, refetch } = useAuthoringResource<WorldDetail>(worldId ? worldPath(id) : null)
    // Moving between the steps changes only the query, so arrival is once per path.
    const headingRef = usePageArrival(state.kind !== "loading", "path")
    const canCreate =
        state.kind === "ready" && state.data.available_actions.includes("create_calendar")

    return (
        <div className="world-page">
            <div className="authoring-page">
                <p className="authoring-page__breadcrumb">
                    <Link to={`/worlds/${encodeURIComponent(id)}`}>World</Link>
                </p>
                <h1 ref={headingRef} tabIndex={-1}>
                    New calendar
                </h1>
                {state.kind === "loading" ? (
                    <p role="status">Loading…</p>
                ) : state.kind !== "ready" ? (
                    <ReadTerminal
                        states={[state]}
                        what="world"
                        onRetry={refetch}
                        back={{ to: "/worlds", label: "Back to Worlds" }}
                    />
                ) : !canCreate ? (
                    <ActionUnavailableNotice
                        noun="world"
                        action="create a calendar for"
                        reason={blockedReasonFor(state.data.blocked_actions, "create_calendar")}
                        archived={state.data.lifecycle_status === "archived"}
                        back={{ to: `/worlds/${encodeURIComponent(id)}`, label: "Back to the world" }}
                    />
                ) : (
                    <CalendarCreation key={id} worldId={id} />
                )}
            </div>
        </div>
    )
}
