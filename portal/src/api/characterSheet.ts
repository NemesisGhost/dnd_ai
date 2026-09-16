import type { CharacterSheet } from "../types/characterSheet"

export class CharacterSheetRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(
            `Character sheet request failed with status ${status}`,
        )
        this.name = "CharacterSheetRequestError"
        this.status = status
    }
}

export async function fetchCharacterSheet(
    campaignId: string,
    characterId: string,
    signal?: AbortSignal,
): Promise<CharacterSheet> {
    const encodedCampaignId =
        encodeURIComponent(campaignId)

    const encodedCharacterId =
        encodeURIComponent(characterId)

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/characters/${encodedCharacterId}/sheet`,
        {
            method: "GET",
            headers: {
                Accept: "application/json",
            },
            cache: "no-store",
            signal,
        },
    )

    if (!response.ok) {
        throw new CharacterSheetRequestError(
            response.status,
        )
    }

    return (await response.json()) as CharacterSheet
}