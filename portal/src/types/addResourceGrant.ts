export interface AddResourceGrantRequest {
    capability_code: string
    effect: string
    grantee_campaign_membership_id: string
    character_id: string
}

export interface AddResourceGrantResponse {
    resource_grant_id: string
}
