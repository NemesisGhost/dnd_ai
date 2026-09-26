import { afterEach, describe, expect, it, vi } from "vitest"
import { changePassword, ChangePasswordRequestError } from "./changePassword"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("changePassword", () => {
    it("posts current/new password with csrf and same-origin credentials", async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            changePassword("old-password-15-chars", "new-password-15-chars", "csrf-token"),
        ).resolves.toBeUndefined()

        expect(fetchMock).toHaveBeenCalledWith("/api/auth/change-password", {
            method: "POST",
            credentials: "same-origin",
            cache: "no-store",
            signal: undefined,
            headers: {
                Accept: "application/json",
                "Content-Type": "application/json",
                "X-CSRF-Token": "csrf-token",
            },
            body: JSON.stringify({
                current_password: "old-password-15-chars",
                new_password: "new-password-15-chars",
            }),
        })
    })

    it("throws a typed request error for a non-disclosing rejection", async () => {
        vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })))

        await expect(
            changePassword("wrong", "new-password-15-chars", "csrf-token"),
        ).rejects.toMatchObject({
            name: "ChangePasswordRequestError",
            status: 401,
        } satisfies Partial<ChangePasswordRequestError>)
    })
})
