import { useParams } from "react-router"
import { GetStartedCard } from "../components/GetStartedCard"
import { useContext } from "react"
import { SessionContext } from "../context/SessionContext"
import { CampaignSummaryBoundary } from "../layouts/CampaignSummaryBoundary"
import { HomePage } from "./HomePage"
import PlaceholderPage from "./PlaceholderPage"
import type { CampaignSummary } from "../types/campaignSummary"

function isEmptyCampaign(summary: CampaignSummary): boolean {
  return (
    summary.current_session === null &&
    summary.previous_session_recap === null &&
    summary.recent_events.length === 0
  )
}

export function CampaignHomePage() {
  const { campaignId } =
    useParams<{ campaignId: string }>()

  // Read the session tolerantly: the Get-started card is an optional extra.
  const state = useContext(SessionContext)?.state
  const canManage =
    state?.status === "authenticated" &&
    state.bootstrap.campaigns
      .find((campaign) => campaign.campaign_id === campaignId)
      ?.capabilities.includes("access.manage") === true

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
        <>
          <HomePage summary={summary} />
          {isEmptyCampaign(summary) && canManage && (
            <GetStartedCard campaignId={campaignId} />
          )}
        </>
      )}
    </CampaignSummaryBoundary>
  )
}