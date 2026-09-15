import { useParams } from "react-router"
import { CampaignSessionsBoundary } from "../components/CampaignSessionsBoundary"
import { SessionsPage } from "./SessionsPage"
import PlaceholderPage from "./PlaceholderPage"

export function CampaignSessionsPage() {
    const { campaignId } =
        useParams<{ campaignId: string }>()

    if (campaignId === undefined) {
        return (
            <PlaceholderPage
                title="Sessions unavailable"
                description="The requested session information is not available."
            />
        )
    }

    return (
        <CampaignSessionsBoundary campaignId={campaignId}>
            {(sessions) => (
                <SessionsPage sessions={sessions} />
            )}
        </CampaignSessionsBoundary>
    )
}