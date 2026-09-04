import type { CampaignSummary } from "../types/campaignSummary"

export class CampaignSummaryRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(
            `Campaign summary request failed with status ${status}`,
        )

        this.name = "CampaignSummaryRequestError"
        this.status = status
    }
}

export async function fetchCampaignSummary(
    campaignId: string,
    signal?: AbortSignal,
): Promise<CampaignSummary> {
    const encodedCampaignId =
        encodeURIComponent(campaignId)

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/summary`,
        {
            method: "GET",
            credentials: "same-origin",
            cache: "no-store",
            signal,
            headers: {
                Accept: "application/json",
            },
        },
    )

    if (!response.ok) {
        throw new CampaignSummaryRequestError(
            response.status,
        )
    }

    return (await response.json()) as CampaignSummary
}