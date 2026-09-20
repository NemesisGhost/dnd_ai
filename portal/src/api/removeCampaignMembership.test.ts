import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { removeCampaignMembership } from "./removeCampaignMembership"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("removeCampaignMembership", () => {
    it("posts to the campaign-scoped end route with the CSRF header, Idempotency-Key header, no body, and same-origin credentials", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    campaign_membership_id: "membership/1",
                }),
                {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            removeCampaignMembership(
                "campaign/a b",
                "membership/1",
                "fixture-csrf-token",
                "fixture-idempotency-key",
                controller.signal,
            ),
        ).resolves.toEqual({
            campaign_membership_id: "membership/1",
        })

        expect(fetchMock).toHaveBeenCalledTimes(1)
        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/memberships/membership%2F1/end",
            {
                method: "POST",
                credentials: "same-origin",
                cache: "no-store",
                signal: controller.signal,
                headers: {
                    Accept: "application/json",
                    "X-CSRF-Token": "fixture-csrf-token",
                    "Idempotency-Key": "fixture-idempotency-key",
                },
            },
        )
    })

    it("passes no signal when the caller supplies none", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(
                new Response(
                    JSON.stringify({ campaign_membership_id: "m" }),
                    {
                        status: 200,
                        headers: { "Content-Type": "application/json" },
                    },
                ),
            ),
        )

        await removeCampaignMembership(
            "campaign-a",
            "membership-a",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

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

        const request = removeCampaignMembership(
            "campaign-a",
            "membership-a",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "RemoveCampaignMembershipRequestError",
            status: 401,
        })
    })

    it("throws the same typed error shape for a non-disclosing forbidden/not-found response", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 404 })),
        )

        const request = removeCampaignMembership(
            "campaign-a",
            "membership-a",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "RemoveCampaignMembershipRequestError",
            status: 404,
        })
    })

    it("throws a typed error for the last-manager rejection", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 400 })),
        )

        const request = removeCampaignMembership(
            "campaign-a",
            "membership-a",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "RemoveCampaignMembershipRequestError",
            status: 400,
        })
    })

    it("throws a typed error for a conflicting/stale target", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 409 })),
        )

        const request = removeCampaignMembership(
            "campaign-a",
            "membership-a",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "RemoveCampaignMembershipRequestError",
            status: 409,
        })
    })

    it("throws a typed error for a recoverable server failure", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 500 })),
        )

        const request = removeCampaignMembership(
            "campaign-a",
            "membership-a",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "RemoveCampaignMembershipRequestError",
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

        const request = removeCampaignMembership(
            "campaign-a",
            "membership-a",
            "fixture-csrf-token",
            "fixture-idempotency-key",
            controller.signal,
        )

        controller.abort()

        await expect(request).rejects.toMatchObject({
            name: "AbortError",
        })
    })
})
