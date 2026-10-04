import { Link, Outlet, useParams } from "react-router"
import { WorkspaceFrame } from "../components/WorkspaceFrame"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import { useRecordLastVisitedCampaign } from "../hooks/useRecordLastVisitedCampaign"
import PlaceholderPage from "../pages/PlaceholderPage"
import type { SessionBootstrap } from "../types/bootstrap"

interface CampaignLayoutProps {
  bootstrap: SessionBootstrap
}

export function CampaignLayout({ bootstrap }: CampaignLayoutProps) {
  const { campaignId } = useParams<{ campaignId: string }>()
  const { getSelectedCharacterId, selectCharacter } = usePerspective()

  const campaign =
    bootstrap.campaigns.find(
      (candidate) => candidate.campaign_id === campaignId,
    ) ?? null

  // Only a campaign found in the current scope's bootstrap has passed the
  // authorization boundary; an unknown/unauthorized route is never recorded.
  useRecordLastVisitedCampaign(campaign?.campaign_id ?? null, bootstrap)

  if (campaign === null) {
    return (
      <main className="app-main">
        <PlaceholderPage
          title="Campaign not found"
          description="The requested campaign is unavailable or you do not have access to it."
        />
        <p>
          <Link to="/campaigns">Browse campaigns</Link>
        </p>
      </main>
    )
  }

  const activeCampaign = campaign
  const selectedCharacterId = getSelectedCharacterId(activeCampaign.campaign_id)

  return (
    <WorkspaceFrame
      campaign={activeCampaign}
      selectedCharacterId={selectedCharacterId}
      onSelectCharacter={(characterId) =>
        selectCharacter(activeCampaign.campaign_id, characterId)
      }
    >
      <Outlet />
    </WorkspaceFrame>
  )
}
