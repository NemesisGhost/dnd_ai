import { useParams } from "react-router"
import { AccessOverviewBoundary } from "../components/AccessOverviewBoundary"
import { AccessPage } from "./AccessPage"
import PlaceholderPage from "./PlaceholderPage"

export function CampaignAccessPage() {
    const { campaignId } =
        useParams<{ campaignId: string }>()

    if (campaignId === undefined) {
        return (
            <PlaceholderPage
                title="Access unavailable"
                description="The requested access information is not available."
            />
        )
    }

    return (
        <AccessOverviewBoundary campaignId={campaignId}>
            {(overview, retry) => (
                <AccessPage
                    campaignId={campaignId}
                    overview={overview}
                    onChanged={retry}
                />
            )}
        </AccessOverviewBoundary>
    )
}
