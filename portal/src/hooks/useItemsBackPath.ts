import { useLocation } from "react-router"

// Router state that restores the collection an item (or definition) was opened from, the way
// `worldSearch` restores the World browser. Only a query string rides along, and only when it is
// one; anything else is ignored, so a crafted state cannot send the person anywhere else.
export interface ItemsReturnState {
    itemsSearch?: string
    definitionsSearch?: string
    worldSearch?: string
}

const KEYS = ["itemsSearch", "definitionsSearch", "worldSearch"] as const

function readSearch(state: unknown, key: (typeof KEYS)[number]): string | undefined {
    const value = (state as ItemsReturnState | null | undefined)?.[key]
    return typeof value === "string" && value.startsWith("?") ? value : undefined
}

// The valid return keys of a location state, for forwarding through in-page links.
export function pickReturnState(state: unknown): ItemsReturnState | undefined {
    const picked: ItemsReturnState = {}
    for (const key of KEYS) {
        const value = readSearch(state, key)
        if (value !== undefined) picked[key] = value
    }
    return Object.keys(picked).length === 0 ? undefined : picked
}

export function useItemsReturnState(): ItemsReturnState | undefined {
    return pickReturnState(useLocation().state)
}

const itemsBase = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}/items`
const definitionsBase = (campaignId: string): string =>
    `/app/${encodeURIComponent(campaignId)}/item-definitions`

// The item inventory, with the query it was left on (none for a direct link).
export function useItemsBackPath(campaignId: string): string {
    return `${itemsBase(campaignId)}${readSearch(useLocation().state, "itemsSearch") ?? ""}`
}

// The item definitions list, with its filters.
export function useDefinitionsBackPath(campaignId: string): string {
    return `${definitionsBase(campaignId)}${readSearch(useLocation().state, "definitionsSearch") ?? ""}`
}
