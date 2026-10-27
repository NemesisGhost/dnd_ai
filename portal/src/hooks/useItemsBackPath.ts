import { useLocation } from "react-router"
import { pickQueryStates, readQueryState } from "./returnState"

// Router state that restores the collection an item (or definition) was opened from, the way
// `worldSearch` restores the World browser. Only a query string rides along, and only when it is
// one; anything else is ignored, so a crafted state cannot send the person anywhere else.
export interface ItemsReturnState {
    itemsSearch?: string
    definitionsSearch?: string
    worldSearch?: string
}

const KEYS = ["itemsSearch", "definitionsSearch", "worldSearch"] as const

// The valid return keys of a location state, for forwarding through in-page links.
export function pickReturnState(state: unknown): ItemsReturnState | undefined {
    return pickQueryStates(state, KEYS)
}

export function useItemsReturnState(): ItemsReturnState | undefined {
    return pickReturnState(useLocation().state)
}

const itemsBase = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}/items`
const definitionsBase = (campaignId: string): string =>
    `/app/${encodeURIComponent(campaignId)}/item-definitions`

// The item inventory, with the query it was left on (none for a direct link).
export function useItemsBackPath(campaignId: string): string {
    return `${itemsBase(campaignId)}${readQueryState(useLocation().state, "itemsSearch") ?? ""}`
}

// The item definitions list, with its filters.
export function useDefinitionsBackPath(campaignId: string): string {
    return `${definitionsBase(campaignId)}${readQueryState(useLocation().state, "definitionsSearch") ?? ""}`
}
