import { useCarriedListSearch } from "../navigation/taskReturn"

// Where an item (or definition) was opened from is the task's list state: the inventory or the
// definitions catalog with the query it was left on. Only a query the list's contract accepts is
// honoured, so a crafted state cannot send the person anywhere else.
const itemsBase = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}/items`
const definitionsBase = (campaignId: string): string =>
    `/app/${encodeURIComponent(campaignId)}/item-definitions`

// The item inventory, with the query it was left on (none for a direct link).
export function useItemsBackPath(campaignId: string): string {
    return `${itemsBase(campaignId)}${useCarriedListSearch("items", "items.list") ?? ""}`
}

// The item definitions list, with its filters.
export function useDefinitionsBackPath(campaignId: string): string {
    return `${definitionsBase(campaignId)}${useCarriedListSearch("items", "itemDefinitions.list") ?? ""}`
}
