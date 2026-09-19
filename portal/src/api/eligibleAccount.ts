import type { EligibleAccountLookupResponse } from "../types/eligibleAccount"

export class EligibleAccountRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(
            `Eligible account lookup request failed with status ${status}`,
        )
        this.name = "EligibleAccountRequestError"
        this.status = status
    }
}

export async function fetchEligibleCampaignAccount(
    campaignId: string,
    loginName: string,
    signal?: AbortSignal,
): Promise<EligibleAccountLookupResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)
    const query = new URLSearchParams({ login_name: loginName })

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/eligible-accounts?${query.toString()}`,
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
        throw new EligibleAccountRequestError(response.status)
    }

    return (
        await response.json()
    ) as EligibleAccountLookupResponse
}
