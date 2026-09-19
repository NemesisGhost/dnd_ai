import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { addCampaignMember } from "./addCampaignMember"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("addCampaignMember", () => {
    it("posts to the campaign-scoped memberships route with the CSRF header, Idempotency-Key header, JSON body, and same-origin credentials", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    campaign_membership_id: "new-membership",
                    membership_role_id: "new-membership-role",
                }),
                {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            addCampaignMember(
                "campaign/a b",
                "user-1",
                "role-2",
                "fixture-csrf-token",
                "fixture-idempotency-key",
                controller.signal,
            ),
        ).resolves.toEqual({
            campaign_membership_id: "new-membership",
            membership_role_id: "new-membership-role",
        })

        expect(fetchMock).toHaveBeenCalledTimes(1)
        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/memberships",
            {
                method: "POST",
                credentials: "same-origin",
                cache: "no-store",
                signal: controller.signal,
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-CSRF-Token": "fixture-csrf-token",
                    "Idempotency-Key": "fixture-idempotency-key",
                },
                body: JSON.stringify({
                    user_id: "user-1",
                    role_id: "role-2",
                }),
            },
        )
    })

    it("passes no signal when the caller supplies none", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(
                new Response(
                    JSON.stringify({
                        campaign_membership_id: "m",
                        membership_role_id: "r",
                    }),
                    {
                        status: 201,
                        headers: { "Content-Type": "application/json" },
                    },
                ),
            ),
        )

        await addCampaignMember(
            "campaign-a",
            "user-a",
            "role-b",
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

        const request = addCampaignMember(
            "campaign-a",
            "user-a",
            "role-b",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "AddCampaignMemberRequestError",
            status: 401,
        })
    })

    it("throws the same typed error shape for a non-disclosing forbidden/not-found response", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 404 })),
        )

        const request = addCampaignMember(
            "campaign-a",
            "user-a",
            "role-b",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "AddCampaignMemberRequestError",
            status: 404,
        })
    })

    it("throws a typed error for a conflicting duplicate/ineligible target", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 409 })),
        )

        const request = addCampaignMember(
            "campaign-a",
            "user-a",
            "role-b",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "AddCampaignMemberRequestError",
            status: 409,
        })
    })

    it("throws a typed error for a recoverable server failure", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 500 })),
        )

        const request = addCampaignMember(
            "campaign-a",
            "user-a",
            "role-b",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "AddCampaignMemberRequestError",
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

        const request = addCampaignMember(
            "campaign-a",
            "user-a",
            "role-b",
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
