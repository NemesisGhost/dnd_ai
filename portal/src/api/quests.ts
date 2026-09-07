import type {
    CampaignQuestListItem,
    QuestDetail,
} from "../types/quest"

export class QuestRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(
            `Quest request failed with status ${status}`,
        )
        this.name = "QuestRequestError"
        this.status = status
    }
}

function addCharacterPerspective(
    path: string,
    characterId: string | null,
): string {
    if (characterId === null) {
        return path
    }

    const parameters = new URLSearchParams({
        character_id: characterId,
    })

    return `${path}?${parameters.toString()}`
}

export async function fetchCampaignQuests(
    campaignId: string,
    characterId: string | null,
    signal?: AbortSignal,
): Promise<CampaignQuestListItem[]> {
    const encodedCampaignId =
        encodeURIComponent(campaignId)

    const path = addCharacterPerspective(
        `/api/campaigns/${encodedCampaignId}/quests`,
        characterId,
    )

    const response = await fetch(path, {
        method: "GET",
        headers: {
            Accept: "application/json",
        },
        cache: "no-store",
        signal,
    })

    if (!response.ok) {
        throw new QuestRequestError(response.status)
    }

    return (
        await response.json()
    ) as CampaignQuestListItem[]
}

export async function fetchQuest(
    campaignId: string,
    questId: string,
    characterId: string | null,
    signal?: AbortSignal,
): Promise<QuestDetail> {
    const encodedCampaignId =
        encodeURIComponent(campaignId)

    const encodedQuestId =
        encodeURIComponent(questId)

    const path = addCharacterPerspective(
        `/api/campaigns/${encodedCampaignId}/quests/${encodedQuestId}`,
        characterId,
    )

    const response = await fetch(path, {
        method: "GET",
        headers: {
            Accept: "application/json",
        },
        cache: "no-store",
        signal,
    })

    if (!response.ok) {
        throw new QuestRequestError(response.status)
    }

    return (
        await response.json()
    ) as QuestDetail
}