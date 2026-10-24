import { Link, useParams } from "react-router"
import { partyRosterPath } from "../api/parties"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { usePageArrival } from "../hooks/usePageArrival"
import type { PartyRoster } from "../types/parties"
import { PartyMembersPage } from "./PartyMembersPage"
import "../components/authoring/authoring.css"

// /app/:campaignId/parties/:partyId: the management page (members, history, inventory) for
// people who can edit canon; everyone else with campaign.view gets the read-only roster. The
// capability only chooses which page to offer — each endpoint re-checks on the server.
export function PartyDetailPage() {
    const { campaignId = "" } = useParams()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    return canEdit ? <PartyMembersPage /> : <PartyRosterPage />
}

function PartyRosterPage() {
    const { campaignId = "", partyId = "" } = useParams()
    const resource = useAuthoringResource<PartyRoster>(partyRosterPath(campaignId, partyId))
    const headingRef = usePageArrival(resource.state.kind === "ready")
    const data = resource.state.kind === "ready" ? resource.state.data : null

    return (
        <section className="authoring-page" aria-labelledby="roster-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={`/app/${encodeURIComponent(campaignId)}/parties`}>Parties</Link>
            </p>
            <h1 id="roster-heading" ref={headingRef} tabIndex={-1}>
                {data !== null ? data.party.name : "Party"}
            </h1>
            {resource.state.kind === "loading" ? (
                <p role="status">Loading party…</p>
            ) : resource.state.kind === "error" ? (
                <p role="alert">The party could not be loaded. Try reloading the page.</p>
            ) : data === null ? (
                <p role="alert">This party does not exist, or you do not have access to it.</p>
            ) : (
                <>
                    {data.party.description !== null ? <p>{data.party.description}</p> : null}
                    <section aria-labelledby="roster-members-heading">
                        <h2 id="roster-members-heading">Current members ({data.member_count})</h2>
                        {data.members.length === 0 ? (
                            <p>No current members.</p>
                        ) : (
                            <ul className="op-list">
                                {data.members.map((member) => (
                                    <li key={member.character_id}>{member.character_name}</li>
                                ))}
                            </ul>
                        )}
                    </section>
                </>
            )}
        </section>
    )
}
