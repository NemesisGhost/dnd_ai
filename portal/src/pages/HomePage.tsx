import { RecentEventsSection } from "../components/RecentEventsSection"
import type { CampaignSummary } from "../types/campaignSummary"

interface HomePageProps {
    summary: CampaignSummary
}

export function HomePage({
    summary,
}: HomePageProps) {
    return (
        <section
            className="placeholder-page placeholder-page--wide"
            aria-labelledby="home-heading">
            <h1 id="home-heading">Campaign Home</h1>
            <section aria-labelledby="latest-session-heading">
                <h2 id="latest-session-heading">Latest session</h2>
                {summary.current_session === null ? (
                    <p>No sessions have been recorded.</p>
                ) : (
                    <>
                        <p>Session {summary.current_session.session_number}:{" "}{summary.current_session.title ?? "Untitled session"}</p>
                        <p>Status: {summary.current_session.status_code}</p>
                    </>
                )}
            </section>

            <section aria-labelledby="previous-session-heading">
                <h2 id="previous-session-heading">Previous session recap</h2>
                {summary.previous_session_recap === null ? (
                    <p>No previous session recap is available.</p>
                ) : (
                    <p>{summary.previous_session_recap}</p>
                )}
            </section>

            <RecentEventsSection events={summary.recent_events} />
        </section>
    )
}