import type { ReactNode } from "react"
import { useCampaignSession } from "../hooks/useCampaignSession"
import { sessionLabel } from "./sessionRun/sessionLabel"
import { useBreadcrumbLabel } from "../navigation/BreadcrumbLabelContext"
import PlaceholderPage from "../pages/PlaceholderPage"
import type {
    CampaignSessionDetail,
} from "../types/campaignSession"

interface CampaignSessionDetailBoundaryProps {
    campaignId: string
    sessionId: string
    children: (
        session: CampaignSessionDetail,
        refresh: () => Promise<boolean>,
    ) => ReactNode
}

export function CampaignSessionDetailBoundary({
    campaignId,
    sessionId,
    children,
}: CampaignSessionDetailBoundaryProps) {
    const { state, retry, refresh, authority } = useCampaignSession(
        campaignId,
        sessionId,
    )
    // The session's title, from this authorized read, for the breadcrumbs of the pages beneath it (Run,
    // an event or a character reached from it). An unavailable (403/404) answer drops it.
    useBreadcrumbLabel({
        route: "sessions.detail",
        params: { campaignId, sessionId },
        name: state.status === "success" ? sessionLabel(state.session) : undefined,
        denied: state.status === "unavailable",
        authority,
    })

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

    return <>{children(state.session, refresh)}</>
}