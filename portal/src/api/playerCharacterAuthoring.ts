import type { PlayerCharacterReceipt } from "../types/contentAuthoring"
import type { CreateNpcBody, UpdateNpcBody } from "../types/npcAuthoring"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

// Player-character identity authoring (Phase 15.2B-1). The same field set and
// options as an NPC; only the route (and the receipt's id field) differ.

function base(campaignId: string): string {
    return `/campaigns/${encodeURIComponent(campaignId)}/authoring/player-characters`
}

export const playerCharacterOptionsPath = (campaignId: string): string =>
    `${base(campaignId)}/options`

export const playerCharacterAuthoringPath = (campaignId: string, id: string): string =>
    `${base(campaignId)}/${encodeURIComponent(id)}`

export function createPlayerCharacter(
    campaignId: string,
    body: CreateNpcBody,
    ctx: MutationContext,
): Promise<PlayerCharacterReceipt> {
    return apiRequest<PlayerCharacterReceipt>("POST", base(campaignId), { body, ...ctx })
}

export function updatePlayerCharacter(
    campaignId: string,
    id: string,
    body: UpdateNpcBody,
    ctx: MutationContext,
): Promise<PlayerCharacterReceipt> {
    return apiRequest<PlayerCharacterReceipt>(
        "POST",
        `${playerCharacterAuthoringPath(campaignId, id)}/update`,
        { body, ...ctx },
    )
}
