import type { BlockedAction, ManagedCampaign, TimelineSummary } from "./worldAuthoring"

export interface TimelineDetail extends TimelineSummary {
    children: TimelineSummary[]
    managed_campaigns: ManagedCampaign[]
    available_actions: string[]
    blocked_actions: BlockedAction[]
}

// A world time the parent's recorded history offers as a branch point. Only
// world-time data: never an event name or identifier.
export interface BranchPointOption {
    world_time_id: string
    label: string | null
    year: number | null
    month_number: number | null
    day: number | null
    sort_key: number
}

export interface BranchPointListResponse {
    items: BranchPointOption[]
    next_cursor: string | null
}

export interface CreateTimelineRequest {
    name: string
    description: string | null
}

export interface CreateTimelineResponse {
    timeline_id: string
    row_version: number
}

export interface UpdateTimelineRequest {
    expected_row_version: number
    name: string
    description: string | null
}

export interface TimelineMutationResponse {
    timeline_id: string
    row_version: number
    lifecycle_status?: string
}

export type BranchPointRequest =
    | { kind: "existing_world_time"; world_time_id: string }
    | { kind: "latest"; label: string }

export interface CreateBranchRequest {
    name: string
    description: string | null
    branch_point: BranchPointRequest
}

export interface CreateBranchResponse {
    timeline_id: string
    branch_world_time_id: string
    row_version: number
}
