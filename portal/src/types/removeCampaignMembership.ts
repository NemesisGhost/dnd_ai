// Response shape for
// POST /campaigns/{campaignId}/memberships/{campaignMembershipId}/end
// (Phase 13E-B checkpoint 3 — "Remove member"). No request body: the route
// path already carries everything the command needs.
export interface RemoveCampaignMembershipResponse {
    campaign_membership_id: string
}
