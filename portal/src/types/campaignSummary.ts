// Response shape for the backend campaign-summary endpoint.
// JSON timestamps remain strings until explicitly parsed.

export interface CampaignSessionSummary {
    session_id: string
    session_number: number
    title: string | null
    status_code: string
    started_at: string | null
    ended_at: string | null
}

export interface RecentCampaignEvent {
    event_id: string
    name: string
    summary: string | null
    event_type_code: string
    event_status_code: string
    world_time_id: string
    details: string | null
}

export interface CampaignSummary {
    current_session: CampaignSessionSummary | null
    previous_session_recap: string | null
    recent_events: RecentCampaignEvent[]
}