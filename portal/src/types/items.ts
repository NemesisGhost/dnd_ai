// Item instance, item operation and inventory contracts (Phase 15 checkpoint 15.3B-1b).

export interface ItemReference {
    entity_id: string
    name: string
    entity_type_code: string
}

export interface ItemView {
    item_instance_id: string
    name: string
    summary: string | null
    origin_notes: string | null
    item_definition_id: string
    definition_name: string
    category: string
    category_label: string
    rarity: string
    requires_attunement: boolean
    weight: number | null
    canon_status: string
    lifecycle_status: string
    row_version: number
    is_container: boolean
    quantity: number
    condition_percentage: number | null
    is_equipped: boolean
    is_destroyed: boolean
    // The item's optimistic token: the last event seen; null when it has no state yet.
    last_event_id: string | null
    holder: ItemReference | null
    container: ItemReference | null
    location: ItemReference | null
    owner: ItemReference | null
    attuned_to: ItemReference | null
    available_actions: string[]
    blocked_actions: { action: string; reason: string }[]
    // Published and active: the only state in which an operation can run.
    can_operate: boolean
    changed?: boolean
    event_id?: string
    operation?: string
}

export interface ItemSummary {
    item_instance_id: string
    name: string
    definition_name: string
    category_label: string
    canon_status: string
    lifecycle_status: string
    holder_name: string | null
    is_destroyed: boolean
}

export interface ItemList {
    items: ItemSummary[]
}

export interface ItemOptions {
    can_create: boolean
    definitions: { value: string; label: string; category: string }[]
    limits: {
        name_max_length: number
        summary_max_length: number
        origin_notes_max_length: number
        change_note_max_length: number
        quantity_max: number
    }
}

export interface CreateItemBody {
    name: string
    summary: string | null
    item_definition_id: string
    origin_notes: string | null
}

export interface UpdateItemBody {
    expected_row_version: number
    name: string
    summary: string | null
    origin_notes: string | null
    change_note: string | null
}

// Every operation names the last event it saw (null when the item has no state yet) and
// optionally a world time (omitted: the campaign clock).
export interface OperationBody {
    expected_last_event_id: string | null
    world_time_id?: string
    note?: string
    [key: string]: unknown
}

export interface PartyInventory {
    party_id: string
    members: {
        character_id: string
        character_name: string
        items: {
            item_instance_id: string
            name: string
            display_name: string
            item_category_code: string
            rarity: string
            quantity: number
            condition_percentage: number | null
            is_equipped: boolean
            is_destroyed: boolean
            is_published: boolean
            last_event_id: string | null
        }[]
    }[]
}

export interface CharacterInventoryItem {
    item_instance_id: string
    name: string
    display_name: string
    item_category_code: string
    rarity: string
    quantity: number
    condition_percentage: number | null
    is_equipped: boolean
    is_destroyed: boolean
}
