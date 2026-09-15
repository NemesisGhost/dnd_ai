import type { CharacterDetail } from "../types/character"

export class CharacterRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(`Character request failed with status ${status}`)
        this.name = "CharacterRequestError"
        this.status = status
    }
}

export async function fetchCharacter(
    campaignId: string,
    characterId: string,
    signal?: AbortSignal,
): Promise<CharacterDetail> {
    const encodedCampaignId = encodeURIComponent(campaignId)
    const encodedCharacterId = encodeURIComponent(characterId)

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/characters/${encodedCharacterId}`,
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
        throw new CharacterRequestError(response.status)
    }

    return (await response.json()) as CharacterDetail
}