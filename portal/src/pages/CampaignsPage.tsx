import { Link } from "react-router"
import { ArchivedCampaignsSection } from "../components/ArchivedCampaignsSection"
import type { SessionBootstrap } from "../types/bootstrap"

interface CampaignsPageProps {
  bootstrap: SessionBootstrap
}

export function CampaignsPage({
  bootstrap,
}: CampaignsPageProps) {
  const canCreate =
    bootstrap.global_capabilities?.includes("world.create") === true
  const createLink = canCreate ? (
    <p>
      <Link to="/campaigns/new">Create campaign</Link>
    </p>
  ) : null

  if (bootstrap.campaigns.length === 0) {
    return (
      <main className="app-main">
        <section className="placeholder-page">
          <h1>Campaigns</h1>
          <p>
            You do not have access to any campaigns yet. Ask a GM to invite
            you.
          </p>
          <p>
            <Link to="/campaign-invitations/accept">
              Accept a campaign invitation
            </Link>
          </p>
          {createLink}
          {canCreate && <ArchivedCampaignsSection />}
        </section>
      </main>
    )
  }

  return (
    <main className="app-main">
      <section className="placeholder-page">
        <h1>Campaigns</h1>
        <p>Select a campaign to continue.</p>
        {createLink}

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
                  bootstrap.campaign_preferences.preferred_campaign_id ? (
                  <span>Opens at sign-in</span>
                ) : campaign.campaign_id ===
                  bootstrap.campaign_preferences.last_visited_campaign_id ? (
                  <span>Last visited</span>
                ) : null}
              </Link>
            </li>
          ))}
        </ul>
        {canCreate && <ArchivedCampaignsSection />}
      </section>
    </main>
  )
}