import type { ReactNode } from "react"
import { useCampaignSessions } from "../hooks/useCampaignSessions"
import type {
    CampaignSessionListItem,
} from "../types/campaignSession"
import PlaceholderPage from "../pages/PlaceholderPage"

interface CampaignSessionsBoundaryProps {
    campaignId: string
    children: (
        sessions: CampaignSessionListItem[],
    ) => ReactNode
}

export function CampaignSessionsBoundary({
    campaignId,
    children,
}: CampaignSessionsBoundaryProps) {
    const { state, retry } =
        useCampaignSessions(campaignId)

    if (state.status === "loading") {
        return (
            <PlaceholderPage
                title="Loading sessions"
                description="Loading the latest authorized session history."
            />
        )
    }

    if (state.status === "unavailable") {
        return (
            <PlaceholderPage
                title="Sessions unavailable"
                description="The requested session information is not available."
            />
        )
    }

    if (state.status === "error") {
        return (
            <section
                className="placeholder-page"
                aria-labelledby="sessions-error-heading"
            >
                <h1 id="sessions-error-heading">
                    Sessions unavailable
                </h1>

                <p>
                    The portal could not load the session history.
                    Try again.
                </p>

                <button
                    type="button"
                    onClick={retry}
                >
                    Try again
                </button>
            </section>
        )
    }

    return <>{children(state.sessions)}</>
}