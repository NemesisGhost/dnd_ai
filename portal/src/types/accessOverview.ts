export interface AccessRoleSummary {
    membership_role_id: string
    role_id: string
    code: string
    display_name: string
}

export interface AssignableRole {
    role_id: string
    code: string
    display_name: string
}

export interface AccessCharacterRelationshipSummary {
    membership_character_relationship_id: string
    character_id: string
    character_display_name: string
    relationship_type_code: string
    relationship_type_display_name: string
    granted_at: string
    expires_at: string | null
}

export interface AccessResourceGrantSummary {
    resource_grant_id: string
    capability_code: string
    capability_display_name: string
    effect: string
    target_type: string
    reason: string | null
    granted_at: string
    expires_at: string | null
}

export interface CampaignAccessMember {
    campaign_membership_id: string
    // Identity only, never rendered as page text — used only to detect
    // "this row is the caller's own membership" by comparing against
    // SessionBootstrap.user.user_id (self-removal messaging).
    user_id: string
    display_name: string
    status_code: string
    status_display_name: string
    joined_at: string
    roles: AccessRoleSummary[]
    character_relationships: AccessCharacterRelationshipSummary[]
    grants: AccessResourceGrantSummary[]
}

export interface CampaignAccessOverview {
    members: CampaignAccessMember[]
    assignable_roles: AssignableRole[]
}
