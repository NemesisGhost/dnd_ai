import { afterEach, describe, expect, it, vi } from "vitest"
import { reactivateAccessGroup } from "./reactivateAccessGroup"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("reactivateAccessGroup", () => {
    it("posts to the group-scoped reactivate route with no body, the CSRF header, Idempotency-Key header, and same-origin credentials", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({ access_group_id: "group-1", name: "Lore Circle" }),
                { status: 200, headers: { "Content-Type": "application/json" } },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            reactivateAccessGroup(
                "campaign-a",
                "group-1",
                "fixture-csrf-token",
                "fixture-idempotency-key",
            ),
        ).resolves.toEqual({ access_group_id: "group-1", name: "Lore Circle" })

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/access-groups/group-1/reactivate",
            expect.objectContaining({ method: "POST" }),
        )
    })

    it("throws a typed error for a conflicting/inactive-campaign rejection", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 409 })),
        )

        await expect(
            reactivateAccessGroup(
                "campaign-a",
                "group-1",
                "fixture-csrf-token",
                "fixture-idempotency-key",
            ),
        ).rejects.toMatchObject({
            name: "ReactivateAccessGroupRequestError",
            status: 409,
        })
    })
})
