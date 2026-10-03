import { afterEach, describe, expect, it, vi } from "vitest"
import { reactivateAccount } from "./reactivateAccount"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("reactivateAccount", () => {
    it("posts with csrf and same-origin credentials, no body", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    user_id: "user-1",
                    previous_lifecycle_status: "inactive",
                    new_lifecycle_status: "active",
                }),
                { status: 200, headers: { "Content-Type": "application/json" } },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(reactivateAccount("user-1", "csrf-token")).resolves.toEqual({
            user_id: "user-1",
            previous_lifecycle_status: "inactive",
            new_lifecycle_status: "active",
        })

        expect(fetchMock).toHaveBeenCalledWith("/api/admin/accounts/user-1/reactivate", {
            method: "POST",
            credentials: "same-origin",
            cache: "no-store",
            signal: undefined,
            headers: {
                Accept: "application/json",
                "X-CSRF-Token": "csrf-token",
            },
        })
    })
})
