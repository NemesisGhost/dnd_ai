import type { OwnBrowserSession } from "../types/accountSessions"

interface OwnSessionsListProps {
    sessions: OwnBrowserSession[]
    onRevoke: (browserSessionId: string, isCurrent: boolean) => void
    revokingSessionId: string | null
}

function formatTimestamp(timestamp: string): string {
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
        new Date(timestamp),
    )
}

// A real <table> with headers, keyboard operable — every value rendered
// here (IP, user agent) is opaque text the server already stores, never a
// link (PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md §8.3's own note for
// CP 11b).
export function OwnSessionsList({ sessions, onRevoke, revokingSessionId }: OwnSessionsListProps) {
    return (
        <table>
            <caption>Your browser sessions</caption>
            <thead>
                <tr>
                    <th scope="col">Created</th>
                    <th scope="col">Last used</th>
                    <th scope="col">IP address</th>
                    <th scope="col">Device</th>
                    <th scope="col">Current</th>
                    <th scope="col">Actions</th>
                </tr>
            </thead>
            <tbody>
                {sessions.map((session) => (
                    <tr key={session.browser_session_id}>
                        <td>{formatTimestamp(session.created_at)}</td>
                        <td>{formatTimestamp(session.last_used_at)}</td>
                        <td>{session.created_ip ?? "Unknown"}</td>
                        <td>{session.user_agent ?? "Unknown"}</td>
                        <td>{session.is_current ? "Yes" : "No"}</td>
                        <td>
                            <button
                                type="button"
                                disabled={revokingSessionId === session.browser_session_id}
                                onClick={() => onRevoke(session.browser_session_id, session.is_current)}
                            >
                                Revoke
                            </button>
                        </td>
                    </tr>
                ))}
            </tbody>
        </table>
    )
}
