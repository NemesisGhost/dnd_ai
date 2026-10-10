import type { NpcReceipt } from "../types/contentAuthoring"
import type { CreateNpcBody, UpdateNpcBody } from "../types/npcAuthoring"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

function base(campaignId: string): string {
    return `/campaigns/${encodeURIComponent(campaignId)}/authoring/npcs`
}

export const npcOptionsPath = (campaignId: string): string => `${base(campaignId)}/options`

export const npcAuthoringPath = (campaignId: string, npcId: string): string =>
    `${base(campaignId)}/${encodeURIComponent(npcId)}`

export function createNpc(
    campaignId: string,
    body: CreateNpcBody,
    ctx: MutationContext,
): Promise<NpcReceipt> {
    return apiRequest<NpcReceipt>("POST", base(campaignId), { body, ...ctx })
}

export function updateNpc(
    campaignId: string,
    npcId: string,
    body: UpdateNpcBody,
    ctx: MutationContext,
): Promise<NpcReceipt> {
    return apiRequest<NpcReceipt>("POST", `${npcAuthoringPath(campaignId, npcId)}/update`, {
        body,
        ...ctx,
    })
}
