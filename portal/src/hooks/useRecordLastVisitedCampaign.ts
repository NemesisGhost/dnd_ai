import { useEffect } from "react"
import { recordLastVisitedCampaign } from "../api/userPreferences"
import type { SessionBootstrap } from "../types/bootstrap"

// Records the campaign the user has just entered as their durable
// "last visited" campaign (docs/UI_DESIGN.md §4.7).
//
// `campaignId` must be a campaign that has already passed the portal's
// authorization boundary (it is in the *current* scope's bootstrap) --
// pass null otherwise, so an unauthorized route attempt is never recorded.
// The server re-verifies authorization regardless; the stored value is
// presentation state and never grants access.
//
// Fire-and-forget by design: no reload (that would unmount the page), no
// retry, no user-visible error. The write is not aborted when the page is left
// (an abandoned request may or may not commit, and the next bootstrap read
// would then report an older campaign); writes are ordered instead, so the
// latest selection wins, and the response updates no state.
export function useRecordLastVisitedCampaign(
    campaignId: string | null,
    bootstrap: SessionBootstrap,
): void {
    const alreadyRecorded =
        bootstrap.campaign_preferences.last_visited_campaign_id === campaignId
    const csrfToken = bootstrap.csrf_token
    const browserSessionId = bootstrap.browser_session_id

    useEffect(() => {
        if (campaignId === null || alreadyRecorded) {
            return
        }

        recordLastVisitedCampaign(campaignId, csrfToken).catch(() => {
            // Intentionally ignored.
        })
        // browserSessionId re-keys the write when the session changes.
    }, [campaignId, alreadyRecorded, csrfToken, browserSessionId])
}
