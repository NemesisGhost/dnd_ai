import type { CampaignContext } from "../types/bootstrap"

export function resolveSelectedCharacterId(
    campaign: CampaignContext,
    requestedCharacterId: string | null,
): string | null {
    const isAuthorized = (
        characterId: string | null,
    ): characterId is string =>
        characterId !== null &&
        campaign.character_perspectives.some(
            (character) =>
                character.character_id === characterId,
        )

    if (isAuthorized(requestedCharacterId)) {
        return requestedCharacterId
    }

    const serverDefaultCharacterId =
        campaign.selected_character_id

    if (isAuthorized(serverDefaultCharacterId)) {
        return serverDefaultCharacterId
    }

    return null
}