export type WorldCategory =
    | "location"
    | "character"
    | "organization"
    | "religion"
    | "item"
    | "event"

export interface WorldEntityCard {
    entity_id: string
    category: WorldCategory
    entity_type_code: string
    name: string
    summary: string | null
}

export interface WorldEntityPage {
    items: WorldEntityCard[]
    next_cursor: string | null
}

export interface WorldEntitySearchParameters {
    category: WorldCategory | null
    query: string
    cursor?: string | null
    limit?: number
}

// World categories with an independently loadable, audience-safe detail
// contract in this increment (UI_STYLE_GUIDE.md §10.2). "organization" and
// "relationship" are deliberately excluded — see docs/PHASE13D_BACKEND_READINESS.md
// §10.3: OrganizationResponse has no display name field yet.
export type WorldDetailCategory =
    | "location"
    | "character"
    | "religion"
    | "item"
    | "event"

export function isWorldDetailCategory(
    value: string,
): value is WorldDetailCategory {
    return (
        value === "location" ||
        value === "character" ||
        value === "religion" ||
        value === "item" ||
        value === "event"
    )
}

export interface LocationCrumb {
    location_id: string
    name: string
    location_type_code: string
}

export interface LocationDetail {
    location_id: string
    name: string
    summary: string | null
    location_type_code: string
    parent_location_id: string | null
    breadcrumbs: LocationCrumb[]
    population: number | null
    building_use: string | null
    danger_level: number | null
    is_searched: boolean | null
    is_destroyed: boolean | null
    alarm_level: number | null
    condition_notes: string | null
}

export interface ReligionDetail {
    religion_id: string
    name: string
    summary: string | null
    pantheon_structure: string | null
    serving_organization_ids: string[]
}

export interface ItemDetail {
    item_instance_id: string
    name: string
    summary: string | null
    item_definition_id: string | null
    origin_notes: string | null
    quantity: number | null
    condition_percentage: number | null
    charges_current: number | null
    charges_maximum: number | null
    is_equipped: boolean | null
    is_destroyed: boolean | null
}

export interface EventParticipant {
    entity_id: string
    role_code: string | null
}

export interface EventLocationRole {
    location_id: string
    role: string | null
}

export interface EventDetail {
    event_id: string
    name: string
    summary: string | null
    event_type_code: string
    event_status_code: string
    world_time_id: string
    details: string | null
    session_id: string | null
    participants: EventParticipant[]
    locations: EventLocationRole[]
}