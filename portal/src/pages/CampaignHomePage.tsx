import { useParams } from "react-router"
import { CampaignSummaryBoundary } from "../layouts/CampaignSummaryBoundary"
import { HomePage } from "./HomePage"
import PlaceholderPage from "./PlaceholderPage"

export function CampaignHomePage() {
  const { campaignId } =
    useParams<{ campaignId: string }>()

  if (campaignId === undefined) {
    return (
      <PlaceholderPage
        title="Campaign information unavailable"
        description="The requested campaign information is unavailable or you do not have access to it."
      />
    )
  }

  return (
    <CampaignSummaryBoundary
      campaignId={campaignId}
    >
      {(summary) => (
        <HomePage summary={summary} />
      )}
    </CampaignSummaryBoundary>
  )
}