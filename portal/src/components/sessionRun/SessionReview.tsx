import { Link } from "react-router"
import type { CampaignSessionDetail } from "../../types/campaignSession"
import type { EncounterSummary } from "../../types/encounters"
import type { SectionKey } from "./runStages"

const enc = encodeURIComponent

function formatRealWorld(value: string): string {
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

// A real-world timestamp, labelled as such so it is never read as in-world time.
export function RealWorldTime({ label, value }: { label: string; value: string }) {
    return (
        <>
            {label}: <time dateTime={value}>{formatRealWorld(value)}</time>
        </>
    )
}

const ROLE_LABEL: Readonly<Record<string, string>> = {
    player_character: "player character",
    npc: "NPC",
    guest: "guest",
}

// Read-only recap of what the page already knows about the session. It changes nothing; each
// "go to" is a link to the section that does, or a reason when that section offers nothing now.
export function SessionReview({
    campaignId,
    session,
    encounters,
    sectionHref,
    canPrepareEncounters,
    reasonLog,
}: {
    campaignId: string
    session: CampaignSessionDetail
    // null while the list is loading or unavailable.
    encounters: EncounterSummary[] | null
    sectionHref: (key: SectionKey) => string
    canPrepareEncounters: boolean
    reasonLog: string | null
}) {
    const actions = session.available_actions ?? []
    const participants = session.participants ?? []
    const present = participants.filter((p) => p.removed_at === null)
    const gone = participants.filter((p) => p.removed_at !== null)
    const pending = (encounters ?? []).filter((e) => e.status === "pending")
    const started = (encounters ?? []).filter((e) => e.status !== "pending")
    const campaign = `/app/${enc(campaignId)}`

    return (
        <div className="session-run__review">
            <section aria-labelledby="review-overview-heading">
                <h3 id="review-overview-heading">Overview</h3>
                <ul className="authoring-choice-list">
                    {session.scheduled_for ? (
                        <li>
                            <RealWorldTime label="Real-world planned start" value={session.scheduled_for} />
                        </li>
                    ) : null}
                    {session.started_at ? (
                        <li>
                            <RealWorldTime label="Real-world start" value={session.started_at} />
                        </li>
                    ) : null}
                    {session.ended_at ? (
                        <li>
                            <RealWorldTime label="Real-world end" value={session.ended_at} />
                        </li>
                    ) : null}
                    <li>{session.summary ? `Recap: ${session.summary}` : "No recap yet."}</li>
                </ul>
                <p>
                    <Link to={`${campaign}/sessions/${enc(session.session_id)}`}>Edit session details</Link>
                </p>
            </section>

            <section aria-labelledby="review-participants-heading">
                <h3 id="review-participants-heading">Participants ({present.length})</h3>
                {present.length === 0 ? <p>No one is in this session.</p> : null}
                <ul className="authoring-choice-list">
                    {present.map((p) => (
                        <li key={p.session_participant_id}>
                            {p.character_name}: {ROLE_LABEL[p.participation_role] ?? p.participation_role}
                        </li>
                    ))}
                </ul>
                {gone.length > 0 ? (
                    <p className="authoring-note">Departed: {gone.map((p) => p.character_name).join(", ")}</p>
                ) : null}
                {actions.includes("manage_participants") ? (
                    <p>
                        <Link to={sectionHref("participants")}>Change participants</Link>
                    </p>
                ) : (
                    <p className="authoring-note">Participants can't be changed now.</p>
                )}
            </section>

            <section aria-labelledby="review-log-heading">
                <h3 id="review-log-heading">Session log ({session.events.length})</h3>
                {session.events.length === 0 ? <p>Nothing has been recorded yet.</p> : null}
                <ul className="authoring-choice-list" aria-label="Recorded entries">
                    {session.events.map((event) => (
                        <li key={event.event_id}>
                            <Link to={`${campaign}/events/${enc(event.event_id)}`}>{event.name}</Link>
                            {event.details !== null ? (
                                <p className="authoring-note">GM notes: {event.details}</p>
                            ) : null}
                        </li>
                    ))}
                </ul>
                {actions.includes("log") ? (
                    <p>
                        <Link to={sectionHref("log")}>Add to the log</Link>
                    </p>
                ) : (
                    <p className="authoring-note">{reasonLog}</p>
                )}
            </section>

            <section aria-labelledby="review-encounters-heading">
                <h3 id="review-encounters-heading">Encounters</h3>
                {encounters === null ? (
                    <p>Encounters are not available.</p>
                ) : (
                    <>
                        <p>
                            {pending.length} prepared, {started.length} started or finished.
                        </p>
                        <ul className="authoring-choice-list">
                            {[...pending, ...started].map((e) => (
                                <li key={e.encounter_id}>
                                    <Link
                                        to={`${campaign}/sessions/${enc(session.session_id)}/encounters/${enc(e.encounter_id)}`}
                                    >
                                        {e.summary ?? "Untitled encounter"}
                                    </Link>{" "}
                                    ({e.status})
                                </li>
                            ))}
                        </ul>
                    </>
                )}
                <p>
                    {canPrepareEncounters ? (
                        <Link to={sectionHref("encounter-prep")}>Prepare encounters</Link>
                    ) : (
                        <span className="authoring-note">Encounters can't be prepared now.</span>
                    )}{" "}
                    {started.length > 0 ? <Link to={sectionHref("encounters")}>Open encounters</Link> : null}
                </p>
            </section>

            <section aria-labelledby="review-time-heading">
                <h3 id="review-time-heading">Campaign time</h3>
                <p>
                    The in-world time is shown above.{" "}
                    <Link to={sectionHref("log")}>Advance or correct time</Link> in the Run session stage.
                </p>
            </section>
        </div>
    )
}
