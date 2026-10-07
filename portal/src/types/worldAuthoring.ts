// Response and request shapes for the Phase 14 world authoring endpoints
// (docs/PLAN.md Phase 14, §6). Every identifier is an opaque server value the
// portal never displays; capabilities, actions, and blocked reasons are always
// server-computed and never inferred client-side.

export interface BlockedAction {
    action: string
    reason: string
}

export interface BranchPoint {
    world_time_id: string
    label: string | null
    sort_key: number
}

export interface TimelineSummary {
    timeline_id: string
    name: string
    description: string | null
    is_primary: boolean
    parent_timeline_id: string | null
    branch_point: BranchPoint | null
    lifecycle_status: "active" | "archived" | string
    row_version: number
    // Whether the caller may start a campaign on this timeline (ADR 0020, D7). Only the world
    // detail carries it; the reason is `timeline_in_use` or `world_use_not_permitted`.
    campaign_hosting?: { eligible: boolean; reason: string | null }
}

export interface ManagedCampaign {
    campaign_id: string
    name: string
    lifecycle_status: string
    timeline_id: string
}

export interface WorldSummary {
    world_id: string
    name: string
    description: string | null
    lifecycle_status: "active" | "archived" | string
    row_version: number
    primary_timeline_id: string | null
    capabilities: string[]
    // Display only: the caller's world roles and whether they hold a use grant.
    role_codes?: string[]
    has_use_grant?: boolean
}

export interface RulesetVersionOption {
    ruleset_version_id: string
    version_label: string
}

export interface AllowedRuleset {
    ruleset_id: string
    code: string
    display_name: string
    is_default: boolean
    current_version: RulesetVersionOption | null
}

export interface WorldDetail extends WorldSummary {
    default_ruleset_id: string | null
    allowed_rulesets: AllowedRuleset[]
    timelines: TimelineSummary[]
    managed_campaigns: ManagedCampaign[]
    available_actions: string[]
    blocked_actions: BlockedAction[]
}

export interface WorldListResponse {
    items: WorldSummary[]
    next_cursor: string | null
}

export interface RulesetOption {
    ruleset_id: string
    code: string
    display_name: string
    description: string | null
    current_versions: RulesetVersionOption[]
}

export interface RulesetListResponse {
    items: RulesetOption[]
}

export interface CreateWorldRequest {
    name: string
    description: string | null
    ruleset_ids: string[]
    default_ruleset_id: string
    primary_timeline: { name: string; description: string | null }
}

export interface CreateWorldResponse {
    world_id: string
    primary_timeline_id: string
    row_version: number
}

export interface UpdateWorldRequest {
    expected_row_version: number
    name: string
    description: string | null
}

export interface TransitionRequest {
    expected_row_version: number
    reason: string | null
}

export interface WorldMutationResponse {
    world_id: string
    row_version: number
    lifecycle_status?: string
}
