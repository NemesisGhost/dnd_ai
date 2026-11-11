import { Link, useLocation, useParams } from "react-router"
import { useTaskLinkState } from "../navigation/useTaskLinkState"
import { continuedStateVia } from "../navigation/breadcrumbModel"
import type { CrumbState } from "../navigation/breadcrumbModel"
import { SortableTable } from "../components/SortableTable"
import { canRunSession } from "../components/sessionRun/runAccess"
import type { SortableTableColumn } from "../components/SortableTable"
import type {
    CampaignSessionListItem,
} from "../types/campaignSession"
import {
    applyDirection,
    compareNullableTimestamps,
} from "../utils/sorting"
import type { SortDirection } from "../utils/sorting"

interface SessionsPageProps {
    sessions: CampaignSessionListItem[]
    canSchedule?: boolean
}

function formatTimestamp(timestamp: string): string {
    return new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
    }).format(new Date(timestamp))
}

function compareTitles(
    a: CampaignSessionListItem,
    b: CampaignSessionListItem,
    direction: SortDirection,
): number {
    return applyDirection(
        direction,
        (a.title ?? "Untitled session").localeCompare(
            b.title ?? "Untitled session",
        ),
    )
}

function renderTimestamp(timestamp: string | null) {
    return timestamp !== null ? (
        <time dateTime={timestamp}>{formatTimestamp(timestamp)}</time>
    ) : (
        "Not recorded"
    )
}

const PLAY_STATUS_LABEL: Readonly<Record<string, string>> = {
    unscheduled: "Not scheduled",
    scheduled: "Scheduled",
    in_progress: "In progress",
    completed: "Completed",
}

// `state` is the Sessions task the list is the page of: a session opened from here is a step of it.
const columnsFor = (state: CrumbState | undefined): SortableTableColumn<CampaignSessionListItem>[] => [
    {
        key: "session_title",
        label: "Title",
        compare: compareTitles,
        render: (session) => (
            <Link to={encodeURIComponent(session.session_id)} state={state}>
                {session.title ?? "Untitled session"}
            </Link>
        ),
    },
    {
        key: "session_status",
        label: "Status",
        compare: (a, b, direction) =>
            applyDirection(
                direction,
                (a.play_status ?? "").localeCompare(b.play_status ?? ""),
            ),
        render: (session) =>
            `${PLAY_STATUS_LABEL[session.play_status ?? "unscheduled"] ?? "Not scheduled"}${
                session.status_code === "archived" ? " (archived)" : ""
            }`,
    },
    {
        key: "session_scheduled_for",
        label: "Planned start",
        compare: (a, b, direction) =>
            compareNullableTimestamps(
                a.scheduled_for ?? null,
                b.scheduled_for ?? null,
                direction,
            ),
        render: (session) => renderTimestamp(session.scheduled_for ?? null),
    },
    {
        key: "session_started_at",
        label: "Start time",
        compare: (a, b, direction) =>
            compareNullableTimestamps(a.started_at, b.started_at, direction),
        render: (session) => renderTimestamp(session.started_at),
    },
    {
        key: "session_ended_at",
        label: "End time",
        compare: (a, b, direction) =>
            compareNullableTimestamps(a.ended_at, b.ended_at, direction),
        render: (session) => renderTimestamp(session.ended_at),
    },
]

// Editors (the server sends them `available_actions`) get a Run link where a
// session can be run, and a link to schedule a new one. Editing happens on the
// session detail page that the title links to.
// `runState` is the task for a session's Run link. Run belongs under the session, which the list skips, so
// the session is part of the trail the link carries and Run keeps its documented hierarchy.
const editColumnFor = (
    runState: (sessionId: string) => CrumbState | undefined,
): SortableTableColumn<CampaignSessionListItem> => ({
    key: "session_actions",
    label: "Actions",
    compare: () => 0,
    render: (session) => {
        const actions = session.available_actions ?? []
        const name = session.title ?? `session ${session.session_number}`
        if (!canRunSession(actions)) return null
        return (
            <Link to={`${encodeURIComponent(session.session_id)}/run`} state={runState(session.session_id)}>
                Run {name}
            </Link>
        )
    },
})

export function SessionsPage({
    sessions,
    canSchedule = false,
}: SessionsPageProps) {
    const editor = sessions.some((session) => session.available_actions != null)
    const taskState = useTaskLinkState()
    const { pathname, state } = useLocation()
    const { campaignId = "" } = useParams()
    const runState = (sessionId: string): CrumbState | undefined =>
        continuedStateVia(
            pathname,
            state,
            { route: "sessions.detail", params: { campaignId, sessionId } },
            { route: "sessions.run", params: { campaignId, sessionId } },
        ) ?? undefined
    const columns = columnsFor(taskState)
    return (
        <section aria-labelledby="sessions-heading">
            <h1 id="sessions-heading">Sessions</h1>
            {canSchedule ? (
                <p>
                    <Link className="authoring-button" to="new" state={taskState}>
                        Schedule a session
                    </Link>
                </p>
            ) : null}
            {sessions.length > 0 ? (
                <SortableTable
                    caption="Sessions"
                    columns={editor ? [...columns, editColumnFor(runState)] : columns}
                    rows={sessions}
                    getRowKey={(session) => session.session_id}
                    initialSort={{ column: "session_started_at", direction: "desc" }}
                />
            ) : (
                <p>No sessions are available for this campaign.</p>
            )}
        </section>
    )
}
