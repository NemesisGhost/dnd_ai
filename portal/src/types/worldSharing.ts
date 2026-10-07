// World sharing (docs/adr/0020-scoped-system-world-and-campaign-roles.md): who holds a
// role on a world, who may host campaigns on it, and the published-canon browse a
// world Reader sees.

export type WorldRoleCode = "world_owner" | "world_editor" | "world_reviewer" | "world_reader"
export type RetainedWorldRoleCode = "world_editor" | "world_reviewer" | "world_reader"

export interface WorldRoleAssignment {
    world_membership_id: string
    user_id: string
    display_name: string
    role_code: WorldRoleCode | string
    role_display_name: string
    granted_at: string
    granted_by_display_name: string | null
    account_active: boolean
}

export interface WorldUseGrant {
    world_use_grant_id: string
    user_id: string
    display_name: string
    granted_at: string
    granted_by_display_name: string | null
    account_active: boolean
}

export interface WorldAccessView {
    assignments: WorldRoleAssignment[]
    use_grants: WorldUseGrant[]
    // True when the caller may add or remove Owners and transfer ownership.
    may_transfer: boolean
}

export interface AssignWorldRoleRequest {
    login_name: string
    role_code: WorldRoleCode
}

export interface TransferOwnershipRequest {
    login_name: string
    retain_previous_owner_as: RetainedWorldRoleCode | null
}

export interface WorldSharingChange {
    world_id: string
    user_id: string
    record_id: string | null
    role_code: string | null
    changed: boolean
}

export interface WorldTransferResult {
    world_id: string
    previous_owner_user_id: string
    new_owner_user_id: string
    retained_role_code: string | null
}

export interface WorldCanonItem {
    entity_id: string
    category: string
    name: string
    summary: string | null
}

export interface WorldCanonResponse {
    items: WorldCanonItem[]
    next_cursor: string | null
}

export const WORLD_ROLE_LABEL: Readonly<Record<string, string>> = {
    world_owner: "Owner",
    world_editor: "Editor",
    world_reviewer: "Reviewer",
    world_reader: "Reader",
}
