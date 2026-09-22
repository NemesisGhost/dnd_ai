import type {
    AcceptCampaignInvitationResponse,
    CreateCampaignInvitationResponse,
    PendingCampaignInvitationList,
    RevokeCampaignInvitationResponse,
} from "../types/campaignInvitations"

export class CampaignInvitationsRequestError extends Error {
    readonly status: number

    constructor(status: number, message: string) {
        super(message)
        this.name = "CampaignInvitationsRequestError"
        this.status = status
    }
}

export async function fetchCampaignInvitations(
    campaignId: string,
    signal?: AbortSignal,
): Promise<PendingCampaignInvitationList> {
    const encodedCampaignId = encodeURIComponent(campaignId)

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/invitations`,
        {
            method: "GET",
            cache: "no-store",
            signal,
            headers: {
                Accept: "application/json",
            },
        },
    )

    if (!response.ok) {
        throw new CampaignInvitationsRequestError(
            response.status,
            `Campaign invitations request failed with status ${response.status}`,
        )
    }

    return (await response.json()) as PendingCampaignInvitationList
}

export async function createCampaignInvitation(
    campaignId: string,
    invitedEmail: string | null,
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<CreateCampaignInvitationResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/invitations`,
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
            body: JSON.stringify({ invited_email: invitedEmail }),
        },
    )

    if (!response.ok) {
        throw new CampaignInvitationsRequestError(
            response.status,
            `Create campaign invitation request failed with status ${response.status}`,
        )
    }

    return (await response.json()) as CreateCampaignInvitationResponse
}

export async function revokeCampaignInvitation(
    campaignId: string,
    campaignInvitationId: string,
    csrfToken: string,
    idempotencyKey: string,
    signal?: AbortSignal,
): Promise<RevokeCampaignInvitationResponse> {
    const encodedCampaignId = encodeURIComponent(campaignId)
    const encodedInvitationId = encodeURIComponent(campaignInvitationId)

    const response = await fetch(
        `/api/campaigns/${encodedCampaignId}/invitations/${encodedInvitationId}/revoke`,
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
        throw new CampaignInvitationsRequestError(
            response.status,
            `Revoke campaign invitation request failed with status ${response.status}`,
        )
    }

    return (await response.json()) as RevokeCampaignInvitationResponse
}

export async function acceptCampaignInvitation(
    token: string,
    csrfToken: string,
    signal?: AbortSignal,
): Promise<AcceptCampaignInvitationResponse> {
    const response = await fetch("/api/campaign-invitations/accept", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        signal,
        headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({ token }),
    })

    if (!response.ok) {
        throw new CampaignInvitationsRequestError(
            response.status,
            `Accept campaign invitation request failed with status ${response.status}`,
        )
    }

    return (await response.json()) as AcceptCampaignInvitationResponse
}