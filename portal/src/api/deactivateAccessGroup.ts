import type { AccessGroupResponse } from "../types/accessGroup"

export class DeactivateAccessGroupRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(`Deactivate access group request failed with status ${status}`)
        this.name = "DeactivateAccessGroupRequestError"
        this.status = status
    }
}

export async function deactivateAccessGroup(
    campaignId: string,
    accessGroupId: string,
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<AccessGroupResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)
    const encodedGroupId = encodeURIComponent(accessGroupId)

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/access-groups/${encodedGroupId}/deactivate`,
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
        throw new DeactivateAccessGroupRequestError(response.status)
    }

    return (await response.json()) as AccessGroupResponse
}
