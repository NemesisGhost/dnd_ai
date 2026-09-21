// Request/response shapes for the Phase 13E-B checkpoint 6 access-group
// lifecycle/membership routes (dnd_ai.api.access_groups).

export interface CreateAccessGroupRequest {
    name: string
    description: string | null
}

export interface UpdateAccessGroupRequest {
    name: string
    description: string | null
}

export interface AccessGroupResponse {
    access_group_id: string
    name: string
}

export interface AddAccessGroupMemberRequest {
    campaign_membership_ids: string[]
    campaign_membership_id?: string
}

export interface AccessGroupMembershipResponse {
    access_group_membership_ids: string[]
    added_count: number
}
