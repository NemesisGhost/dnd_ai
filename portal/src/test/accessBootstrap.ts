import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { SessionBootstrap } from "../types/bootstrap"

// A session whose caller holds `access.manage` on each named campaign, for tests of the Access page. The page
// is bound to the applied session's capability for the route's campaign (O-5-R1), so a campaign the bootstrap
// does not list, or lists without the capability, shows "Access unavailable" and reads nothing.
export function bootstrapWithAccessManage(...campaignIds: string[]): SessionBootstrap {
    return {
        ...sessionBootstrapFixture,
        campaigns: campaignIds.map((campaignId) => ({
            ...sessionBootstrapFixture.campaigns[0],
            campaign_id: campaignId,
            capabilities: ["access.manage"],
        })),
    }
}
