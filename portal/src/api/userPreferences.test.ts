import { afterEach, describe, expect, it, vi } from "vitest"
import {
    recordLastVisitedCampaign,
    setCampaignStartupPreference,
    UserPreferenceRequestError,
} from "./userPreferences"

afterEach(() => {
    vi.unstubAllGlobals()
})

function expectedInit(body: object) {
    return {
        method: "PUT",
        credentials: "same-origin",
        cache: "no-store",
        signal: undefined,
        headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-CSRF-Token": "csrf-token",
        },
        body: JSON.stringify(body),
    }
}

describe("setCampaignStartupPreference", () => {
    it("PUTs the preferred campaign with csrf and same-origin credentials", async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            setCampaignStartupPreference("campaign-a", "csrf-token"),
        ).resolves.toBeUndefined()

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/auth/preferences/campaign-startup",
            expectedInit({ preferred_campaign_id: "campaign-a" }),
        )
    })

    it("sends null to clear the fixed choice", async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
        vi.stubGlobal("fetch", fetchMock)

        await setCampaignStartupPreference(null, "csrf-token")

        expect(fetchMock.mock.calls[0]![1].body).toBe(
            JSON.stringify({ preferred_campaign_id: null }),
        )
    })

    it("throws a typed error carrying the status on a non-ok response", async () => {
        vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 404 })))

        await expect(
            setCampaignStartupPreference("gone", "csrf-token"),
        ).rejects.toMatchObject({
            name: "UserPreferenceRequestError",
            status: 404,
        } satisfies Partial<UserPreferenceRequestError>)
    })
})

describe("recordLastVisitedCampaign", () => {
    it("PUTs the campaign id with csrf", async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
        vi.stubGlobal("fetch", fetchMock)

        await recordLastVisitedCampaign("campaign-a", "csrf-token")

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/auth/preferences/last-visited-campaign",
            expectedInit({ campaign_id: "campaign-a" }),
        )
    })

    it("throws a typed error on failure", async () => {
        vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 403 })))

        await expect(recordLastVisitedCampaign("c", "bad")).rejects.toBeInstanceOf(
            UserPreferenceRequestError,
        )
    })
})
