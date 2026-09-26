import { afterEach, describe, expect, it, vi } from "vitest"
import { revokeAllSessions } from "./revokeAllSessions"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("revokeAllSessions", () => {
    it("posts with csrf and same-origin credentials, no body", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({ user_id: "user-1", revoked_count: 3 }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(revokeAllSessions("user-1", "csrf-token")).resolves.toEqual({
            user_id: "user-1",
            revoked_count: 3,
        })

        expect(fetchMock).toHaveBeenCalledWith("/api/admin/accounts/user-1/revoke-sessions", {
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
