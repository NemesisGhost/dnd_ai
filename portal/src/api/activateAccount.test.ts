import { afterEach, describe, expect, it, vi } from "vitest"
import { activateAccount, ActivateAccountRequestError } from "./activateAccount"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("activateAccount", () => {
    it("posts token and password in the body, same-origin credentials, no auth header", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({ user_id: "user-1", login_name: "new.gm" }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(activateAccount("raw-token", "correct-password-15-chars")).resolves.toEqual({
            user_id: "user-1",
            login_name: "new.gm",
        })

        expect(fetchMock).toHaveBeenCalledWith("/api/auth/activate", {
            method: "POST",
            credentials: "same-origin",
            cache: "no-store",
            signal: undefined,
            headers: {
                Accept: "application/json",
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ token: "raw-token", password: "correct-password-15-chars" }),
        })
    })

    it("throws a typed request error for a non-disclosing rejection", async () => {
        vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 404 })))

        await expect(activateAccount("raw-token", "password")).rejects.toMatchObject({
            name: "ActivateAccountRequestError",
            status: 404,
        } satisfies Partial<ActivateAccountRequestError>)
    })
})
