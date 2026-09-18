import type {
    ChangeMembershipRoleRequest,
    ChangeMembershipRoleResponse,
} from "../types/changeMembershipRole"

export class ChangeMembershipRoleRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(
            `Change membership role request failed with status ${status}`,
        )
        this.name = "ChangeMembershipRoleRequestError"
        this.status = status
    }
}

export async function changeMembershipRole(
    campaignId: string,
    membershipRoleId: string,
    newRoleId: string,
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<ChangeMembershipRoleResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)
    const encodedMembershipRoleId =
        encodeURIComponent(membershipRoleId)

    const body: ChangeMembershipRoleRequest = {
        new_role_id: newRoleId,
    }

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/memberships/roles/${encodedMembershipRoleId}/change`,
        {
            method: "POST",
            credentials: "same-origin",
            cache: "no-store",
            signal,
            headers: {
                Accept: "application/json",
                "Content-Type": "application/json",
                "X-CSRF-Token": csrfToken,
                "Idempotency-Key": idempotencyKey,
            },
            body: JSON.stringify(body),
        },
    )

    if (!response.ok) {
        throw new ChangeMembershipRoleRequestError(
            response.status,
        )
    }

    return (
        await response.json()
    ) as ChangeMembershipRoleResponse
}
