import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { fetchEligibleCampaignAccount } from "./eligibleAccount"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("fetchEligibleCampaignAccount", () => {
    it("gets the campaign-scoped eligible-accounts route with the login_name query parameter", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    account: {
                        user_id: "user-1",
                        display_name: "Player One",
                    },
                }),
                {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchEligibleCampaignAccount(
                "campaign/a b",
                "player.one",
                controller.signal,
            ),
        ).resolves.toEqual({
            account: {
                user_id: "user-1",
                display_name: "Player One",
            },
        })

        expect(fetchMock).toHaveBeenCalledTimes(1)
        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/eligible-accounts?login_name=player.one",
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

    it("returns account: null for no eligible match, without a thrown error", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(
                new Response(JSON.stringify({ account: null }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            ),
        )

        await expect(
            fetchEligibleCampaignAccount("campaign-a", "nonexistent"),
        ).resolves.toEqual({ account: null })
    })

    it("passes no signal when the caller supplies none", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(
                new Response(JSON.stringify({ account: null }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            ),
        )

        await fetchEligibleCampaignAccount("campaign-a", "someone")

        expect(fetch).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ signal: undefined }),
        )
    })

    it("throws a typed error for an unauthenticated response", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 401 })),
        )

        const request = fetchEligibleCampaignAccount(
            "campaign-a",
            "someone",
        )

        await expect(request).rejects.toMatchObject({
            name: "EligibleAccountRequestError",
            status: 401,
        })
    })

    it("throws the same typed error shape for a non-disclosing forbidden/not-found response", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 403 })),
        )

        const request = fetchEligibleCampaignAccount(
            "campaign-a",
            "someone",
        )

        await expect(request).rejects.toMatchObject({
            name: "EligibleAccountRequestError",
            status: 403,
        })
    })

    it("throws a typed error for a recoverable server failure", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 500 })),
        )

        const request = fetchEligibleCampaignAccount(
            "campaign-a",
            "someone",
        )

        await expect(request).rejects.toMatchObject({
            name: "EligibleAccountRequestError",
            status: 500,
        })
    })

    it("propagates an abort so callers can distinguish it from a request failure", async () => {
        const controller = new AbortController()

        vi.stubGlobal(
            "fetch",
            vi.fn().mockImplementation(
                (_input: RequestInfo | URL, init?: RequestInit) =>
                    new Promise((_resolve, reject) => {
                        init?.signal?.addEventListener("abort", () => {
                            reject(new DOMException("Aborted", "AbortError"))
                        })
                    }),
            ),
        )

        const request = fetchEligibleCampaignAccount(
            "campaign-a",
            "someone",
            controller.signal,
        )

        controller.abort()

        await expect(request).rejects.toMatchObject({
            name: "AbortError",
        })
    })
})
