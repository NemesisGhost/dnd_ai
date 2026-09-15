import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import type {
    CampaignSessionDetail,
    CampaignSessionListItem,
} from "../types/campaignSession"
import {
    CampaignSessionsRequestError,
    fetchCampaignSession,
    fetchCampaignSessions,
} from "./campaignSessions"

const sessionsFixture: CampaignSessionListItem[] = [
    {
        session_id: "session-12",
        session_number: 12,
        title: "The Glass Ossuary",
        status_code: "ended",
        started_at: "2026-08-30T18:00:00Z",
        ended_at: "2026-08-30T22:00:00Z",
    },
    {
        session_id: "session-11",
        session_number: 11,
        title: null,
        status_code: "ended",
        started_at: "2026-08-23T18:00:00Z",
        ended_at: "2026-08-23T22:00:00Z",
    },
]

const sessionDetailFixture = {
    session_id: "session-12",
    session_number: 12,
    title: "The Glass Ossuary",
    status_code: "ended",
    started_at: "2026-08-30T18:00:00Z",
    ended_at: "2026-08-30T22:00:00Z",
    summary: "The party entered the dormant facility.",
    start_world_time_id: "world-time-start",
    end_world_time_id: "world-time-end",
    events: [
        {
            event_id: "event-1",
            name: "Entered the Ossuary",
            summary: "The party crossed the sealed threshold.",
            event_type_code: "discovery",
            event_status_code: "resolved",
            world_time_id: "world-time-event",
            details: "The dormant transit system began responding.",
        },
    ],
} satisfies CampaignSessionDetail

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("fetchCampaignSessions", () => {
    it("returns the authorized session list", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify(sessionsFixture), {
                status: 200,
                headers: {
                    "Content-Type": "application/json",
                },
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchCampaignSessions(
                "campaign/a b",
                controller.signal,
            ),
        ).resolves.toEqual(sessionsFixture)

        expect(fetchMock).toHaveBeenCalledTimes(1)

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/sessions",
            {
                method: "GET",
                headers: {
                    Accept: "application/json",
                },
                cache: "no-store",
                signal: controller.signal,
            },
        )
    })

    it("returns an empty authorized session list", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify([]), {
                status: 200,
                headers: {
                    "Content-Type": "application/json",
                },
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchCampaignSessions("campaign-a"),
        ).resolves.toEqual([])
    })

    it("throws a typed error with the HTTP status", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(null, {
                status: 404,
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        const request =
            fetchCampaignSessions("missing-campaign")

        await expect(request).rejects.toBeInstanceOf(
            CampaignSessionsRequestError,
        )

        await expect(request).rejects.toMatchObject({
            name: "CampaignSessionsRequestError",
            status: 404,
            message:
                "Campaign sessions request failed with status 404",
        })
    })

    it("preserves network failures", async () => {
        const networkError = new TypeError(
            "Failed to fetch",
        )

        const fetchMock =
            vi.fn().mockRejectedValue(networkError)

        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchCampaignSessions("campaign-a"),
        ).rejects.toBe(networkError)
    })

    it("forwards the abort signal and preserves cancellation", async () => {
        const controller = new AbortController()

        const abortError = new DOMException(
            "The operation was aborted.",
            "AbortError",
        )

        const fetchMock =
            vi.fn().mockRejectedValue(abortError)

        vi.stubGlobal("fetch", fetchMock)

        controller.abort()

        await expect(
            fetchCampaignSessions(
                "campaign-a",
                controller.signal,
            ),
        ).rejects.toBe(abortError)

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/sessions",
            expect.objectContaining({
                signal: controller.signal,
            }),
        )
    })
})

describe("fetchCampaignSession", () => {
    it("returns the authorized session detail", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify(sessionDetailFixture),
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
            fetchCampaignSession(
                "campaign/a b",
                "session/c d",
                controller.signal,
            ),
        ).resolves.toEqual(sessionDetailFixture)

        expect(fetchMock).toHaveBeenCalledTimes(1)

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/sessions/session%2Fc%20d",
            {
                method: "GET",
                headers: {
                    Accept: "application/json",
                },
                cache: "no-store",
                signal: controller.signal,
            },
        )
    })

    it("throws the same typed error for a missing or inaccessible session", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(null, {
                status: 404,
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        const request = fetchCampaignSession(
            "campaign-a",
            "unavailable-session",
        )

        await expect(request).rejects.toBeInstanceOf(
            CampaignSessionsRequestError,
        )

        await expect(request).rejects.toMatchObject({
            name: "CampaignSessionsRequestError",
            status: 404,
            message:
                "Campaign sessions request failed with status 404",
        })
    })
})