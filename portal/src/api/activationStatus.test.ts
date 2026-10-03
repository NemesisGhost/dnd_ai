import { afterEach, describe, expect, it, vi } from "vitest"
import { ActivationStatusError, checkActivationLink } from "./activationStatus"

afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
})

function stub(response: Response | Error) {
    const fetchMock = vi.fn(() => (response instanceof Error ? Promise.reject(response) : Promise.resolve(response)))
    vi.stubGlobal("fetch", fetchMock)
    return fetchMock
}

describe("checkActivationLink", () => {
    it("POSTs the token in the JSON body only, with same-origin credentials", async () => {
        const fetchMock = stub(new Response(JSON.stringify({ valid: true }), { status: 200 }))
        await expect(checkActivationLink("raw-token")).resolves.toBe(true)
        const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
        expect(url).toBe("/api/auth/activation-status")
        expect(init.method).toBe("POST")
        expect(init.credentials).toBe("same-origin")
        expect(init.cache).toBe("no-store")
        expect(init.body).toBe(JSON.stringify({ token: "raw-token" }))
        expect(JSON.stringify(init.headers)).not.toContain("raw-token")
    })

    it("resolves false for valid:false and for a definitive 4xx", async () => {
        stub(new Response(JSON.stringify({ valid: false }), { status: 200 }))
        await expect(checkActivationLink("t")).resolves.toBe(false)
        stub(new Response("{}", { status: 404 }))
        await expect(checkActivationLink("t")).resolves.toBe(false)
    })

    it.each([408, 429, 500, 502])("throws a recoverable error for %s", async (status) => {
        stub(new Response("{}", { status }))
        await expect(checkActivationLink("t")).rejects.toBeInstanceOf(ActivationStatusError)
    })

    it("throws a recoverable error for a network failure or unreadable body", async () => {
        stub(new TypeError("offline"))
        await expect(checkActivationLink("t")).rejects.toBeInstanceOf(ActivationStatusError)
        stub(new Response("not json", { status: 200 }))
        await expect(checkActivationLink("t")).rejects.toBeInstanceOf(ActivationStatusError)
        stub(new Response(JSON.stringify({ valid: "yes" }), { status: 200 }))
        await expect(checkActivationLink("t")).rejects.toBeInstanceOf(ActivationStatusError)
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
        const pending = checkActivationLink("secret-token")
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
        const pending = checkActivationLink("t", controller.signal)
        controller.abort()
        await expect(pending).rejects.not.toBeInstanceOf(ActivationStatusError)
    })
})
