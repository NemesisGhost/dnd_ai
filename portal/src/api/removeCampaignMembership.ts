import type { RemoveCampaignMembershipResponse } from "../types/removeCampaignMembership"

export class RemoveCampaignMembershipRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(
            `Remove campaign membership request failed with status ${status}`,
        )
        this.name = "RemoveCampaignMembershipRequestError"
        this.status = status
    }
}

export async function removeCampaignMembership(
    campaignId: string,
    campaignMembershipId: string,
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<RemoveCampaignMembershipResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)
    const encodedMembershipId =
        encodeURIComponent(campaignMembershipId)

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/memberships/${encodedMembershipId}/end`,
        {
            method: "POST",
            credentials: "same-origin",
            cache: "no-store",
            signal,
            headers: {
                Accept: "application/json",
                "X-CSRF-Token": csrfToken,
                "Idempotency-Key": idempotencyKey,
            },
        },
    )

    if (!response.ok) {
        throw new RemoveCampaignMembershipRequestError(
            response.status,
        )
    }

    return (
        await response.json()
    ) as RemoveCampaignMembershipResponse
}
