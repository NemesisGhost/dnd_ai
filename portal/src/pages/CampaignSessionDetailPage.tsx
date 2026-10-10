import { Navigate, useParams } from "react-router"
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
            {(session, refresh) => (
                <SessionDetailPage
                    key={session.session_id}
                    campaignId={campaignId}
                    session={session}
                    refresh={refresh}
                />
            )}
        </CampaignSessionDetailBoundary>
    )
}

// Old bookmarks to /sessions/:sessionId/edit land on the canonical page. The
// history entry is replaced so Back does not return to the retired URL.
export function LegacySessionEditRedirect() {
    const {
        campaignId,
        sessionId,
    } = useParams<{
        campaignId: string
        sessionId: string
    }>()

    return (
        <Navigate
            to={`/app/${encodeURIComponent(campaignId ?? "")}/sessions/${encodeURIComponent(sessionId ?? "")}`}
            replace
        />
    )
}
