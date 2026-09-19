// Request/response shape for POST /campaigns/{campaignId}/memberships
// (Phase 13E-B checkpoint 3 — "Add campaign member"). role_id is required:
// this route never creates a roleless membership.
export interface AddCampaignMemberRequest {
    user_id: string
    role_id: string
}

export interface AddCampaignMemberResponse {
    campaign_membership_id: string
    membership_role_id: string
}
