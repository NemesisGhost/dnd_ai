import { Link } from "react-router"
import { ArchivedCampaignsSection } from "../components/ArchivedCampaignsSection"
import type { SessionBootstrap } from "../types/bootstrap"
import { canHostCampaigns } from "../utils/systemAccess"
import { canCreateWorlds } from "../utils/worldAccess"

interface CampaignsPageProps {
  bootstrap: SessionBootstrap
}

export function CampaignsPage({
  bootstrap,
}: CampaignsPageProps) {
  const canCreate = canCreateWorlds(bootstrap)
  // Campaign creation is a game master's action (system `campaign.host`, ADR 0020); the page
  // offers it only when the server says so, and the server re-checks on every request.
  const canHost = canHostCampaigns(bootstrap)
  const createLink = canHost ? (
    <p>
      <Link to="/campaigns/new">Create campaign</Link>
    </p>
  ) : null

  if (bootstrap.campaigns.length === 0) {
    return (
      <main className="app-main">
        <section className="placeholder-page">
          <h1>Campaigns</h1>
          {canCreate || canHost ? (
            <>
              <p>You are not in any campaigns yet.</p>
              {canCreate ? (
                <p>
                  <Link to="/worlds/new">Create a world</Link>
                </p>
              ) : null}
            </>
          ) : (
            <p>
              You do not have access to any campaigns yet. Ask a GM to invite
              you.
            </p>
          )}
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