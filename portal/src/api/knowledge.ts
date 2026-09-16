import type {
    KnowledgeDetail,
    KnowledgePage,
    KnowledgeSearchParameters,
} from "../types/knowledge"

export class KnowledgeRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(
            `Knowledge request failed with status ${status}`,
        )
        this.name = "KnowledgeRequestError"
        this.status = status
    }
}

function buildKnowledgePath(
    campaignId: string,
    parameters: KnowledgeSearchParameters,
): string {
    const encodedCampaignId =
        encodeURIComponent(campaignId)

    const searchParameters = new URLSearchParams()

    searchParameters.set("view", parameters.view)

    if (parameters.characterId !== null) {
        searchParameters.set(
            "character_id",
            parameters.characterId,
        )
    }

    if (parameters.partyId !== null) {
        searchParameters.set(
            "party_id",
            parameters.partyId,
        )
    }

    if (parameters.query !== "") {
        searchParameters.set(
            "q",
            parameters.query,
        )
    }

    if (
        parameters.knowledgeType !== null &&
        parameters.knowledgeType !== ""
    ) {
        searchParameters.set(
            "type",
            parameters.knowledgeType,
        )
    }

    if (parameters.cursor) {
        searchParameters.set(
            "cursor",
            parameters.cursor,
        )
    }

    if (parameters.limit !== undefined) {
        searchParameters.set(
            "limit",
            parameters.limit.toString(),
        )
    }

    const queryString =
        searchParameters.toString()

    return (
        `/api/campaigns/${encodedCampaignId}` +
        `/knowledge?${queryString}`
    )
}

export async function fetchKnowledgeItems(
    campaignId: string,
    parameters: KnowledgeSearchParameters,
    signal?: AbortSignal,
): Promise<KnowledgePage> {
    const response = await fetch(
        buildKnowledgePath(
            campaignId,
            parameters,
        ),
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
        throw new KnowledgeRequestError(
            response.status,
        )
    }

    return (await response.json()) as KnowledgePage
}

function buildKnowledgeDetailPath(
    campaignId: string,
    knowledgeItemId: string,
    characterId: string | null,
    partyId: string | null,
): string {
    const encodedCampaignId = encodeURIComponent(campaignId)
    const encodedItemId = encodeURIComponent(knowledgeItemId)

    const searchParameters = new URLSearchParams()

    if (characterId !== null) {
        searchParameters.set("character_id", characterId)
    }

    if (partyId !== null) {
        searchParameters.set("party_id", partyId)
    }

    const queryString = searchParameters.toString()

    const path =
        `/api/campaigns/${encodedCampaignId}/knowledge/${encodedItemId}`

    return queryString === "" ? path : `${path}?${queryString}`
}

export async function fetchKnowledgeDetail(
    campaignId: string,
    knowledgeItemId: string,
    characterId: string | null,
    partyId: string | null,
    signal?: AbortSignal,
): Promise<KnowledgeDetail> {
    const response = await fetch(
        buildKnowledgeDetailPath(
            campaignId,
            knowledgeItemId,
            characterId,
            partyId,
        ),
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
        throw new KnowledgeRequestError(response.status)
    }

    return (await response.json()) as KnowledgeDetail
}