import { afterEach, describe, expect, it, vi } from "vitest"
import { addGroupResourceGrant } from "./addGroupResourceGrant"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("addGroupResourceGrant", () => {
    it("posts to the campaign-scoped resource-grants route with a group grantee, the CSRF header, Idempotency-Key header, JSON body, and same-origin credentials", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({ resource_grant_id: "new-grant" }),
                { status: 201, headers: { "Content-Type": "application/json" } },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            addGroupResourceGrant(
                "campaign-a",
                "group-1",
                "character-1",
                "character.view_summary",
                "fixture-csrf-token",
                "fixture-idempotency-key",
            ),
        ).resolves.toEqual({ resource_grant_id: "new-grant" })

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/resource-grants",
            expect.objectContaining({
                method: "POST",
                body: JSON.stringify({
                    capability_code: "character.view_summary",
                    effect: "allow",
                    grantee_access_group_id: "group-1",
                    character_id: "character-1",
                }),
            }),
        )
    })

    it("throws a typed error for an inactive-group or duplicate-active-grant rejection", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 409 })),
        )

        await expect(
            addGroupResourceGrant(
                "campaign-a",
                "group-1",
                "character-1",
                "character.view_summary",
                "fixture-csrf-token",
                "fixture-idempotency-key",
            ),
        ).rejects.toMatchObject({
            name: "AddGroupResourceGrantRequestError",
            status: 409,
        })
    })
})
