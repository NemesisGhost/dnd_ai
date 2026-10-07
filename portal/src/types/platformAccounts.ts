export interface PlatformAccount {
    user_id: string
    display_name: string
    login_name: string | null
    lifecycle_status_code: string
    is_platform_administrator: boolean
    system_roles: string[]
    // Worlds this account owns that currently have no manageable owner (ADR 0020, F5).
    stranded_world_count?: number
    has_local_credential: boolean
    has_outstanding_activation: boolean
    last_login_at: string | null
    active_session_count: number
}

export interface PlatformAccountList {
    items: PlatformAccount[]
    next_cursor: string | null
}

export interface CreateAccountResponse {
    user_id: string
    login_name: string
    raw_activation_token: string
    expires_at: string
}

export interface IssuePasswordResetResponse {
    user_id: string
    raw_reset_token: string
    expires_at: string
}

export interface AccountLifecycleResponse {
    user_id: string
    previous_lifecycle_status: string
    new_lifecycle_status: string
}

export interface RevokeAllSessionsResponse {
    user_id: string
    revoked_count: number
}

export interface SystemRoleChangeResponse {
    user_id: string
    system_role_code: "admin" | "gm" | "player" | "observer"
    changed: boolean
}
