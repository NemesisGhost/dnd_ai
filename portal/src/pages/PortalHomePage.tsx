import { Link } from "react-router"
import type { SessionBootstrap } from "../types/bootstrap"
import { humanizeCode } from "../utils/humanize"

interface PortalHomePageProps {
    bootstrap: SessionBootstrap
}

// At most this many campaigns are listed directly on the landing page;
// the rest are reachable through "View all campaigns" (UI_DESIGN §5.2a,
// navigation plan §5, decision D-6).
const HOME_CAMPAIGN_LIMIT = 6

// Global landing page. Receives bootstrap from the authenticated outlet
// context and makes no network requests of its own — every value here
// comes from the current session bootstrap, which every campaign-scope
// change already refreshes.
export function PortalHomePage({ bootstrap }: PortalHomePageProps) {
    const displayName = bootstrap.user.display_name
    const hasUsableName = displayName.trim().length > 0

    const defaultCampaign =
        bootstrap.startup_campaign_id === null
            ? null
            : bootstrap.campaigns.find(
                (campaign) =>
                    campaign.campaign_id === bootstrap.startup_campaign_id,
            ) ?? null

    const visibleCampaigns = bootstrap.campaigns.slice(
        0,
        HOME_CAMPAIGN_LIMIT,
    )

    const hasCampaigns = bootstrap.campaigns.length > 0

    return (
        <main className="app-main">
            <section
                className="portal-home"
                aria-labelledby="portal-home-heading"
            >
                <h1 id="portal-home-heading">Home</h1>

                {hasUsableName && <p>Welcome, {displayName}.</p>}

                {defaultCampaign !== null && (
                    <section
                        className="portal-home__section"
                        aria-labelledby="portal-home-default-heading"
                    >
                        <h2 id="portal-home-default-heading">
                            Default campaign
                        </h2>
                        <p>
                            <Link
                                to={`/app/${defaultCampaign.campaign_id}/home`}
                            >
                                Open default campaign
                                {": "}
                                {defaultCampaign.campaign_name}
                            </Link>
                        </p>
                    </section>
                )}

                {hasCampaigns ? (
                    <section
                        className="portal-home__section"
                        aria-labelledby="portal-home-campaigns-heading"
                    >
                        <h2 id="portal-home-campaigns-heading">
                            Your campaigns
                        </h2>

                        <ul className="portal-home__campaign-list">
                            {visibleCampaigns.map((campaign) => (
                                <li key={campaign.campaign_id}>
                                    <Link
                                        className="portal-home__campaign-link"
                                        to={`/app/${campaign.campaign_id}/home`}
                                    >
                                        <span className="portal-home__campaign-name">
                                            {campaign.campaign_name}
                                        </span>

                                        {campaign.world_name !== null && (
                                            <span>{campaign.world_name}</span>
                                        )}

                                        <span>
                                            {campaign.timeline_name ??
                                                "No timeline selected"}
                                        </span>

                                        {campaign.roles.length > 0 && (
                                            <span>
                                                {campaign.roles
                                                    .map((role) =>
                                                        humanizeCode(role),
                                                    )
                                                    .join(", ")}
                                            </span>
                                        )}

                                        {campaign.campaign_id ===
                                            bootstrap.startup_campaign_id && (
                                            <span>Default campaign</span>
                                        )}
                                    </Link>
                                </li>
                            ))}
                        </ul>

                        <p>
                            <Link to="/campaigns">
                                View all campaigns ({bootstrap.campaigns.length})
                            </Link>
                        </p>
                    </section>
                ) : (
                    <section
                        className="portal-home__section"
                        aria-labelledby="portal-home-empty-heading"
                    >
                        <h2 id="portal-home-empty-heading">
                            Your campaigns
                        </h2>

                        <p>
                            You do not have access to any campaigns yet.
                        </p>

                        <p>
                            <Link to="/campaigns">Browse campaigns</Link>
                        </p>

                        <p>
                            <Link to="/campaign-invitations/accept">
                                Accept a campaign invitation
                            </Link>
                        </p>
                    </section>
                )}

                <section
                    className="portal-home__section"
                    aria-labelledby="portal-home-account-heading"
                >
                    <h2 id="portal-home-account-heading">Account</h2>

                    <ul className="portal-home__account-list">
                        <li>
                            <Link to="/account">Your account</Link>
                        </li>

                        {bootstrap.is_platform_administrator && (
                            <li>
                                <Link to="/platform/accounts">
                                    Platform accounts
                                </Link>
                            </li>
                        )}
                    </ul>
                </section>
            </section>
        </main>
    )
}
