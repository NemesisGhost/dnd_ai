import type {
    CreateRevelationBody,
    CreateRevelationReceipt,
    RevokeRevelationReceipt,
    RevokeRevelationSubmit,
} from "../types/characterRevelations"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

// The GM's list of one character's revelations, and the two writes. Only the public-profile page's
// Revelations section calls anything under this path.
const enc = encodeURIComponent

export const revelationsPath = (campaignId: string, characterId: string): string =>
    `/campaigns/${enc(campaignId)}/characters/${enc(characterId)}/revelations`

export function createCharacterRevelation(
    campaignId: string,
    characterId: string,
    body: CreateRevelationBody,
    ctx: MutationContext,
): Promise<CreateRevelationReceipt> {
    return apiRequest<CreateRevelationReceipt>("POST", revelationsPath(campaignId, characterId), { body, ...ctx })
}

export function revokeCharacterRevelation(
    campaignId: string,
    characterId: string,
    submit: RevokeRevelationSubmit,
    ctx: MutationContext,
): Promise<RevokeRevelationReceipt> {
    return apiRequest<RevokeRevelationReceipt>(
        "POST",
        `${revelationsPath(campaignId, characterId)}/${enc(submit.character_revelation_id)}/revoke`,
        { body: { reason: submit.reason }, ...ctx },
    )
}
