import type { MemberEffectiveAccess } from "../types/effectiveAccess"

export class EffectiveAccessRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(`Effective access request failed with status ${status}`)
        this.name = "EffectiveAccessRequestError"
        this.status = status
    }
}

export async function fetchMemberEffectiveAccess(
    campaignId: string,
    campaignMembershipId: string,
    signal?: AbortSignal,
): Promise<MemberEffectiveAccess> {
    const encodedCampaignId = encodeURIComponent(campaignId)
    const encodedMembershipId = encodeURIComponent(campaignMembershipId)

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/members/${encodedMembershipId}/effective-access`,
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
        throw new EffectiveAccessRequestError(response.status)
    }

    return (await response.json()) as MemberEffectiveAccess
}
