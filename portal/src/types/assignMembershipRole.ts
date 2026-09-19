// Request/response shape for
// POST /campaigns/{campaignId}/memberships/{campaignMembershipId}/roles
// (Phase 13E-B checkpoint 2 — "Add role").
export interface AssignMembershipRoleRequest {
    role_id: string
}

export interface AssignMembershipRoleResponse {
    membership_role_id: string
}
