// Item definition authoring contracts (Phase 15 checkpoint 15.3B-1a, decision D-22).

export interface ItemDefinition {
    item_definition_id: string
    code: string
    name: string
    category: string
    category_label: string
    description: string | null
    rarity: string
    requires_attunement: boolean
    weight: number | null
    base_cost_gp: number | null
    canon_status: string
    row_version: number
    is_homebrew: boolean
    can_edit: boolean
}

export interface ItemDefinitionList {
    items: ItemDefinition[]
}

export interface ItemDefinitionOptions {
    categories: { value: string; label: string }[]
    rarities: { value: string; label: string }[]
    canon_states: { value: string; label: string }[]
    limits: { name_max_length: number; description_max_length: number }
}

export interface ItemDefinitionBody {
    name: string
    category: string
    description: string | null
    rarity: string
    requires_attunement: boolean
    weight: number | null
    base_cost_gp: number | null
    canon_status: string
}
