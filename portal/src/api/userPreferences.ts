import { enqueuePreferenceWrite } from "./preferenceWrites"

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

// Never aborted: a request cancelled by the page that issued it may or may not
// commit, which is what let a bootstrap read return the previous campaign.
// Writes are ordered (see preferenceWrites.ts), so the latest selection wins.
export function recordLastVisitedCampaign(
    campaignId: string,
    csrfToken: string,
): Promise<void> {
    return enqueuePreferenceWrite(() =>
        putPreference(
            "/api/auth/preferences/last-visited-campaign",
            { campaign_id: campaignId },
            csrfToken,
        ),
    )
}
