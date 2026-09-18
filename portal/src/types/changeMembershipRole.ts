// Request/response shape for
// POST /campaigns/{campaignId}/memberships/roles/{membershipRoleId}/change
// (Phase 13E-B checkpoint 1).
export interface ChangeMembershipRoleRequest {
    new_role_id: string
}

export interface ChangeMembershipRoleResponse {
    membership_role_id: string
}
