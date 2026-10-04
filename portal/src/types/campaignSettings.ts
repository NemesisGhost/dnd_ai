import type { BlockedAction } from "./worldAuthoring"

export interface CampaignSettings {
    campaign_id: string
    name: string
    description: string | null
    lifecycle_status: "active" | "archived" | string
    row_version: number
    world: { world_id: string; name: string }
    timeline: { timeline_id: string; name: string }
    ruleset_version: {
        ruleset_version_id: string
        ruleset_display_name: string
        version_label: string
    }
    available_actions: string[]
    blocked_actions: BlockedAction[]
}

export interface ArchivedCampaign {
    campaign_id: string
    name: string
    world_name: string
    timeline_name: string
    row_version: number
}

export interface ArchivedCampaignListResponse {
    items: ArchivedCampaign[]
    next_cursor: string | null
}

export interface CreateCampaignRequest {
    timeline_id: string
    ruleset_version_id: string
    name: string
    description: string | null
}

export interface CreateCampaignResponse {
    campaign_id: string
    campaign_membership_id: string
}

export interface UpdateCampaignRequest {
    expected_row_version: number
    name: string
    description: string | null
}

export interface CampaignMutationResponse {
    campaign_id: string
    row_version: number
    lifecycle_status?: string
}
