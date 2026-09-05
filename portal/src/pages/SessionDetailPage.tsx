import { Link } from "react-router"
import { SortableTable } from "../components/SortableTable"
import type { SortableTableColumn } from "../components/SortableTable"
import type {
    CampaignSessionDetail,
    CampaignSessionEvent,
} from "../types/campaignSession"
import { applyDirection } from "../utils/sorting"
import type { SortDirection } from "../utils/sorting"

interface SessionDetailPageProps {
    session: CampaignSessionDetail
}

function compareStrings(
    a: string,
    b: string,
    direction: SortDirection,
): number {
    return applyDirection(direction, a.localeCompare(b))
}

const eventColumns: SortableTableColumn<CampaignSessionEvent>[] = [
    {
        key: "event_name",
        label: "Name",
        compare: (a, b, direction) =>
            compareStrings(a.name, b.name, direction),
        render: (event) => event.name,
    },
    {
        key: "event_type",
        label: "Type",
        compare: (a, b, direction) =>
            compareStrings(
                a.event_type_code,
                b.event_type_code,
                direction,
            ),
        render: (event) => event.event_type_code,
    },
    {
        key: "event_status",
        label: "Status",
        compare: (a, b, direction) =>
            compareStrings(
                a.event_status_code,
                b.event_status_code,
                direction,
            ),
        render: (event) => event.event_status_code,
    },
    {
        key: "event_summary",
        label: "Summary",
        render: (event) => event.summary ?? "No summary recorded",
    },
    {
        key: "event_details",
        label: "Details",
        render: (event) =>
            event.details ?? "No details recorded",
    },
]

function formatTimestamp(timestamp: string): string {
    return new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
    }).format(new Date(timestamp))
}

function renderTimestamp(timestamp: string | null) {
    return timestamp !== null ? (
        <time dateTime={timestamp}>{formatTimestamp(timestamp)}</time>
    ) : (
        "Not recorded"
    )
}

export function SessionDetailPage({
    session,
}: SessionDetailPageProps) {
    const title = session.title ?? `Session ${session.session_number}`
    const events = session.events

    return (
        <section aria-labelledby="session-heading">
            <Link to=".." relative="path">
                Back to sessions
            </Link>
            <h1 id="session-heading">{title}</h1>
            <section aria-labelledby="session-overview-heading">
                <h2 id="session-overview-heading">Overview</h2>
                <dl>
                    <div>
                        <dt>Session number</dt>
                        <dd>{session.session_number}</dd>
                    </div>

                    <div>
                        <dt>Status</dt>
                        <dd>{session.status_code}</dd>
                    </div>

                    <div>
                        <dt>Start time</dt>
                        <dd>{renderTimestamp(session.started_at)}</dd>
                    </div>

                    <div>
                        <dt>End time</dt>
                        <dd>{renderTimestamp(session.ended_at)}</dd>
                    </div>
                </dl>
            </section>
            <section aria-labelledby="session-summary-heading">
                <h2 id="session-summary-heading">Summary</h2>
                {session.summary !== null ? (
                    <p>{session.summary}</p>
                ) : (
                    <p>No summary is recorded for this session.</p>
                )}
            </section>
            <section aria-labelledby="session-events-heading">
                <h2 id="session-events-heading">Events</h2>
                {events.length > 0 ? (
                    <SortableTable
                        caption="Session events"
                        columns={eventColumns}
                        rows={events}
                        getRowKey={(event) => event.event_id}
                    />
                ) : (
                    <p>No events are recorded for this session.</p>
                )}
            </section>
        </section>
    )
}
