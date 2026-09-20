import type { RevokeResourceGrantResponse } from "../types/revokeResourceGrant"

export class RevokeResourceGrantRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(`Revoke resource grant request failed with status ${status}`)
        this.name = "RevokeResourceGrantRequestError"
        this.status = status
    }
}

export async function revokeResourceGrant(
    campaignId: string,
    resourceGrantId: string,
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<RevokeResourceGrantResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)
    const encodedGrantId = encodeURIComponent(resourceGrantId)

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/resource-grants/${encodedGrantId}/revoke`,
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
        throw new RevokeResourceGrantRequestError(response.status)
    }

    return (await response.json()) as RevokeResourceGrantResponse
}
