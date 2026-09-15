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

export function SessionsPage({
    sessions,
}: SessionsPageProps) {
    return (
        <section aria-labelledby="sessions-heading">
            <h1 id="sessions-heading">Sessions</h1>
            {sessions.length > 0 ? (
                <SortableTable
                    caption="Sessions"
                    columns={columns}
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
