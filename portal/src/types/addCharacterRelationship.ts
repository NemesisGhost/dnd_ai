// Request/response shape for
// POST /campaigns/{campaignId}/memberships/{campaignMembershipId}/character-relationships
// (character-relationship-management checkpoint).
export interface AddCharacterRelationshipRequest {
    character_id: string
    relationship_type_code: string
}

export interface AddCharacterRelationshipResponse {
    membership_character_relationship_id: string
}
