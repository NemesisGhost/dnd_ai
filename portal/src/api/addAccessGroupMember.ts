import type {
    AddAccessGroupMembersRequest,
    AddAccessGroupMembersResponse,
} from "../types/accessGroup"

export class AddAccessGroupMemberRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(
            `Add access group member request failed with status ${status}`,
        )
        this.name = "AddAccessGroupMemberRequestError"
        this.status = status
    }
}

export async function addAccessGroupMember(
    campaignId: string,
    accessGroupId: string,
    campaignMembershipIds: string[],
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<AddAccessGroupMembersResponse> {
    const encodedCampaignId =
        encodeURIComponent(campaignId)
    const encodedGroupId =
        encodeURIComponent(accessGroupId)

    const body: AddAccessGroupMembersRequest = {
        campaign_membership_ids:
            campaignMembershipIds,
    }

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/access-groups/${encodedGroupId}/members`,
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
        throw new AddAccessGroupMemberRequestError(
            response.status,
        )
    }

    return (await response.json()) as AddAccessGroupMembersResponse
}