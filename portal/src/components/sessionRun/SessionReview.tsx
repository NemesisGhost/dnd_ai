import { Link } from "react-router"
import type { CampaignSessionDetail } from "../../types/campaignSession"
import type { EncounterSummary } from "../../types/encounters"
import type { SectionKey } from "./runStages"
import { RealWorldTime } from "./RealWorldTime"
import { SessionEventList, TravelHistory } from "./SessionActivity"
import { SessionRoster } from "./SessionRoster"

const enc = encodeURIComponent

// Read-only recap of what the page already knows about the session. It changes nothing; each
// "go to" is a link to the section that does, or a reason when that section offers nothing now.
export function SessionReview({
    campaignId,
    session,
    encounters,
    sectionHref,
    canPrepareEncounters,
    reasonLog,
    reasonTravel,
}: {
    campaignId: string
    session: CampaignSessionDetail
    // null while the list is loading or unavailable.
    encounters: EncounterSummary[] | null
    sectionHref: (key: SectionKey) => string
    canPrepareEncounters: boolean
    reasonLog: string | null
    reasonTravel: string | null
}) {
    const actions = session.available_actions ?? []
    const participants = session.participants ?? []
    const present = participants.filter((p) => p.removed_at === null)
    const pending = (encounters ?? []).filter((e) => e.status === "pending")
    const started = (encounters ?? []).filter((e) => e.status !== "pending")
    const campaign = `/app/${enc(campaignId)}`
    const travel = session.travel ?? []

    return (
        <div className="session-run__review">
            <section aria-labelledby="review-overview-heading">
                <h3 id="review-overview-heading">Overview</h3>
                <ul className="record-list">
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
                <SessionRoster
                    campaignId={campaignId}
                    participants={participants}
                    emptyText="No one is in this session."
                />
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
                <SessionEventList
                    events={session.events}
                    travel={session.travel}
                    label="Recorded entries"
                    eventHref={(id) => `${campaign}/events/${enc(id)}`}
                />
                {actions.includes("log") ? (
                    <p>
                        <Link to={sectionHref("log")}>Add to the log</Link>
                    </p>
                ) : (
                    <p className="authoring-note">{reasonLog}</p>
                )}
            </section>

            <section aria-labelledby="review-travel-heading">
                <h3 id="review-travel-heading">Travel ({travel.length})</h3>
                {travel.length === 0 ? <p>No travel was recorded in this session.</p> : null}
                <TravelHistory
                    travel={travel}
                    label="Travel in this session"
                    eventHref={(id) => `${campaign}/events/${enc(id)}`}
                />
                {actions.includes("log") ? (
                    <p>
                        <Link to={sectionHref("travel")}>Record travel</Link>
                    </p>
                ) : (
                    <p className="authoring-note">{reasonTravel}</p>
                )}
                <p className="authoring-note">
                    Travel recorded before travel was linked to sessions is not listed here.
                </p>
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
                        <ul className="record-list">
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
