export interface CampaignSessionListItem {
    session_id: string
    session_number: number
    title: string | null
    status_code: string
    started_at: string | null
    ended_at: string | null
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