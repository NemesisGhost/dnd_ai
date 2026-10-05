export interface CampaignSessionListItem {
    session_id: string
    session_number: number
    title: string | null
    status_code: string
    started_at: string | null
    ended_at: string | null
    // Phase 15.2D-1: the planned start and the derived play status.
    scheduled_for?: string | null
    play_status?: "unscheduled" | "scheduled" | "in_progress" | "completed"
    // Editors only.
    row_version?: number | null
    available_actions?: ("update" | "archive" | "restore")[] | null
}

export interface SessionReceipt {
    session_id: string
    session_number: number
    row_version: number
    created: boolean
    changed: boolean
}

export interface CampaignSessionEvent {
    event_id: string
    name: string
    summary: string | null
    event_type_code: string
    event_status_code: string
    world_time_id: string
    details: string | null
}

export interface CampaignSessionDetail
    extends CampaignSessionListItem {
    summary: string | null
    start_world_time_id: string | null
    end_world_time_id: string | null
    events: CampaignSessionEvent[]
}