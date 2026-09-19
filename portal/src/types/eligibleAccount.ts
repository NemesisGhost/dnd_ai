// Response shape for
// GET /campaigns/{campaignId}/eligible-accounts?login_name=...
// (Phase 13E-B checkpoint 3 — exact-match account lookup for "Add campaign
// member"). `account` is `null` for "no match, not eligible, or already a
// member" — all indistinguishable, matching the backend's own
// non-disclosure contract (dnd_ai.queries.access_overview.
// find_eligible_campaign_account).
export interface EligibleAccount {
    // Identity only, never rendered as page text — submitted back verbatim
    // as the add-member mutation's target user_id.
    user_id: string
    display_name: string
}

export interface EligibleAccountLookupResponse {
    account: EligibleAccount | null
}
