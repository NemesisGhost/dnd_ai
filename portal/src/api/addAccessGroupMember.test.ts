import { afterEach, describe, expect, it, vi } from "vitest"
import { addAccessGroupMember } from "./addAccessGroupMember"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("addAccessGroupMember", () => {
    it("posts to the group-scoped members route with the CSRF header, Idempotency-Key header, JSON body, and same-origin credentials", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({ access_group_membership_id: "link-1" }),
                { status: 201, headers: { "Content-Type": "application/json" } },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            addAccessGroupMember(
                "campaign-a",
                "group-1",
                "membership-1",
                "fixture-csrf-token",
                "fixture-idempotency-key",
            ),
        ).resolves.toEqual({ access_group_membership_id: "link-1" })

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/access-groups/group-1/members",
            expect.objectContaining({
                method: "POST",
                body: JSON.stringify({ campaign_membership_id: "membership-1" }),
            }),
        )
    })

    it("throws a typed error for a duplicate-active-member or ineligible-membership rejection", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 409 })),
        )

        await expect(
            addAccessGroupMember(
                "campaign-a",
                "group-1",
                "membership-1",
                "fixture-csrf-token",
                "fixture-idempotency-key",
            ),
        ).rejects.toMatchObject({
            name: "AddAccessGroupMemberRequestError",
            status: 409,
        })
    })
})
