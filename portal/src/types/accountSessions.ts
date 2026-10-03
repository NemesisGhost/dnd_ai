export interface OwnBrowserSession {
    browser_session_id: string
    created_at: string
    last_used_at: string
    idle_expires_at: string
    absolute_expires_at: string
    created_ip: string | null
    last_used_ip: string | null
    user_agent: string | null
    is_current: boolean
}
