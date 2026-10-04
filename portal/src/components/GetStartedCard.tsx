import { Link } from "react-router"
import "./authoring/authoring.css"

interface GetStartedCardProps {
    campaignId: string
}

// Shown on an empty Campaign Home to campaign managers only (the caller decides
// from the bootstrap's `access.manage` and the empty summary). It points at the
// next real steps; nothing here requires an AI provider or a VTT.
export function GetStartedCard({ campaignId }: GetStartedCardProps) {
    return (
        <section className="authoring-aside" aria-labelledby="get-started-heading">
            <h2 id="get-started-heading">Get started</h2>
            <p>This campaign is ready. A few good first steps:</p>
            <ul>
                <li>
                    <Link to={`/app/${campaignId}/access/invitations`}>Invite players</Link>
                </li>
                <li>
                    <Link to={`/app/${campaignId}/settings`}>Review campaign settings</Link>
                </li>
                <li>
                    <Link to="/worlds">Manage your worlds and timelines</Link>
                </li>
            </ul>
        </section>
    )
}
