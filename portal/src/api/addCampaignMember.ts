import type {
    AddCampaignMemberRequest,
    AddCampaignMemberResponse,
} from "../types/addCampaignMember"

export class AddCampaignMemberRequestError extends Error {
    readonly status: number

    constructor(status: number) {
        super(
            `Add campaign member request failed with status ${status}`,
        )
        this.name = "AddCampaignMemberRequestError"
        this.status = status
    }
}

export async function addCampaignMember(
    campaignId: string,
    userId: string,
    roleId: string,
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<AddCampaignMemberResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)

    const body: AddCampaignMemberRequest = {
        user_id: userId,
        role_id: roleId,
    }

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/memberships`,
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
        throw new AddCampaignMemberRequestError(response.status)
    }

    return (
        await response.json()
    ) as AddCampaignMemberResponse
}
