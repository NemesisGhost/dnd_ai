import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import type { CampaignSummary } from "../types/campaignSummary"
import {
    CampaignSummaryRequestError,
    fetchCampaignSummary,
} from "./campaignSummary"

const campaignSummaryFixture = {
    current_session: {
        session_id: "session-12",
        session_number: 12,
        title: "The Glass Ossuary",
        status_code: "active",
        started_at: "2026-09-04T18:00:00Z",
        ended_at: null,
    },
    previous_session_recap:
        "The party entered the dormant facility.",
    recent_events: [
        {
            event_id: "event-1",
            name: "Threshold Opened",
            summary: "The first seal was released.",
            event_type_code: "location_changed",
            event_status_code: "recorded",
            world_time_id: "world-time-1",
            details: null,
        },
    ],
} satisfies CampaignSummary

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("fetchCampaignSummary", () => {
    it("returns the campaign summary from a successful response", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify(campaignSummaryFixture),
                {
                    status: 200,
                    headers: {
                        "Content-Type": "application/json",
                    },
                },
            ),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchCampaignSummary(
                "campaign/a b",
                controller.signal,
            ),
        ).resolves.toEqual(campaignSummaryFixture)

        expect(fetchMock).toHaveBeenCalledTimes(1)

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/summary",
            {
                method: "GET",
                credentials: "same-origin",
                cache: "no-store",
                signal: controller.signal,
                headers: {
                    Accept: "application/json",
                },
            },
        )
    })

    it("throws a typed error containing the HTTP status", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(null, {
                status: 404,
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        const request = fetchCampaignSummary(
            "campaign-unavailable",
        )

        await expect(request).rejects.toBeInstanceOf(
            CampaignSummaryRequestError,
        )

        await expect(request).rejects.toMatchObject({
            name: "CampaignSummaryRequestError",
            status: 404,
            message:
                "Campaign summary request failed with status 404",
        })
    })

    it("preserves network failures for the caller to handle", async () => {
        const networkError = new TypeError(
            "Failed to fetch",
        )

        const fetchMock = vi.fn().mockRejectedValue(
            networkError,
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchCampaignSummary("campaign-a"),
        ).rejects.toBe(networkError)
    })

    it("passes cancellation failures back to the caller", async () => {
        const controller = new AbortController()
        const abortError = new DOMException(
            "The operation was aborted.",
            "AbortError",
        )

        const fetchMock = vi.fn().mockRejectedValue(
            abortError,
        )

        vi.stubGlobal("fetch", fetchMock)

        controller.abort()

        await expect(
            fetchCampaignSummary(
                "campaign-a",
                controller.signal,
            ),
        ).rejects.toBe(abortError)

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/summary",
            expect.objectContaining({
                signal: controller.signal,
            }),
        )
    })
})