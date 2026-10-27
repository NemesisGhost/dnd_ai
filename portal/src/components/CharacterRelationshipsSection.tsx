import { useId, useState } from "react"
import { Link } from "react-router"
import { characterRelationshipsPath } from "../api/characterRelationships"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import type {
    CharacterRelationship,
    CharacterRelationships,
    ReaderRelationshipDetails,
    ReaderRelationshipParticipant,
} from "../types/characterRelationships"
import { periodSummary, readerCounterpartNames, readerRoleSentence } from "../utils/relationshipForm"
import { worldRecordPath } from "./world/worldPaths"

// The player-facing, read-only Relationships section on a character's page. It reads only the
// reader projection the server builds for this character; it never fetches an editor response and
// hides fields in the browser. Expanding a row sends nothing: every detail shown arrived with the
// list. Editors get nothing here (their roster is the World workspace's Relationships section), so
// the editor routes are never requested from this page.

const DETAIL_FACTS: ReadonlyArray<readonly [keyof ReaderRelationshipDetails, string]> = [
    ["family_unit_name", "Family"],
    ["job_title", "Job title"],
    ["office", "Office"],
    ["rank", "Rank"],
    ["distance_text", "Distance"],
    ["travel_time_text", "Travel time"],
    ["travel_mode", "Travel mode"],
]

function recordPath(campaignId: string, p: ReaderRelationshipParticipant): string | null {
    if (!p.can_open || p.category === null) return null
    if (p.category === "character") {
        return `/app/${encodeURIComponent(campaignId)}/characters/${encodeURIComponent(p.entity_id)}`
    }
    return worldRecordPath(campaignId, p.category, p.entity_id)
}

function Who({ campaignId, participant }: { campaignId: string; participant: ReaderRelationshipParticipant }) {
    const to = recordPath(campaignId, participant)
    return to === null ? <>{participant.name}</> : <Link to={to}>{participant.name}</Link>
}

// The counterpart names, each a link only where the server said the caller can open that record.
function CounterpartNames({ campaignId, item }: { campaignId: string; item: CharacterRelationship }) {
    const others = item.participants.filter((p) => !p.is_self)
    if (others.length === 0) return <>{readerCounterpartNames(item.participants)}</>
    return (
        <>
            {others.map((p, index) => (
                <span key={`${p.entity_id}:${p.role}`}>
                    {index > 0 ? " and " : ""}
                    <Who campaignId={campaignId} participant={p} />
                </span>
            ))}
        </>
    )
}

function Row({ campaignId, item }: { campaignId: string; item: CharacterRelationship }) {
    const [open, setOpen] = useState(false)
    const detailsId = useId()
    const label = `${item.relationship_type_label} with ${readerCounterpartNames(item.participants)}`
    const facts: Array<[string, string]> = [["Period", periodSummary(item)]]
    if (item.current_status_label) facts.push(["Timeline status", item.current_status_label])
    for (const [key, name] of DETAIL_FACTS) {
        const value = item.details[key]
        if (typeof value === "string" && value !== "") facts.push([name, value])
    }
    if (typeof item.details.ownership_share === "number") {
        facts.push(["Share", `${item.details.ownership_share}%`])
    }
    if (typeof item.details.in_force === "boolean") {
        facts.push(["In force", item.details.in_force ? "Yes" : "No"])
    }
    return (
        <li className="relationship-roster__row">
            <div className="relationship-roster__who">
                <span className="relationship-roster__name">
                    <CounterpartNames campaignId={campaignId} item={item} />
                </span>
                {item.period_status === "ended" ? <span className="relationship-roster__badge">Ended</span> : null}
                {item.period_status === "not_started" ? (
                    <span className="relationship-roster__badge">Not started</span>
                ) : null}
            </div>
            <p className="relationship-roster__clock">
                {item.relationship_type_label} · {readerRoleSentence(item.participants, item.symmetric)}
            </p>
            <div className="relationship-roster__actions">
                <button
                    type="button"
                    className="authoring-button"
                    aria-expanded={open}
                    aria-controls={detailsId}
                    onClick={() => setOpen((value) => !value)}
                >
                    Details <span className="visually-hidden">of {label}</span>
                </button>
            </div>
            {open ? (
                <div id={detailsId} className="relationship-roster__editor">
                    <dl className="relationship-roster__facts">
                        {facts.map(([name, value]) => (
                            <div key={name}>
                                <dt>{name}</dt>
                                <dd>{value}</dd>
                            </div>
                        ))}
                        <div>
                            <dt>Participants</dt>
                            <dd>
                                {item.participants.map((p, index) => (
                                    <span key={`${p.entity_id}:${p.role}`}>
                                        {index > 0 ? "; " : ""}
                                        <Who campaignId={campaignId} participant={p} /> ({p.role_label})
                                    </span>
                                ))}
                            </dd>
                        </div>
                    </dl>
                </div>
            ) : null}
        </li>
    )
}

function Reader({ campaignId, characterId }: { campaignId: string; characterId: string }) {
    const { state, refetch } = useAuthoringResource<CharacterRelationships>(
        characterRelationshipsPath(campaignId, characterId),
    )
    const headingId = "character-relationships-heading"
    const count = state.kind === "ready" && state.data.items.length > 0 ? ` (${state.data.items.length})` : ""
    return (
        <section aria-labelledby={headingId} className="character-relationships">
            <h2 id={headingId}>Relationships{count}</h2>
            {state.kind === "loading" ? <p role="status">Loading relationships…</p> : null}
            {state.kind === "error" ? (
                <div role="alert">
                    <p>Relationships could not be loaded.</p>
                    <button type="button" className="authoring-button" onClick={() => void refetch()}>
                        Try again
                    </button>
                </div>
            ) : null}
            {state.kind === "denied" || state.kind === "unavailable" ? (
                <div role="alert">
                    <p>Relationships could not be loaded.</p>
                </div>
            ) : null}
            {state.kind === "ready" && state.data.items.length === 0 ? <p>No visible relationships.</p> : null}
            {state.kind === "ready" && state.data.items.length > 0 ? (
                <>
                    <ul className="relationship-roster__list">
                        {state.data.items.map((item) => (
                            <Row key={item.relationship_id} campaignId={campaignId} item={item} />
                        ))}
                    </ul>
                    {state.data.truncated ? (
                        <p className="relationship-roster__empty">Only the first relationships are shown.</p>
                    ) : null}
                </>
            ) : null}
        </section>
    )
}

export function CharacterRelationshipsSection({
    campaignId,
    characterId,
}: {
    campaignId: string
    characterId: string
}) {
    // Editors manage relationships in the World workspace; mounting nothing here also sends nothing.
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    if (canEdit) return null
    return <Reader key={`${campaignId}:${characterId}`} campaignId={campaignId} characterId={characterId} />
}
