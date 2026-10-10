import { Link } from "react-router"
import type { EncounterSummary } from "../types/encounters"
import "./authoring/authoring.css"

const encountersBase = (campaignId: string, sessionId: string): string =>
    `/app/${encodeURIComponent(campaignId)}/sessions/${encodeURIComponent(sessionId)}/encounters`

// The encounters in `items` (the caller may have narrowed them), each opening its own page.
// `prepareLink` adds the link to prepare another.
export function EncounterList({
    campaignId,
    sessionId,
    items,
    emptyText,
    prepareLink,
}: {
    campaignId: string
    sessionId: string
    items: EncounterSummary[]
    emptyText: string
    prepareLink: boolean
}) {
    const base = encountersBase(campaignId, sessionId)
    return (
        <>
            {items.length === 0 ? <p>{emptyText}</p> : null}
            <ul className="authoring-choice-list">
                {items.map((e) => (
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
            {prepareLink ? (
                <p>
                    <Link className="authoring-button" to={`${base}/new`}>
                        Prepare an encounter
                    </Link>
                </p>
            ) : null}
        </>
    )
}
