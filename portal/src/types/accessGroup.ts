// Request/response shapes for the Phase 13E-B checkpoint 6 access-group
// lifecycle and membership routes.

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

export interface AddAccessGroupMembersRequest {
    campaign_membership_ids: string[]
}

export interface AddAccessGroupMembersResponse {
    access_group_membership_id: string | null
    access_group_membership_ids: string[]
    added_count: number
}

export interface RemoveAccessGroupMemberResponse {
    access_group_membership_id: string
}