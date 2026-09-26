export interface AddResourceGrantRequest {
    capability_code: string
    effect: string
    grantee_campaign_membership_id: string
    character_id?: string
    entity_id?: string
    knowledge_item_id?: string
    quest_id?: string
    session_id?: string
    event_id?: string
}

export interface AddResourceGrantResponse {
    resource_grant_id: string
}
