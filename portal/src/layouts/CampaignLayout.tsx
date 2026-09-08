import {
  Outlet,
  useLocation,
  useNavigate,
  useParams,
} from 'react-router'
import { AppNavigation } from '../components/AppNavigation'
import { CampaignContextPanel } from '../components/CampaignContextPanel'
import { usePerspective } from '../context/CharacterPerspectiveContext'
import PlaceholderPage from '../pages/PlaceholderPage'
import type { SessionBootstrap } from '../types/bootstrap'

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

  if (!campaign) {
    return (
      <main className="app-main">
        <PlaceholderPage
          title="Campaign not found"
          description="The requested campaign is unavailable or you do not have access to it."
        />
      </main>
    )
  }

  // Local alias so the narrowed (non-null) value is visible inside the
  // change handler closure below.
  const activeCampaign = campaign
  const showAccess = activeCampaign.capabilities.includes('access.manage')
  const selectedCharacterId = getSelectedCharacterId(
    activeCampaign.campaign_id,
  )

  function handleSelectCampaign(nextCampaignId: string) {
    if (nextCampaignId === activeCampaign.campaign_id) {
      return
    }

    // A higher selection changed: start the target campaign with no character
    // rather than falling back to its server default.
    selectCharacter(nextCampaignId, null)

    // Preserve the current top-level section, discard any detail id below it
    // (/app/<id>/<section>/<detail> -> /app/<next>/<section>).
    const section = location.pathname.split('/')[3] || 'home'
    navigate(`/app/${nextCampaignId}/${section}`)
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
