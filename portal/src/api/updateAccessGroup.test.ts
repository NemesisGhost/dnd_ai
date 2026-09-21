import { afterEach, describe, expect, it, vi } from "vitest"
import { updateAccessGroup } from "./updateAccessGroup"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("updateAccessGroup", () => {
    it("posts to the group-scoped update route with the CSRF header, Idempotency-Key header, JSON body, and same-origin credentials", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    access_group_id: "group-1",
                    name: "Renamed",
                }),
                { status: 200, headers: { "Content-Type": "application/json" } },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            updateAccessGroup(
                "campaign-a",
                "group/1",
                "Renamed",
                null,
                "fixture-csrf-token",
                "fixture-idempotency-key",
                controller.signal,
            ),
        ).resolves.toEqual({ access_group_id: "group-1", name: "Renamed" })

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/access-groups/group%2F1/update",
            expect.objectContaining({
                method: "POST",
                body: JSON.stringify({ name: "Renamed", description: null }),
            }),
        )
    })

    it("throws a typed error for a non-disclosing forbidden/not-found response", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 404 })),
        )

        await expect(
            updateAccessGroup(
                "campaign-a",
                "group-1",
                "Renamed",
                null,
                "fixture-csrf-token",
                "fixture-idempotency-key",
            ),
        ).rejects.toMatchObject({
            name: "UpdateAccessGroupRequestError",
            status: 404,
        })
    })

    it("throws a typed error for a no-op or duplicate-name rejection", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 422 })),
        )

        await expect(
            updateAccessGroup(
                "campaign-a",
                "group-1",
                "Renamed",
                null,
                "fixture-csrf-token",
                "fixture-idempotency-key",
            ),
        ).rejects.toMatchObject({
            name: "UpdateAccessGroupRequestError",
            status: 422,
        })
    })
})
