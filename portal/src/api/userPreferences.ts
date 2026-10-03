export class UserPreferenceRequestError extends Error {
    readonly status: number

    constructor(status: number, message: string) {
        super(message)
        this.name = "UserPreferenceRequestError"
        this.status = status
    }
}

async function putPreference(
    path: string,
    body: Record<string, string | null>,
    csrfToken: string,
    signal?: AbortSignal,
): Promise<void> {
    const response = await fetch(path, {
        method: "PUT",
        credentials: "same-origin",
        cache: "no-store",
        signal,
        headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify(body),
    })

    if (!response.ok) {
        throw new UserPreferenceRequestError(
            response.status,
            `Preference request failed with status ${response.status}`,
        )
    }
}

// `null` clears the fixed choice ("Resume my last visited campaign").
export function setCampaignStartupPreference(
    preferredCampaignId: string | null,
    csrfToken: string,
    signal?: AbortSignal,
): Promise<void> {
    return putPreference(
        "/api/auth/preferences/campaign-startup",
        { preferred_campaign_id: preferredCampaignId },
        csrfToken,
        signal,
    )
}

export function recordLastVisitedCampaign(
    campaignId: string,
    csrfToken: string,
    signal?: AbortSignal,
): Promise<void> {
    return putPreference(
        "/api/auth/preferences/last-visited-campaign",
        { campaign_id: campaignId },
        csrfToken,
        signal,
    )
}
