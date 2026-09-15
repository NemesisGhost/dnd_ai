import type { CampaignSummary } from "../types/campaignSummary"

interface HomePageProps {
    summary: CampaignSummary
}

export function HomePage({
    summary,
}: HomePageProps) {
    return (
        <section
            className="placeholder-page"
            aria-labelledby="home-heading">
            <h1 id="home-heading">Home</h1>
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

            <section aria-labelledby="recent-events-heading">
                <h2 id="recent-events-heading">
                    Recent events
                </h2>

                {summary.recent_events.length === 0 ? (
                    <p>No recent events are available.</p>
                ) : (
                    <ul className="recent-events__list">
                        {summary.recent_events.map((event) => (
                            <li
                                key={event.event_id}
                                className="recent-events__item"
                            >
                                <article>
                                    <h3>{event.name}</h3>

                                    <p>
                                        {event.summary ??
                                            event.details ??
                                            "No event description is available."}
                                    </p>
                                </article>
                            </li>
                        ))}
                    </ul>
                )}
            </section>
        </section>
    )
}