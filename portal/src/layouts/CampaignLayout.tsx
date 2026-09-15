import {
  Outlet,
  useLocation,
  useNavigate,
  useParams,
} from "react-router"
import { AppNavigation } from "../components/AppNavigation"
import { CampaignContextPanel } from "../components/CampaignContextPanel"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import PlaceholderPage from "../pages/PlaceholderPage"
import type { SessionBootstrap } from "../types/bootstrap"
import { buildCampaignSelectionPath } from "../utils/campaignNavigation"

interface CampaignLayoutProps {
  bootstrap: SessionBootstrap
}

export function CampaignLayout({ bootstrap }: CampaignLayoutProps) {
  const { campaignId } = useParams<{ campaignId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const { getSelectedCharacterId, selectCharacter } = usePerspective()

  const campaign =
    bootstrap.campaigns.find(
      (candidate) => candidate.campaign_id === campaignId,
    ) ?? null

  if (campaign === null) {
    return (
      <main className="app-main">
        <PlaceholderPage
          title="Campaign not found"
          description="The requested campaign is unavailable or you do not have access to it."
        />
      </main>
    )
  }

  const activeCampaign = campaign
  const showAccess = activeCampaign.capabilities.includes('access.manage')
  const selectedCharacterId = getSelectedCharacterId(activeCampaign.campaign_id)

  function handleSelectCampaign(nextCampaignId: string): void {
    if (nextCampaignId === activeCampaign.campaign_id) {
      return
    }

    const targetCampaign =
      bootstrap.campaigns.find(
        (candidate) =>
          candidate.campaign_id ===
          nextCampaignId,
      )

    if (targetCampaign === undefined) {
      return
    }

    const destination =
      buildCampaignSelectionPath({
        pathname: location.pathname,
        targetCampaign,
        askEnabled: bootstrap.features.ask,
      })

    selectCharacter(
      targetCampaign.campaign_id,
      null,
    )

    navigate(destination)
  }

  return (
    <>
      <AppNavigation
        campaignId={activeCampaign.campaign_id}
        askEnabled={bootstrap.features.ask}
        showAccess={showAccess}
      />

      <main className="app-main campaign-workspace">
        <CampaignContextPanel
          campaign={activeCampaign}
          campaigns={bootstrap.campaigns}
          selectedCharacterId={selectedCharacterId}
          onSelectCampaign={handleSelectCampaign}
          onSelectCharacter={(characterId) =>
            selectCharacter(activeCampaign.campaign_id, characterId)
          }
        />

        <div className="campaign-workspace__content">
          <Outlet />
        </div>
      </main>
    </>
  )
}
