import { afterEach, describe, expect, it, vi } from "vitest"
import { resetPassword, ResetPasswordRequestError } from "./resetPassword"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("resetPassword", () => {
    it("posts token and new_password in the body with same-origin credentials", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({ user_id: "user-1", sessions_revoked: true }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(resetPassword("raw-token", "new-password-15-chars")).resolves.toEqual({
            user_id: "user-1",
            sessions_revoked: true,
        })

        expect(fetchMock).toHaveBeenCalledWith("/api/auth/password-reset", {
            method: "POST",
            credentials: "same-origin",
            cache: "no-store",
            signal: undefined,
            headers: {
                Accept: "application/json",
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ token: "raw-token", new_password: "new-password-15-chars" }),
        })
    })

    it("throws a typed request error for a non-disclosing rejection", async () => {
        vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 400 })))

        await expect(resetPassword("raw-token", "weak")).rejects.toMatchObject({
            name: "ResetPasswordRequestError",
            status: 400,
        } satisfies Partial<ResetPasswordRequestError>)
    })
})
