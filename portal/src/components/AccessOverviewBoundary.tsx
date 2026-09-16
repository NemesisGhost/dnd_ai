import type { ReactNode } from "react"
import { useAccessOverview } from "../hooks/useAccessOverview"
import PlaceholderPage from "../pages/PlaceholderPage"
import type {
    CampaignAccessOverview,
} from "../types/accessOverview"

interface AccessOverviewBoundaryProps {
    campaignId: string
    children: (
        overview: CampaignAccessOverview,
    ) => ReactNode
}

export function AccessOverviewBoundary({
    campaignId,
    children,
}: AccessOverviewBoundaryProps) {
    const { state, retry } = useAccessOverview(
        campaignId,
    )

    if (state.status === "loading") {
        return (
            <PlaceholderPage
                title="Loading access"
                description="Loading the campaign's current access information."
            />
        )
    }

    if (state.status === "unavailable") {
        return (
            <PlaceholderPage
                title="Access unavailable"
                description="The requested access information is not available."
            />
        )
    }

    if (state.status === "error") {
        return (
            <section
                className="placeholder-page"
                aria-labelledby="access-error-heading"
            >
                <h1 id="access-error-heading">
                    Access information unavailable
                </h1>

                <p>
                    The portal could not load the campaign's access
                    information. Try again.
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

    return <>{children(state.overview)}</>
}
