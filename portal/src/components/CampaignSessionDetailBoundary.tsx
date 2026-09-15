import type { ReactNode } from "react"
import { useCampaignSession } from "../hooks/useCampaignSession"
import PlaceholderPage from "../pages/PlaceholderPage"
import type {
    CampaignSessionDetail,
} from "../types/campaignSession"

interface CampaignSessionDetailBoundaryProps {
    campaignId: string
    sessionId: string
    children: (
        session: CampaignSessionDetail,
    ) => ReactNode
}

export function CampaignSessionDetailBoundary({
    campaignId,
    sessionId,
    children,
}: CampaignSessionDetailBoundaryProps) {
    const { state, retry } = useCampaignSession(
        campaignId,
        sessionId,
    )

    if (state.status === "loading") {
        return (
            <PlaceholderPage
                title="Loading session"
                description="Loading the latest authorized session information."
            />
        )
    }

    if (state.status === "unavailable") {
        return (
            <PlaceholderPage
                title="Session unavailable"
                description="The requested session information is not available."
            />
        )
    }

    if (state.status === "error") {
        return (
            <section
                className="placeholder-page"
                aria-labelledby="session-error-heading"
            >
                <h1 id="session-error-heading">
                    Session information unavailable
                </h1>

                <p>
                    The portal could not load the session information.
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

    return <>{children(state.session)}</>
}