import { Link } from "react-router"
import { SortableTable } from "../components/SortableTable"
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

const columns: SortableTableColumn<CampaignSessionListItem>[] = [
    {
        key: "session_title",
        label: "Title",
        compare: compareTitles,
        render: (session) => (
            <Link to={encodeURIComponent(session.session_id)}>
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

// Editors (the server sends them `available_actions`) get an Edit link per
// session and a link to schedule a new one.
const editColumn: SortableTableColumn<CampaignSessionListItem> = {
    key: "session_actions",
    label: "Actions",
    compare: () => 0,
    render: (session) =>
        (session.available_actions ?? []).length > 0 ? (
            <Link to={`${encodeURIComponent(session.session_id)}/edit`}>
                Edit {session.title ?? `session ${session.session_number}`}
            </Link>
        ) : null,
}

export function SessionsPage({
    sessions,
}: SessionsPageProps) {
    const editor = sessions.some((session) => session.available_actions != null)
    return (
        <section aria-labelledby="sessions-heading">
            <h1 id="sessions-heading">Sessions</h1>
            {editor ? (
                <p>
                    <Link className="authoring-button" to="new">
                        Schedule a session
                    </Link>
                </p>
            ) : null}
            {sessions.length > 0 ? (
                <SortableTable
                    caption="Sessions"
                    columns={editor ? [...columns, editColumn] : columns}
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
