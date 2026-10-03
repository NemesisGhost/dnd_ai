import { afterEach, describe, expect, it, vi } from "vitest"
import { checkPasswordResetLink, PasswordResetStatusError } from "./passwordResetStatus"

afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
})

function stub(response: Response | Error) {
    const fetchMock = vi.fn(() => (response instanceof Error ? Promise.reject(response) : Promise.resolve(response)))
    vi.stubGlobal("fetch", fetchMock)
    return fetchMock
}

describe("checkPasswordResetLink", () => {
    it("POSTs the token in the JSON body only, with same-origin credentials", async () => {
        const fetchMock = stub(new Response(JSON.stringify({ valid: true }), { status: 200 }))
        await expect(checkPasswordResetLink("raw-token")).resolves.toBe(true)
        const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
        expect(url).toBe("/api/auth/password-reset-status")
        expect(init.method).toBe("POST")
        expect(init.credentials).toBe("same-origin")
        expect(init.cache).toBe("no-store")
        expect(init.body).toBe(JSON.stringify({ token: "raw-token" }))
        expect(JSON.stringify(init.headers)).not.toContain("raw-token")
    })

    it("resolves false for valid:false and for a definitive 4xx", async () => {
        stub(new Response(JSON.stringify({ valid: false }), { status: 200 }))
        await expect(checkPasswordResetLink("t")).resolves.toBe(false)
        stub(new Response("{}", { status: 404 }))
        await expect(checkPasswordResetLink("t")).resolves.toBe(false)
    })

    it.each([408, 500, 502])("throws a recoverable, non-rate-limited error for %s", async (status) => {
        stub(new Response("{}", { status }))
        await expect(checkPasswordResetLink("t")).rejects.toMatchObject({
            name: "PasswordResetStatusError",
            rateLimited: false,
        })
    })

    it("flags 429 as rate limited rather than invalid", async () => {
        stub(new Response("{}", { status: 429 }))
        await expect(checkPasswordResetLink("t")).rejects.toMatchObject({ rateLimited: true })
    })

    it("throws a recoverable error for a network failure or unreadable body", async () => {
        stub(new TypeError("offline"))
        await expect(checkPasswordResetLink("t")).rejects.toBeInstanceOf(PasswordResetStatusError)
        stub(new Response("not json", { status: 200 }))
        await expect(checkPasswordResetLink("t")).rejects.toBeInstanceOf(PasswordResetStatusError)
        stub(new Response(JSON.stringify({ valid: "yes" }), { status: 200 }))
        await expect(checkPasswordResetLink("t")).rejects.toBeInstanceOf(PasswordResetStatusError)
    })

    it("treats a timeout as recoverable and never leaks the token into the message", async () => {
        vi.useFakeTimers()
        vi.stubGlobal(
            "fetch",
            vi.fn(
                (_url: string, init: RequestInit) =>
                    new Promise((_resolve, reject) => {
                        init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")))
                    }),
            ),
        )
        const pending = checkPasswordResetLink("secret-token")
        const assertion = expect(pending).rejects.toThrow("timed out")
        await vi.advanceTimersByTimeAsync(16_000)
        await assertion
        await expect(pending).rejects.not.toThrow(/secret-token/)
    })

    it("propagates a caller abort as an abort, not as a recoverable error", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(
                (_url: string, init: RequestInit) =>
                    new Promise((_resolve, reject) => {
                        init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")))
                    }),
            ),
        )
        const controller = new AbortController()
        const pending = checkPasswordResetLink("t", controller.signal)
        controller.abort()
        await expect(pending).rejects.not.toBeInstanceOf(PasswordResetStatusError)
    })
})
