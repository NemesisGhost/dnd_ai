import { Outlet, useParams } from 'react-router'
import { AppNavigation } from '../components/AppNavigation'
import { CampaignContextBar } from '../components/CampaignContextBar'
import PlaceholderPage from '../pages/PlaceholderPage'
import type { SessionBootstrap } from '../types/bootstrap'

interface CampaignLayoutProps {
  bootstrap: SessionBootstrap
}

export function CampaignLayout({ bootstrap }: CampaignLayoutProps) {
  const { campaignId } = useParams<{ campaignId: string }>()

  const campaign =
    bootstrap.campaigns.find(
      (candidate) => candidate.campaignId === campaignId,
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

  const showAccess = campaign.roles.includes('Game Master')

  return (
    <>
      <CampaignContextBar campaign={campaign} />

      <AppNavigation
        campaignId={campaign.campaignId}
        askEnabled={bootstrap.features.ask}
        showAccess={showAccess}
      />

      <main className="app-main">
        <Outlet />
      </main>
    </>
  )
}