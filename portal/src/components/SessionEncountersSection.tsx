import { Link } from "react-router"
import { sessionEncountersPath } from "../api/encounters"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { EncounterSummary } from "../types/encounters"
import "./authoring/authoring.css"

interface Props {
    campaignId: string
    sessionId: string
}

// The session's encounters, from the run page, with a link to prepare another. An encounter is
// opened to prepare it (pending) or, once started, to see how it stands.
export function SessionEncountersSection({ campaignId, sessionId }: Props) {
    const { state } = useAuthoringResource<{ items: EncounterSummary[] }>(
        sessionEncountersPath(campaignId, sessionId),
    )
    if (state.kind !== "ready") return null
    const base = `/app/${encodeURIComponent(campaignId)}/sessions/${encodeURIComponent(sessionId)}/encounters`
    return (
        <section aria-labelledby="session-encounters-heading">
            <h2 id="session-encounters-heading">Encounters</h2>
            {state.data.items.length === 0 ? <p>No encounters yet.</p> : null}
            <ul className="authoring-choice-list">
                {state.data.items.map((e) => (
                    <li key={e.encounter_id}>
                        <Link to={`${base}/${encodeURIComponent(e.encounter_id)}`}>
                            {e.summary ?? "Untitled encounter"}
                        </Link>{" "}
                        ({e.status}
                        {e.location_name !== null ? `, at ${e.location_name}` : ""}, {e.participant_count}{" "}
                        {e.participant_count === 1 ? "participant" : "participants"})
                    </li>
                ))}
            </ul>
            <p>
                <Link className="authoring-button" to={`${base}/new`}>
                    Prepare an encounter
                </Link>
            </p>
        </section>
    )
}
