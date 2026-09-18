import type {
    AssignMembershipRoleRequest,
    AssignMembershipRoleResponse,
} from "../types/assignMembershipRole"

export class AssignMembershipRoleRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(
            `Assign membership role request failed with status ${status}`,
        )
        this.name = "AssignMembershipRoleRequestError"
        this.status = status
    }
}

export async function assignMembershipRole(
    campaignId: string,
    campaignMembershipId: string,
    roleId: string,
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<AssignMembershipRoleResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)
    const encodedMembershipId =
        encodeURIComponent(campaignMembershipId)

    const body: AssignMembershipRoleRequest = {
        role_id: roleId,
    }

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/memberships/${encodedMembershipId}/roles`,
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
        throw new AssignMembershipRoleRequestError(
            response.status,
        )
    }

    return (
        await response.json()
    ) as AssignMembershipRoleResponse
}
