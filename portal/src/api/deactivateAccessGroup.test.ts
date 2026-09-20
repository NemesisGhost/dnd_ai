import { afterEach, describe, expect, it, vi } from "vitest"
import { deactivateAccessGroup } from "./deactivateAccessGroup"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("deactivateAccessGroup", () => {
    it("posts to the group-scoped deactivate route with no body, the CSRF header, Idempotency-Key header, and same-origin credentials", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({ access_group_id: "group-1", name: "Lore Circle" }),
                { status: 200, headers: { "Content-Type": "application/json" } },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            deactivateAccessGroup(
                "campaign-a",
                "group-1",
                "fixture-csrf-token",
                "fixture-idempotency-key",
            ),
        ).resolves.toEqual({ access_group_id: "group-1", name: "Lore Circle" })

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/access-groups/group-1/deactivate",
            {
                method: "POST",
                credentials: "same-origin",
                cache: "no-store",
                signal: undefined,
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

        await expect(
            deactivateAccessGroup(
                "campaign-a",
                "group-1",
                "fixture-csrf-token",
                "fixture-idempotency-key",
            ),
        ).rejects.toMatchObject({
            name: "DeactivateAccessGroupRequestError",
            status: 404,
        })
    })
})
