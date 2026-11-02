import type { ItemDefinition, ItemDefinitionBody } from "../types/itemDefinitions"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

const enc = encodeURIComponent

const base = (campaignId: string): string =>
    `/campaigns/${enc(campaignId)}/authoring/item-definitions`

export const itemDefinitionsPath = (campaignId: string): string => base(campaignId)

export const itemDefinitionOptionsPath = (campaignId: string): string =>
    `${base(campaignId)}/options`

export const itemDefinitionPath = (campaignId: string, definitionId: string): string =>
    `${base(campaignId)}/${enc(definitionId)}`

export function createItemDefinition(
    campaignId: string,
    body: ItemDefinitionBody,
    ctx: MutationContext,
): Promise<ItemDefinition> {
    return apiRequest<ItemDefinition>("POST", base(campaignId), { body, ...ctx })
}

export function updateItemDefinition(
    campaignId: string,
    definitionId: string,
    body: ItemDefinitionBody & { expected_row_version: number },
    ctx: MutationContext,
): Promise<ItemDefinition> {
    return apiRequest<ItemDefinition>("POST", `${itemDefinitionPath(campaignId, definitionId)}/update`, {
        body,
        ...ctx,
    })
}
