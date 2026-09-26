import { afterEach, describe, expect, it, vi } from "vitest"
import { fetchPlatformAccounts, PlatformAccountsRequestError } from "./platformAccounts"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("fetchPlatformAccounts", () => {
    it("gets the list with no query params when none are given", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({ items: [], next_cursor: null }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(fetchPlatformAccounts({})).resolves.toEqual({ items: [], next_cursor: null })

        expect(fetchMock).toHaveBeenCalledWith("/api/admin/accounts", {
            method: "GET",
            credentials: "same-origin",
            cache: "no-store",
            signal: undefined,
            headers: { Accept: "application/json" },
        })
    })

    it("encodes q/status/limit/cursor as query params", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({ items: [], next_cursor: null }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        )
        vi.stubGlobal("fetch", fetchMock)

        await fetchPlatformAccounts({ q: "a b", status: "active", limit: 10, cursor: "c/1" })

        const [url] = fetchMock.mock.calls[0] as [string, RequestInit]
        expect(url).toBe("/api/admin/accounts?q=a+b&status=active&limit=10&cursor=c%2F1")
    })

    it("throws a typed request error for a non-disclosing rejection", async () => {
        vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 404 })))

        await expect(fetchPlatformAccounts({})).rejects.toMatchObject({
            name: "PlatformAccountsRequestError",
            status: 404,
        } satisfies Partial<PlatformAccountsRequestError>)
    })
})
