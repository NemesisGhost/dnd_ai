import type { CampaignContext, SessionBootstrap } from "../types/bootstrap"

// The World → Timeline selection the active route establishes, as confirmed by
// the workspace hierarchy provider (never a raw route ID).
export interface NavigationWorldScope {
    // The route names a concrete world / timeline (confirmed or not).
    routeNamesWorld: boolean
    routeNamesTimeline: boolean
    // The server-confirmed world and timeline, null until confirmed.
    activeWorldId: string | null
    activeTimelineId: string | null
}

// The campaign the persistent sidebar's campaign-specific links target
// (docs/UI_DESIGN.md §4.5). Precedence, most to least authoritative:
//
//   1. the route campaign, when it is in the current bootstrap;
//   2. a route that names a world (and possibly a timeline): a campaign of
//      that confirmed world and timeline only -- saved last-visited, then
//      startup, then the world's only campaign, else none. An explicit
//      destination that is not confirmed (still loading, unknown, denied, or
//      failed world; unknown or unauthorized timeline) resolves nothing: a
//      saved campaign never stands in for it;
//   3. otherwise (no world in the route): the last-visited campaign, then the
//      startup campaign.
//
// Every candidate must be present in `bootstrap.campaigns`; an ID that is
// not (unknown route, stale preference) is treated as absent, so a link is
// never built from a guessed, stale, or unauthorized campaign ID. Saved
// preferences are fallbacks only: they never override a campaign or world the
// route selects. Returns null when nothing resolves, and the sidebar then
// shows its campaign-specific entries as disabled.
export function resolveNavigationCampaign(
    bootstrap: SessionBootstrap,
    routeCampaignId: string | undefined,
    worldScope: NavigationWorldScope | null = null,
): CampaignContext | null {
    const find = (
        id: string | null | undefined,
        pool: readonly CampaignContext[] = bootstrap.campaigns,
    ): CampaignContext | null =>
        id === null || id === undefined
            ? null
            : (pool.find((campaign) => campaign.campaign_id === id) ?? null)

    const routeCampaign = find(routeCampaignId)
    if (routeCampaign !== null) {
        return routeCampaign
    }

    if (worldScope?.routeNamesWorld === true) {
        if (
            worldScope.activeWorldId === null ||
            (worldScope.routeNamesTimeline && worldScope.activeTimelineId === null)
        ) {
            return null
        }
        const inScope = bootstrap.campaigns.filter(
            (campaign) =>
                campaign.world_id === worldScope.activeWorldId &&
                (worldScope.activeTimelineId === null ||
                    campaign.timeline_id === worldScope.activeTimelineId),
        )
        return (
            find(bootstrap.campaign_preferences.last_visited_campaign_id, inScope) ??
            find(bootstrap.startup_campaign_id, inScope) ??
            (inScope.length === 1 ? inScope[0]! : null)
        )
    }

    return (
        find(bootstrap.campaign_preferences.last_visited_campaign_id) ??
        find(bootstrap.startup_campaign_id)
    )
}
