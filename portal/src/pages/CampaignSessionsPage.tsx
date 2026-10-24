import { useParams } from "react-router"
import { CampaignSessionsBoundary } from "../components/CampaignSessionsBoundary"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { SessionsPage } from "./SessionsPage"
import PlaceholderPage from "./PlaceholderPage"

export function CampaignSessionsPage() {
    const { campaignId } =
        useParams<{ campaignId: string }>()

    const canSchedule = useCampaignCapability(campaignId ?? "", "canon.edit")

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
                <SessionsPage sessions={sessions} canSchedule={canSchedule} />
            )}
        </CampaignSessionsBoundary>
    )
}
