import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { addResourceGrant } from "./addResourceGrant"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("addResourceGrant", () => {
    it("posts to the campaign-scoped resource-grants route with the CSRF header, Idempotency-Key header, JSON body, and same-origin credentials", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({ resource_grant_id: "new-grant" }),
                {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            addResourceGrant(
                "campaign/a b",
                "membership/1",
                "character-2",
                "character.view_full",
                "fixture-csrf-token",
                "fixture-idempotency-key",
                controller.signal,
            ),
        ).resolves.toEqual({ resource_grant_id: "new-grant" })

        expect(fetchMock).toHaveBeenCalledTimes(1)
        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/resource-grants",
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
                    capability_code: "character.view_full",
                    effect: "allow",
                    grantee_campaign_membership_id: "membership/1",
                    character_id: "character-2",
                }),
            },
        )
    })

    it("throws a typed error for a non-disclosing forbidden/not-found response", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 404 })),
        )

        const request = addResourceGrant(
            "campaign-a",
            "membership-a",
            "character-a",
            "character.view_full",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "AddResourceGrantRequestError",
            status: 404,
        })
    })

    it("throws a typed error for a conflicting duplicate/ineligible target", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 409 })),
        )

        const request = addResourceGrant(
            "campaign-a",
            "membership-a",
            "character-a",
            "character.view_full",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "AddResourceGrantRequestError",
            status: 409,
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

        const request = addResourceGrant(
            "campaign-a",
            "membership-a",
            "character-a",
            "character.view_full",
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
