import type { SessionBootstrapState } from "../hooks/useSessionBootstrap"

const _ACCESS_MANAGE_CAPABILITY = "access.manage"

// Presentation only, never authorization: dnd_ai.api.preview's own
// require_campaign_capability(access.manage) is unaffected by this — it is
// the server, not this check, that actually authorizes every preview
// request. This just avoids showing a control that would only ever 404 for
// an actor whose own campaign membership never carries access.manage at
// all, matching the exact capability the server checks (checkpoint 15's own
// "presentation only, backend still authoritative" test requirement).
export function canPreviewAudience(
    sessionState: SessionBootstrapState,
    campaignId: string,
): boolean {
    return (
        sessionState.status === "authenticated" &&
        (sessionState.bootstrap.campaigns.find(
            (campaign) => campaign.campaign_id === campaignId,
        )?.capabilities.includes(_ACCESS_MANAGE_CAPABILITY) ??
            false)
    )
}
