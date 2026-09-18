import type { RevokeMembershipRoleResponse } from "../types/revokeMembershipRole"

export class RevokeMembershipRoleRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(
            `Revoke membership role request failed with status ${status}`,
        )
        this.name = "RevokeMembershipRoleRequestError"
        this.status = status
    }
}

export async function revokeMembershipRole(
    campaignId: string,
    membershipRoleId: string,
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<RevokeMembershipRoleResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)
    const encodedMembershipRoleId =
        encodeURIComponent(membershipRoleId)

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/memberships/roles/${encodedMembershipRoleId}/revoke`,
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
        throw new RevokeMembershipRoleRequestError(
            response.status,
        )
    }

    return (
        await response.json()
    ) as RevokeMembershipRoleResponse
}
