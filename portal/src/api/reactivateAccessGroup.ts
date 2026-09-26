import type { AccessGroupResponse } from "../types/accessGroup"

export class ReactivateAccessGroupRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(`Reactivate access group request failed with status ${status}`)
        this.name = "ReactivateAccessGroupRequestError"
        this.status = status
    }
}

export async function reactivateAccessGroup(
    campaignId: string,
    accessGroupId: string,
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<AccessGroupResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)
    const encodedGroupId = encodeURIComponent(accessGroupId)

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/access-groups/${encodedGroupId}/reactivate`,
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
        throw new ReactivateAccessGroupRequestError(response.status)
    }

    return (await response.json()) as AccessGroupResponse
}
