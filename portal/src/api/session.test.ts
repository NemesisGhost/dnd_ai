import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { fetchSessionBootstrap } from "./session"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("fetchSessionBootstrap", () => {
    it("returns the session bootstrap from a successful response", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify(sessionBootstrapFixture), {
                status: 200,
                headers: {
                    "Content-Type": "application/json",
                },
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(fetchSessionBootstrap()).resolves.toEqual(
            sessionBootstrapFixture,
        )

        expect(fetchMock).toHaveBeenCalledTimes(1)

        expect(fetchMock).toHaveBeenCalledWith("/auth/session", {
            method: "GET",
            credentials: "same-origin",
            cache: "no-store",
            headers: {
                Accept: "application/json",
            },
        })
    })

    it("returns null when the browser is not authenticated", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(null, {
                status: 401,
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(fetchSessionBootstrap()).resolves.toBeNull()
    })

    it("throws when the server returns an unexpected error", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(null, {
                status: 500,
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(fetchSessionBootstrap()).rejects.toThrow(
            "Session bootstrap request failed with status 500",
        )
    })

    it("preserves network failures for the caller to handle", async () => {
        const networkError = new TypeError("Failed to fetch")
        const fetchMock = vi.fn().mockRejectedValue(networkError)

        vi.stubGlobal("fetch", fetchMock)

        await expect(fetchSessionBootstrap()).rejects.toBe(networkError)
    })
})