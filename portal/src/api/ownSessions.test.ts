import { afterEach, describe, expect, it, vi } from "vitest"
import { fetchOwnSessions, OwnSessionsRequestError, revokeOwnSession } from "./ownSessions"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("fetchOwnSessions", () => {
    it("gets the list with same-origin credentials", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify([]), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(fetchOwnSessions()).resolves.toEqual([])

        expect(fetchMock).toHaveBeenCalledWith("/api/auth/sessions", {
            method: "GET",
            credentials: "same-origin",
            cache: "no-store",
            signal: undefined,
            headers: { Accept: "application/json" },
        })
    })
})

describe("revokeOwnSession", () => {
    it("deletes with csrf and same-origin credentials", async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
        vi.stubGlobal("fetch", fetchMock)

        await expect(revokeOwnSession("session/1", "csrf-token")).resolves.toBeUndefined()

        expect(fetchMock).toHaveBeenCalledWith("/api/auth/sessions/session%2F1", {
            method: "DELETE",
            credentials: "same-origin",
            cache: "no-store",
            signal: undefined,
            headers: { "X-CSRF-Token": "csrf-token" },
        })
    })

    it("throws a typed request error for a non-disclosing rejection", async () => {
        vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 404 })))

        await expect(revokeOwnSession("session-1", "csrf-token")).rejects.toMatchObject({
            name: "OwnSessionsRequestError",
            status: 404,
        } satisfies Partial<OwnSessionsRequestError>)
    })
})
