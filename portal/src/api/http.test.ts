import { afterEach, describe, expect, it, vi } from "vitest"
import { ApiRequestError, apiRequest } from "./http"

function respond(status: number, body?: unknown): Response {
    return new Response(body === undefined ? null : JSON.stringify(body), { status })
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("apiRequest", () => {
    it("sends same-origin credentials, no-store, and JSON headers on a GET without a CSRF token", async () => {
        const fetchMock = vi.fn().mockResolvedValue(respond(200, { ok: true }))
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            apiRequest("GET", "/worlds", { csrfToken: "csrf", idempotencyKey: "key" }),
        ).resolves.toEqual({ ok: true })

        const [url, init] = fetchMock.mock.calls[0]!
        expect(url).toBe("/api/worlds")
        expect(init).toMatchObject({
            method: "GET",
            credentials: "same-origin",
            cache: "no-store",
        })
        expect(init.headers).toEqual({ Accept: "application/json" })
        expect(init.body).toBeUndefined()
    })

    it("sends the CSRF token, the idempotency key, and a JSON body on a POST", async () => {
        const fetchMock = vi.fn().mockResolvedValue(respond(201, { id: "x" }))
        vi.stubGlobal("fetch", fetchMock)

        await apiRequest("POST", "/worlds", {
            body: { name: "Eberron" },
            csrfToken: "csrf-token",
            idempotencyKey: "idem-1",
        })

        const [, init] = fetchMock.mock.calls[0]!
        expect(init.headers).toEqual({
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-CSRF-Token": "csrf-token",
            "Idempotency-Key": "idem-1",
        })
        expect(JSON.parse(init.body)).toEqual({ name: "Eberron" })
    })

    it("returns undefined for 204", async () => {
        vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(204)))
        await expect(apiRequest("POST", "/x")).resolves.toBeUndefined()
    })

    it("parses the stable error code and correlation id from the envelope", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(
                respond(409, {
                    error: { code: "stale_write", message: "m", correlation_id: "corr-1" },
                }),
            ),
        )
        const failure = await apiRequest("POST", "/x").catch((e: unknown) => e)
        expect(failure).toBeInstanceOf(ApiRequestError)
        expect(failure).toMatchObject({ status: 409, code: "stale_write", correlationId: "corr-1" })
    })

    it("tolerates a non-JSON error body", async () => {
        vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>bad gateway</html>", { status: 502 })))
        const failure = await apiRequest("GET", "/x").catch((e: unknown) => e)
        expect(failure).toMatchObject({ status: 502, code: null, correlationId: null })
    })

    it("reports a network failure as status 0", async () => {
        vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")))
        const failure = await apiRequest("GET", "/x").catch((e: unknown) => e)
        expect(failure).toMatchObject({ status: 0, code: "network_error" })
    })

    it("rethrows an abort instead of calling it a network failure", async () => {
        const controller = new AbortController()
        controller.abort()
        const abort = new DOMException("aborted", "AbortError")
        vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abort))
        await expect(apiRequest("GET", "/x", { signal: controller.signal })).rejects.toBe(abort)
    })
})
