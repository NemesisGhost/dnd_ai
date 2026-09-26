// Request/response shapes for POST /campaigns/{campaignId}/resource-grants
// with a grantee_access_group_id grantee, mirroring
// ../types/addResourceGrant.ts's identical member-grantee shape.
export interface AddGroupResourceGrantRequest {
    capability_code: string
    effect: string
    grantee_access_group_id: string
    character_id?: string
    entity_id?: string
    knowledge_item_id?: string
    quest_id?: string
    session_id?: string
    event_id?: string
}

export interface AddGroupResourceGrantResponse {
    resource_grant_id: string
}
