import {
    act,
    renderHook,
    waitFor,
} from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { SESSION_EXPIRED_EVENT } from "../api/http"
import { fetchSessionBootstrap } from "../api/session"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { useSessionBootstrap } from "./useSessionBootstrap"

vi.mock("../api/session", () => ({
    fetchSessionBootstrap: vi.fn(),
}))

const fetchSessionBootstrapMock = vi.mocked(
    fetchSessionBootstrap,
)

beforeEach(() => {
    fetchSessionBootstrapMock.mockReset()
})

describe("useSessionBootstrap", () => {
    it("moves from loading to authenticated", async () => {
        fetchSessionBootstrapMock.mockResolvedValue(
            sessionBootstrapFixture,
        )

        const { result } = renderHook(() => useSessionBootstrap())

        expect(result.current.state).toEqual({
            status: "loading",
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "authenticated",
                bootstrap: sessionBootstrapFixture,
            })
        })
    })

    it("moves from loading to unauthenticated", async () => {
        fetchSessionBootstrapMock.mockResolvedValue(null)

        const { result } = renderHook(() => useSessionBootstrap())

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "unauthenticated",
            })
        })
    })

    it("moves from loading to error when the request fails", async () => {
        const error = new Error("Backend unavailable")

        fetchSessionBootstrapMock.mockRejectedValue(error)

        const { result } = renderHook(() => useSessionBootstrap())

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "error",
                error,
            })
        })
    })

    it("aborts the request when the hook unmounts", () => {
        let receivedSignal: AbortSignal | undefined

        fetchSessionBootstrapMock.mockImplementation((signal) => {
            receivedSignal = signal
            return new Promise<never>(() => { })
        })

        const { unmount } = renderHook(() => useSessionBootstrap())

        if (receivedSignal === undefined) {
            throw new Error("Expected the hook to provide an AbortSignal")
        }

        expect(receivedSignal.aborted).toBe(false)

        unmount()

        expect(receivedSignal.aborted).toBe(true)
    })

    it("returns to loading and requests fresh state when reloaded", async () => {
        let resolveReload: (() => void) | undefined

        const reloadRequest = new Promise<null>((resolve) => {
            resolveReload = () => {
                resolve(null)
            }
        })

        fetchSessionBootstrapMock
            .mockResolvedValueOnce(sessionBootstrapFixture)
            .mockReturnValueOnce(reloadRequest)

        const { result } = renderHook(() => useSessionBootstrap())

        await waitFor(() => {
            expect(result.current.state.status).toBe("authenticated")
        })

        act(() => {
            result.current.reload()
        })

        expect(result.current.state).toEqual({
            status: "loading",
        })

        expect(fetchSessionBootstrapMock).toHaveBeenCalledTimes(2)

        const completeReload = resolveReload

        if (completeReload === undefined) {
            throw new Error("Expected the reload request to be pending")
        }

        await act(async () => {
            completeReload()
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "unauthenticated",
            })
        })
    })

    describe("refresh", () => {
        const updated = {
            ...sessionBootstrapFixture,
            startup_campaign_id: null,
        }

        async function authenticatedHook() {
            fetchSessionBootstrapMock.mockResolvedValueOnce(sessionBootstrapFixture)
            const hook = renderHook(() => useSessionBootstrap())
            await waitFor(() => {
                expect(hook.result.current.state.status).toBe("authenticated")
            })
            return hook
        }

        it("replaces the bootstrap in place without passing through loading", async () => {
            const { result } = await authenticatedHook()
            fetchSessionBootstrapMock.mockResolvedValueOnce(updated)
            const seen: string[] = []

            let applied = false
            await act(async () => {
                const pending = result.current.refresh()
                seen.push(result.current.state.status)
                applied = await pending
            })

            expect(seen).toEqual(["authenticated"])
            expect(applied).toBe(true)
            expect(result.current.state).toEqual({ status: "authenticated", bootstrap: updated })
        })

        it("becomes unauthenticated and resolves false on a 401", async () => {
            const { result } = await authenticatedHook()
            fetchSessionBootstrapMock.mockResolvedValueOnce(null)

            let applied = true
            await act(async () => {
                applied = await result.current.refresh()
            })

            expect(applied).toBe(false)
            expect(result.current.state).toEqual({ status: "unauthenticated" })
        })

        it("rejects and keeps the previous bootstrap when the request fails", async () => {
            const { result } = await authenticatedHook()
            fetchSessionBootstrapMock.mockRejectedValueOnce(new Error("boom"))

            await act(async () => {
                await expect(result.current.refresh()).rejects.toThrow("boom")
            })

            expect(result.current.state).toEqual({
                status: "authenticated",
                bootstrap: sessionBootstrapFixture,
            })
        })

        it("does not apply a result for an aborted refresh", async () => {
            const { result } = await authenticatedHook()
            fetchSessionBootstrapMock.mockResolvedValueOnce(updated)
            const controller = new AbortController()
            controller.abort()

            let applied = true
            await act(async () => {
                applied = await result.current.refresh(controller.signal)
            })

            expect(applied).toBe(false)
            expect(result.current.state).toEqual({
                status: "authenticated",
                bootstrap: sessionBootstrapFixture,
            })
        })
    })

    describe("session expiry", () => {
        const withLifetime = {
            ...sessionBootstrapFixture,
            session_idle_timeout_seconds: 60,
            session_absolute_expires_at: null,
        }

        it("signs out when the idle deadline passes and the server says 401", async () => {
            vi.useFakeTimers()
            try {
                fetchSessionBootstrapMock.mockResolvedValueOnce(withLifetime)
                const { result } = renderHook(() => useSessionBootstrap())
                await act(async () => {
                    await vi.advanceTimersByTimeAsync(0)
                })
                expect(result.current.state.status).toBe("authenticated")

                fetchSessionBootstrapMock.mockResolvedValueOnce(null)
                await act(async () => {
                    await vi.advanceTimersByTimeAsync(62_000)
                })
                expect(result.current.state.status).toBe("unauthenticated")
            } finally {
                vi.useRealTimers()
            }
        })

        it("stays signed in when the server still accepts the session", async () => {
            vi.useFakeTimers()
            try {
                fetchSessionBootstrapMock.mockResolvedValue(withLifetime)
                const { result } = renderHook(() => useSessionBootstrap())
                await act(async () => {
                    await vi.advanceTimersByTimeAsync(62_000)
                })
                expect(result.current.state.status).toBe("authenticated")
            } finally {
                vi.useRealTimers()
            }
        })

        it("signs out immediately on a session-expired event", async () => {
            fetchSessionBootstrapMock.mockResolvedValue(withLifetime)
            const { result } = renderHook(() => useSessionBootstrap())
            await waitFor(() =>
                expect(result.current.state.status).toBe("authenticated"),
            )
            act(() => {
                window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
            })
            expect(result.current.state.status).toBe("unauthenticated")
        })
    })
})

describe("useSessionBootstrap refresh coalescing", () => {
    async function authenticatedHook() {
        fetchSessionBootstrapMock.mockResolvedValueOnce(sessionBootstrapFixture)
        const hook = renderHook(() => useSessionBootstrap())
        await waitFor(() => {
            expect(hook.result.current.state.status).toBe("authenticated")
        })
        return hook
    }

    it("shares one request among argument-free refreshes made while it is in flight", async () => {
        const { result } = await authenticatedHook()
        const updated = { ...sessionBootstrapFixture, startup_campaign_id: null }
        let release!: (value: typeof updated) => void
        fetchSessionBootstrapMock.mockReturnValueOnce(
            new Promise<typeof updated>((resolve) => {
                release = resolve
            }),
        )

        let outcomes: boolean[] = []
        await act(async () => {
            const all = Promise.all([result.current.refresh(), result.current.refresh(), result.current.refresh()])
            release(updated)
            outcomes = await all
        })

        expect(outcomes).toEqual([true, true, true])
        // One read for sign-in and one shared refresh.
        expect(fetchSessionBootstrapMock).toHaveBeenCalledTimes(2)
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: updated })
    })

    it("reads again for a refresh made after the shared one finished", async () => {
        const { result } = await authenticatedHook()
        fetchSessionBootstrapMock.mockResolvedValue(sessionBootstrapFixture)

        await act(async () => {
            await result.current.refresh()
        })
        await act(async () => {
            await result.current.refresh()
        })

        expect(fetchSessionBootstrapMock).toHaveBeenCalledTimes(3)
    })

    it("does not share a refresh that carries its own abort signal", async () => {
        const { result } = await authenticatedHook()
        fetchSessionBootstrapMock.mockResolvedValue(sessionBootstrapFixture)

        await act(async () => {
            await Promise.all([result.current.refresh(), result.current.refresh(new AbortController().signal)])
        })

        expect(fetchSessionBootstrapMock).toHaveBeenCalledTimes(3)
    })

    it("a failed shared refresh rejects every caller and the next one reads again", async () => {
        const { result } = await authenticatedHook()
        fetchSessionBootstrapMock.mockRejectedValueOnce(new Error("boom"))

        await act(async () => {
            const results = await Promise.allSettled([result.current.refresh(), result.current.refresh()])
            expect(results.map((r) => r.status)).toEqual(["rejected", "rejected"])
        })
        fetchSessionBootstrapMock.mockResolvedValueOnce(sessionBootstrapFixture)
        await act(async () => {
            expect(await result.current.refresh()).toBe(true)
        })
    })
})
