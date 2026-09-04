import type { ReactNode } from "react"
import { useCampaignSummary } from "../hooks/useCampaignSummary"
import PlaceholderPage from "../pages/PlaceholderPage"
import type { CampaignSummary } from "../types/campaignSummary"

interface CampaignSummaryBoundaryProps {
    campaignId: string
    children: (
        summary: CampaignSummary,
    ) => ReactNode
}

export function CampaignSummaryBoundary({
    campaignId,
    children,
}: CampaignSummaryBoundaryProps) {
    const { state, retry } =
        useCampaignSummary(campaignId)

    switch (state.status) {
        case "loading":
            return (
                <PlaceholderPage
                    title="Loading campaign"
                    description="Loading the latest authorized campaign information."
                />
            )

        case "unavailable":
            return (
                <PlaceholderPage
                    title="Campaign information unavailable"
                    description="The requested campaign information is unavailable or you do not have access to it."
                />
            )

        case "error":
            return (
                <section
                    className="placeholder-page"
                    aria-labelledby="campaign-summary-error-heading"
                >
                    <h1 id="campaign-summary-error-heading">
                        Campaign information unavailable
                    </h1>

                    <p>
                        The latest campaign information could not be
                        loaded. No campaign summary has been displayed.
                    </p>

                    <button
                        type="button"
                        onClick={retry}
                    >
                        Try again
                    </button>
                </section>
            )

        case "success":
            return children(state.summary)
    }
}