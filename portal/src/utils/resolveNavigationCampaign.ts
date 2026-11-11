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
// (docs/UI_DESIGN.md §4.5, §4.8). Precedence, most to least authoritative:
//
//   1. the route campaign, when it is in the current bootstrap. A route that
//      names a campaign the bootstrap does not contain (unknown, revoked,
//      unauthorized) resolves nothing -- the ID is never used or echoed and a
//      retained selection never stands in for it;
//   2. a route that names a world (and possibly a timeline): the person's
//      selected campaign, only when it belongs to that confirmed world and
//      timeline. An explicit destination that is not confirmed (still loading,
//      unknown, denied, or failed world; unknown or unauthorized timeline)
//      resolves nothing;
//   3. otherwise (an unscoped route): the person's selected campaign.
//
// The selected campaign is the explicit selection this tab retains
// (navigation/selectedContextStore.ts). There is no fallback to the last-visited or
// startup campaign and no guess from a world's only campaign: with nothing selected the
// sidebar shows its campaign-specific entries as disabled ("Select a campaign first").
// Those preferences remain inputs of the /home landing only. Every candidate must be present
// in `bootstrap.campaigns`; an ID that is not (revoked, unknown) is treated as absent, so a
// link is never built from a stale or unauthorized campaign ID.
export function resolveNavigationCampaign(
    bootstrap: SessionBootstrap,
    routeCampaignId: string | undefined,
    worldScope: NavigationWorldScope | null = null,
    selectedCampaignId: string | null = null,
): CampaignContext | null {
    const find = (id: string | null | undefined): CampaignContext | null =>
        id === null || id === undefined
            ? null
            : (bootstrap.campaigns.find((campaign) => campaign.campaign_id === id) ?? null)

    const routeCampaign = find(routeCampaignId)
    if (routeCampaign !== null) {
        return routeCampaign
    }
    if (routeCampaignId !== undefined) {
        return null
    }

    const selected = find(selectedCampaignId)
    if (worldScope?.routeNamesWorld === true) {
        if (
            selected === null ||
            worldScope.activeWorldId === null ||
            (worldScope.routeNamesTimeline && worldScope.activeTimelineId === null)
        ) {
            return null
        }
        return selected.world_id === worldScope.activeWorldId &&
            (worldScope.activeTimelineId === null || selected.timeline_id === worldScope.activeTimelineId)
            ? selected
            : null
    }

    return selected
}
