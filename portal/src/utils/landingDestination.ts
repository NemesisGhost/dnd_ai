import type { SessionBootstrap } from "../types/bootstrap"

// Where the authenticated landing resolver (/home) sends the user
// (docs/UI_DESIGN.md §4.2, steps 2-6). The precedence itself — no
// campaigns, exactly one, a valid fixed preference, a valid last-visited
// campaign — is computed server-side into `startup_campaign_id`; this only
// turns it into a path, and re-checks it against the bootstrap's own
// campaign list so a stale or unauthorized ID can never be navigated to.
//
// Step 1 (an invitation/onboarding or other security continuation, or an
// accepted safe return destination) never reaches here: LoginPage handles
// it before ever navigating to /home.
export function resolveLandingPath(bootstrap: SessionBootstrap): string {
    const startupCampaignId = bootstrap.startup_campaign_id

    if (
        startupCampaignId !== null &&
        bootstrap.campaigns.some(
            (campaign) => campaign.campaign_id === startupCampaignId,
        )
    ) {
        return `/app/${startupCampaignId}/home`
    }

    return "/campaigns"
}
