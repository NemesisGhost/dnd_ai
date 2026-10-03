import { afterEach, describe, expect, it, vi } from "vitest"
import { issuePasswordReset } from "./issuePasswordReset"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("issuePasswordReset", () => {
    it("posts revoke_sessions with csrf and same-origin credentials", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    user_id: "user-1",
                    raw_reset_token: "raw-reset-token",
                    expires_at: "2026-10-01T00:00:00Z",
                }),
                { status: 201, headers: { "Content-Type": "application/json" } },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(issuePasswordReset("user/1", true, "csrf-token")).resolves.toEqual({
            user_id: "user-1",
            raw_reset_token: "raw-reset-token",
            expires_at: "2026-10-01T00:00:00Z",
        })

        expect(fetchMock).toHaveBeenCalledWith("/api/admin/accounts/user%2F1/password-reset", {
            method: "POST",
            credentials: "same-origin",
            cache: "no-store",
            signal: undefined,
            headers: {
                Accept: "application/json",
                "Content-Type": "application/json",
                "X-CSRF-Token": "csrf-token",
            },
            body: JSON.stringify({ revoke_sessions: true }),
        })
    })
})
