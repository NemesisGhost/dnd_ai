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