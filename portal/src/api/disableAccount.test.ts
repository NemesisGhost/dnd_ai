import { afterEach, describe, expect, it, vi } from "vitest"
import { disableAccount } from "./disableAccount"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("disableAccount", () => {
    it("posts with csrf and same-origin credentials, no body", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    user_id: "user-1",
                    previous_lifecycle_status: "active",
                    new_lifecycle_status: "inactive",
                }),
                { status: 200, headers: { "Content-Type": "application/json" } },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(disableAccount("user-1", "csrf-token")).resolves.toEqual({
            user_id: "user-1",
            previous_lifecycle_status: "active",
            new_lifecycle_status: "inactive",
        })

        expect(fetchMock).toHaveBeenCalledWith("/api/admin/accounts/user-1/disable", {
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
