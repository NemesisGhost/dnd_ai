import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { revokeResourceGrant } from "./revokeResourceGrant"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("revokeResourceGrant", () => {
    it("posts to the campaign-scoped revoke route with the CSRF header, Idempotency-Key header, and same-origin credentials, no body", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({ resource_grant_id: "grant-1" }),
                {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            revokeResourceGrant(
                "campaign/a b",
                "grant/1",
                "fixture-csrf-token",
                "fixture-idempotency-key",
                controller.signal,
            ),
        ).resolves.toEqual({ resource_grant_id: "grant-1" })

        expect(fetchMock).toHaveBeenCalledTimes(1)
        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/resource-grants/grant%2F1/revoke",
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

    it("throws a typed error for a non-disclosing forbidden/not-found response", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 404 })),
        )

        const request = revokeResourceGrant(
            "campaign-a",
            "grant-a",
            "fixture-csrf-token",
            "fixture-idempotency-key",
        )

        await expect(request).rejects.toMatchObject({
            name: "RevokeResourceGrantRequestError",
            status: 404,
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

        const request = revokeResourceGrant(
            "campaign-a",
            "grant-a",
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
