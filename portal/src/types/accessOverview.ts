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

export interface AssignableCharacter {
    character_id: string
    display_name: string
}

export interface AssignableCharacterRelationshipType {
    character_relationship_type_id: string
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
    // Identity only, never rendered as page text — used to detect an
    // exact active duplicate (target, capability, effect) combination
    // when adding a new grant, matching character_id's own identical
    // contract on AccessCharacterRelationshipSummary.
    target_id: string
    // Populated only for a "character" target_type — resolved server-side
    // from core.entities.canonical_name, the identical safe display name
    // character_relationships already uses. null for every other target
    // kind (checkpoint 5's own portal scope is limited to character
    // targets — see dnd_ai.commands.access_grants' module docstring).
    target_display_name: string | null
    reason: string | null
    granted_at: string
    expires_at: string | null
}

export interface GrantableResourceCapability {
    capability_id: string
    code: string
    display_name: string
    target_type: string
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

export interface AccessGroupMemberSummary {
    access_group_membership_id: string
    campaign_membership_id: string
    display_name: string
    added_at: string
}

// Phase 13E-B checkpoint 6. Shares AccessResourceGrantSummary's exact shape
// (a group-owned grant and a member-owned grant are the same underlying
// security.resource_grants row, differing only in which grantee column is
// non-null) — reused rather than duplicated below.
export interface AccessGroupSummary {
    access_group_id: string
    name: string
    description: string | null
    // "active" | "archived" (core.lifecycle_statuses codes this checkpoint's
    // own commands ever write).
    status_code: string
    status_display_name: string
    created_at: string
    members: AccessGroupMemberSummary[]
    grants: AccessResourceGrantSummary[]
}

export interface CampaignAccessOverview {
    members: CampaignAccessMember[]
    assignable_roles: AssignableRole[]
    assignable_characters: AssignableCharacter[]
    assignable_relationship_types: AssignableCharacterRelationshipType[]
    grantable_resource_capabilities: GrantableResourceCapability[]
    access_groups: AccessGroupSummary[]
}
