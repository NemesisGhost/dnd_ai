import { Link } from "react-router"
import PlaceholderPage from "./PlaceholderPage"
import type { SessionBootstrap } from "../types/bootstrap"

interface CampaignsPageProps {
  bootstrap: SessionBootstrap
}

export function CampaignsPage({
  bootstrap,
}: CampaignsPageProps) {
  if (bootstrap.campaigns.length === 0) {
    return (
      <main className="app-main">
        <PlaceholderPage
          title="Campaigns"
          description="You do not have access to any campaigns yet. Ask a GM to grant you access."
        />
      </main>
    )
  }

  return (
    <main className="app-main">
      <section className="placeholder-page">
        <h1>Campaigns</h1>
        <p>Select a campaign to continue.</p>

        <ul className="campaign-selection__list">
          {bootstrap.campaigns.map((campaign) => (
            <li
              key={campaign.campaign_id}
              className="campaign-selection__item"
            >
              <Link
                className="campaign-selection__link"
                to={`/app/${campaign.campaign_id}/home`}
              >
                <h2>{campaign.campaign_name}</h2>

                <p>
                  {campaign.timeline_name ??
                    "No timeline selected"}
                </p>

                {campaign.campaign_id ===
                  bootstrap.selected_campaign_id && (
                    <span>Default campaign</span>
                  )}
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </main>
  )
}