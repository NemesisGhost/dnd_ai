import type { NpcPortrayalView } from "../types/npcPortrayal"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

const enc = encodeURIComponent

export const npcPortrayalPath = (
    campaignId: string,
    npcId: string,
    version: number | null = null,
): string =>
    `/campaigns/${enc(campaignId)}/authoring/npcs/${enc(npcId)}/portrayal${
        version === null ? "" : `?version=${version}`
    }`

export const npcRuntimeOptionsPath = (campaignId: string): string =>
    `/campaigns/${enc(campaignId)}/authoring/npc-runtime-options`

export function saveNpcPortrayal(
    campaignId: string,
    npcId: string,
    body: Record<string, string | number | null>,
    ctx: MutationContext,
): Promise<NpcPortrayalView> {
    return apiRequest<NpcPortrayalView>("POST", npcPortrayalPath(campaignId, npcId), {
        body,
        ...ctx,
    })
}

export function setNpcDetailLevel(
    campaignId: string,
    npcId: string,
    body: { expected_row_version: number; detail_level: string },
    ctx: MutationContext,
): Promise<NpcPortrayalView> {
    return apiRequest<NpcPortrayalView>(
        "POST",
        `/campaigns/${enc(campaignId)}/authoring/npcs/${enc(npcId)}/detail-level`,
        { body, ...ctx },
    )
}
