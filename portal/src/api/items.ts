import type { CreateItemBody, ItemView, OperationBody, UpdateItemBody } from "../types/items"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

const enc = encodeURIComponent

const authoring = (campaignId: string): string => `/campaigns/${enc(campaignId)}/authoring/items`

export const itemsPath = (campaignId: string): string => authoring(campaignId)

export const itemOptionsPath = (campaignId: string): string => `${authoring(campaignId)}/options`

export const itemAuthoringPath = (campaignId: string, itemId: string): string =>
    `${authoring(campaignId)}/${enc(itemId)}`

export const characterInventoryPath = (campaignId: string, characterId: string): string =>
    `/campaigns/${enc(campaignId)}/characters/${enc(characterId)}/inventory`

export const partyInventoryPath = (campaignId: string, partyId: string): string =>
    `/campaigns/${enc(campaignId)}/parties/${enc(partyId)}/inventory`

export function createItem(
    campaignId: string,
    body: CreateItemBody,
    ctx: MutationContext,
): Promise<ItemView> {
    return apiRequest<ItemView>("POST", authoring(campaignId), { body, ...ctx })
}

export function updateItem(
    campaignId: string,
    itemId: string,
    body: UpdateItemBody,
    ctx: MutationContext,
): Promise<ItemView> {
    return apiRequest<ItemView>("POST", `${itemAuthoringPath(campaignId, itemId)}/update`, {
        body,
        ...ctx,
    })
}

// One POST per operation: award, transfer, equip, unequip, consume, damage, repair, destroy,
// attune, end-attunement.
export function runItemOperation(
    campaignId: string,
    itemId: string,
    operation: string,
    body: OperationBody,
    ctx: MutationContext,
): Promise<ItemView> {
    return apiRequest<ItemView>(
        "POST",
        `/campaigns/${enc(campaignId)}/items/${enc(itemId)}/${operation}`,
        { body, ...ctx },
    )
}
