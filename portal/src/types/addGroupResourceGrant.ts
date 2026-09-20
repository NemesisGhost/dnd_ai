// Request/response shapes for POST /campaigns/{campaignId}/resource-grants
// with a grantee_access_group_id grantee (Phase 13E-B checkpoint 6) —
// character-target, allow-effect only, mirroring
// ../types/addResourceGrant.ts's identical member-grantee shape.
export interface AddGroupResourceGrantRequest {
    capability_code: string
    effect: string
    grantee_access_group_id: string
    character_id: string
}

export interface AddGroupResourceGrantResponse {
    resource_grant_id: string
}
