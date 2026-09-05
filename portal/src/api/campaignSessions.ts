import type {
    CampaignSessionListItem,
} from "../types/campaignSession"

export class CampaignSessionsRequestError
    extends Error {
    readonly status: number

    constructor(status: number) {
        super(
            `Campaign sessions request failed with status ${status}`,
        )
        this.name = "CampaignSessionsRequestError"
        this.status = status
    }
}

export async function fetchCampaignSessions(
    campaignId: string,
    signal?: AbortSignal,
): Promise<CampaignSessionListItem[]> {
    const encodedCampaignId =
        encodeURIComponent(campaignId)

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/sessions`,
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
        throw new CampaignSessionsRequestError(
            response.status,
        )
    }

    return (
        await response.json()
    ) as CampaignSessionListItem[]
}