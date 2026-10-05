import { Link } from "react-router"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import "./authoring/authoring.css"

// Game-master tools on Campaign Home. Offered only to people the bootstrap lists
// `canon.edit` for; every destination re-authorizes on the server. Later Phase 15
// checkpoints add their entry points here (sessions, parties, the clock, events).
export function GmToolsCard({ campaignId }: { campaignId: string }) {
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    if (!canEdit) return null
    const base = `/app/${encodeURIComponent(campaignId)}`
    return (
        <section className="authoring-aside" aria-labelledby="gm-tools-heading">
            <h2 id="gm-tools-heading">Game master tools</h2>
            <ul>
                <li>
                    <Link to={`${base}/world-times`}>World times</Link>
                </li>
                <li>
                    <Link to={`${base}/parties`}>Parties</Link>
                </li>
                <li>
                    <Link to={`${base}/events/new`}>Record an event</Link>
                </li>
            </ul>
        </section>
    )
}
