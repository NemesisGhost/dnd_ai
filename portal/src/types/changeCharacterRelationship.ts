// Request/response shape for
// POST /campaigns/{campaignId}/character-relationships/{membershipCharacterRelationshipId}/change
// (character-relationship-management checkpoint).
export interface ChangeCharacterRelationshipRequest {
    new_relationship_type_id: string
}

export interface ChangeCharacterRelationshipResponse {
    membership_character_relationship_id: string
}
