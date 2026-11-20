import type {
    SavePublicProfileDraftBody,
    SavePublicProfileDraftReceipt,
} from "../types/characterPublicProfile"
import { apiRequest } from "./http"
import type { MutationContext } from "./worlds"

const enc = encodeURIComponent

// The GM's read of one character's public-profile draft and releases. Only the public-profile page
// calls anything under this path.
export const publicProfilePath = (campaignId: string, characterId: string): string =>
    `/campaigns/${enc(campaignId)}/characters/${enc(characterId)}/public-profile`

export function saveCharacterPublicProfileDraft(
    campaignId: string,
    characterId: string,
    body: SavePublicProfileDraftBody,
    ctx: MutationContext,
): Promise<SavePublicProfileDraftReceipt> {
    return apiRequest<SavePublicProfileDraftReceipt>(
        "POST",
        `${publicProfilePath(campaignId, characterId)}/draft`,
        { body, ...ctx },
    )
}
