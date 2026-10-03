import type { CampaignContext, SessionBootstrap } from "../types/bootstrap"

// The campaign the persistent sidebar's campaign-specific links target
// (docs/UI_DESIGN.md §4.5). Resolution order:
//
//   1. the route campaign, when it is in the current bootstrap;
//   2. the (already authorization-filtered) last-visited campaign;
//   3. the server-computed startup campaign.
//
// Every candidate must be present in `bootstrap.campaigns`; an ID that is
// not (unknown route, stale preference) is treated as absent, so a link is
// never built from a guessed, stale, or unauthorized campaign ID. Returns
// null when nothing resolves, and the sidebar then omits campaign-specific
// links.
export function resolveNavigationCampaign(
    bootstrap: SessionBootstrap,
    routeCampaignId: string | undefined,
): CampaignContext | null {
    const find = (id: string | null | undefined): CampaignContext | null =>
        id === null || id === undefined
            ? null
            : (bootstrap.campaigns.find((campaign) => campaign.campaign_id === id) ??
              null)

    return (
        find(routeCampaignId) ??
        find(bootstrap.campaign_preferences.last_visited_campaign_id) ??
        find(bootstrap.startup_campaign_id)
    )
}
