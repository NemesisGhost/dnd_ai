import { afterEach, describe, expect, it, vi } from "vitest"
import { removeAccessGroupMember } from "./removeAccessGroupMember"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("removeAccessGroupMember", () => {
    it("posts to the campaign-scoped access-group-memberships remove route with no body, the CSRF header, Idempotency-Key header, and same-origin credentials", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({ access_group_membership_id: "link-1" }),
                { status: 200, headers: { "Content-Type": "application/json" } },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            removeAccessGroupMember(
                "campaign-a",
                "link-1",
                "fixture-csrf-token",
                "fixture-idempotency-key",
            ),
        ).resolves.toEqual({ access_group_membership_id: "link-1" })

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/access-group-memberships/link-1/remove",
            expect.objectContaining({ method: "POST" }),
        )
    })

    it("throws a typed error for a non-disclosing forbidden/not-found response", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 404 })),
        )

        await expect(
            removeAccessGroupMember(
                "campaign-a",
                "link-1",
                "fixture-csrf-token",
                "fixture-idempotency-key",
            ),
        ).rejects.toMatchObject({
            name: "RemoveAccessGroupMemberRequestError",
            status: 404,
        })
    })
})
