// Response shape for
// POST /campaigns/{campaignId}/memberships/roles/{membershipRoleId}/revoke
// (Phase 13E-B checkpoint 2 — "Revoke role"). No request body: the target
// is named entirely by the URL.
export interface RevokeMembershipRoleResponse {
    membership_role_id: string
}
