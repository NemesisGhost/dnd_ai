import type {
    CampaignAccessOverview,
} from "../types/accessOverview"

export class AccessOverviewRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(
            `Access overview request failed with status ${status}`,
        )
        this.name = "AccessOverviewRequestError"
        this.status = status
    }
}

export async function fetchCampaignAccessOverview(
    campaignId: string,
    signal?: AbortSignal,
): Promise<CampaignAccessOverview> {
    const encodedCampaignId =
        encodeURIComponent(campaignId)

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/access-overview`,
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
        throw new AccessOverviewRequestError(
            response.status,
        )
    }

    return (
        await response.json()
    ) as CampaignAccessOverview
}
