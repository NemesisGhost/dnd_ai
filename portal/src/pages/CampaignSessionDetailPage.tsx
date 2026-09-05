import { useParams } from "react-router"
import {
    CampaignSessionDetailBoundary,
} from "../components/CampaignSessionDetailBoundary"
import { SessionDetailPage } from "./SessionDetailPage"
import PlaceholderPage from "./PlaceholderPage"

export function CampaignSessionDetailPage() {
    const {
        campaignId,
        sessionId,
    } = useParams<{
        campaignId: string
        sessionId: string
    }>()

    if (
        campaignId === undefined ||
        sessionId === undefined
    ) {
        return (
            <PlaceholderPage
                title="Session unavailable"
                description="The requested session information is not available."
            />
        )
    }

    return (
        <CampaignSessionDetailBoundary
            campaignId={campaignId}
            sessionId={sessionId}
        >
            {(session) => (
                <SessionDetailPage session={session} />
            )}
        </CampaignSessionDetailBoundary>
    )
}