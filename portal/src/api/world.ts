import type {
    WorldEntityPage,
    WorldEntitySearchParameters,
} from "../types/world"

export class WorldRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(
            `World request failed with status ${status}`,
        )
        this.name = "WorldRequestError"
        this.status = status
    }
}

function buildWorldSearchPath(
    campaignId: string,
    parameters: WorldEntitySearchParameters,
): string {
    const encodedCampaignId =
        encodeURIComponent(campaignId)

    const searchParameters = new URLSearchParams()

    if (parameters.category !== null) {
        searchParameters.set(
            "category",
            parameters.category,
        )
    }

    if (parameters.query !== "") {
        searchParameters.set("q", parameters.query)
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

    const queryString = searchParameters.toString()

    const path =
        `/api/campaigns/${encodedCampaignId}/world/search`

    return queryString === ""
        ? path
        : `${path}?${queryString}`
}

export async function fetchWorldEntities(
    campaignId: string,
    parameters: WorldEntitySearchParameters,
    signal?: AbortSignal,
): Promise<WorldEntityPage> {
    const response = await fetch(
        buildWorldSearchPath(campaignId, parameters),
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
        throw new WorldRequestError(response.status)
    }

    return (await response.json()) as WorldEntityPage
}