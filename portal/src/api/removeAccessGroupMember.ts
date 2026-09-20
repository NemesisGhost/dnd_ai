import type { AccessGroupMembershipResponse } from "../types/accessGroup"

export class RemoveAccessGroupMemberRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(
            `Remove access group member request failed with status ${status}`,
        )
        this.name = "RemoveAccessGroupMemberRequestError"
        this.status = status
    }
}

export async function removeAccessGroupMember(
    campaignId: string,
    accessGroupMembershipId: string,
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<AccessGroupMembershipResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)
    const encodedMembershipId = encodeURIComponent(accessGroupMembershipId)

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/access-group-memberships/${encodedMembershipId}/remove`,
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
        throw new RemoveAccessGroupMemberRequestError(response.status)
    }

    return (await response.json()) as AccessGroupMembershipResponse
}
