import { afterEach, describe, expect, it, vi } from "vitest"
import { createAccessGroup } from "./createAccessGroup"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("createAccessGroup", () => {
    it("posts to the campaign-scoped access-groups route with the CSRF header, Idempotency-Key header, JSON body, and same-origin credentials", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    access_group_id: "new-group",
                    name: "Lore Circle",
                }),
                { status: 201, headers: { "Content-Type": "application/json" } },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            createAccessGroup(
                "campaign/a b",
                "Lore Circle",
                "For the lore fans",
                "fixture-csrf-token",
                "fixture-idempotency-key",
                controller.signal,
            ),
        ).resolves.toEqual({ access_group_id: "new-group", name: "Lore Circle" })

        expect(fetchMock).toHaveBeenCalledTimes(1)
        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/access-groups",
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
                    name: "Lore Circle",
                    description: "For the lore fans",
                }),
            },
        )
    })

    it("throws a typed error for a non-disclosing forbidden/not-found response", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 404 })),
        )

        await expect(
            createAccessGroup(
                "campaign-a",
                "Lore Circle",
                null,
                "fixture-csrf-token",
                "fixture-idempotency-key",
            ),
        ).rejects.toMatchObject({
            name: "CreateAccessGroupRequestError",
            status: 404,
        })
    })

    it("throws a typed error for a conflicting duplicate name", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 409 })),
        )

        await expect(
            createAccessGroup(
                "campaign-a",
                "Lore Circle",
                null,
                "fixture-csrf-token",
                "fixture-idempotency-key",
            ),
        ).rejects.toMatchObject({
            name: "CreateAccessGroupRequestError",
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

        const request = createAccessGroup(
            "campaign-a",
            "Lore Circle",
            null,
            "fixture-csrf-token",
            "fixture-idempotency-key",
            controller.signal,
        )

        controller.abort()

        await expect(request).rejects.toMatchObject({ name: "AbortError" })
    })
})
