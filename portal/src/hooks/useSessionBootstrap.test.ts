import {
    act,
    renderHook,
    waitFor,
} from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { SESSION_EXPIRED_EVENT } from "../api/http"
import { fetchSessionBootstrap } from "../api/session"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { SessionBootstrap } from "../types/bootstrap"
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

describe("useSessionBootstrap request ownership", () => {
    type Bootstrap = typeof sessionBootstrapFixture
    const fresh: Bootstrap = { ...sessionBootstrapFixture, startup_campaign_id: "fresh-campaign" }
    const other: Bootstrap = { ...sessionBootstrapFixture, startup_campaign_id: "another" }

    interface Gate<T> {
        promise: Promise<T>
        resolve: (value: T) => void
        reject: (error: unknown) => void
    }

    function gate<T>(): Gate<T> {
        let resolve!: (value: T) => void
        let reject!: (error: unknown) => void
        const promise = new Promise<T>((res, rej) => {
            resolve = res
            reject = rej
        })
        return { promise, resolve, reject }
    }

    async function authenticatedHook() {
        fetchSessionBootstrapMock.mockResolvedValueOnce(sessionBootstrapFixture)
        const hook = renderHook(() => useSessionBootstrap())
        await waitFor(() => {
            expect(hook.result.current.state.status).toBe("authenticated")
        })
        return hook
    }

    it("an older authenticated refresh cannot restore a session that a newer reload found unauthenticated", async () => {
        const { result } = await authenticatedHook()
        const a = gate<Bootstrap | null>()
        const b = gate<Bootstrap | null>()
        fetchSessionBootstrapMock.mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise)

        let aResult: Promise<boolean> = Promise.resolve(true)
        act(() => {
            aResult = result.current.refresh()
        })
        act(() => result.current.reload())
        await act(async () => b.resolve(null))
        await waitFor(() => expect(result.current.state).toEqual({ status: "unauthenticated" }))

        await act(async () => a.resolve(fresh))
        expect(await aResult).toBe(false)
        expect(result.current.state).toEqual({ status: "unauthenticated" })
    })

    it("an older authenticated refresh cannot restore a session that expired while it was pending", async () => {
        const { result } = await authenticatedHook()
        const a = gate<Bootstrap | null>()
        fetchSessionBootstrapMock.mockReturnValueOnce(a.promise)

        let aResult: Promise<boolean> = Promise.resolve(true)
        act(() => {
            aResult = result.current.refresh()
        })
        act(() => {
            window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
        })
        expect(result.current.state).toEqual({ status: "unauthenticated" })

        await act(async () => a.resolve(fresh))
        expect(await aResult).toBe(false)
        expect(result.current.state).toEqual({ status: "unauthenticated" })
    })

    it("an older unauthenticated result cannot end a session that a newer read established", async () => {
        const { result } = await authenticatedHook()
        const a = gate<Bootstrap | null>()
        const b = gate<Bootstrap | null>()
        fetchSessionBootstrapMock.mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise)

        let aResult: Promise<boolean> = Promise.resolve(true)
        let bResult: Promise<boolean> = Promise.resolve(false)
        act(() => {
            aResult = result.current.refresh()
            // A newer read that carries its own signal never joins A.
            bResult = result.current.refresh(new AbortController().signal)
        })
        await act(async () => b.resolve(other))
        expect(await bResult).toBe(true)
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: other })

        await act(async () => a.resolve(null))
        expect(await aResult).toBe(false)
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: other })
    })

    it("an older authenticated result cannot replace a newer authenticated one", async () => {
        const { result } = await authenticatedHook()
        const a = gate<Bootstrap | null>()
        const b = gate<Bootstrap | null>()
        fetchSessionBootstrapMock.mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise)

        let aResult: Promise<boolean> = Promise.resolve(true)
        act(() => {
            aResult = result.current.refresh()
            void result.current.refresh(new AbortController().signal)
        })
        await act(async () => b.resolve(other))
        await act(async () => a.resolve(fresh))
        expect(await aResult).toBe(false)
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: other })
    })

    it("an obsolete failure is ignored, not thrown and not shown", async () => {
        const { result } = await authenticatedHook()
        const a = gate<Bootstrap | null>()
        fetchSessionBootstrapMock.mockReturnValueOnce(a.promise).mockResolvedValue(fresh)

        let aResult: Promise<boolean> = Promise.resolve(true)
        act(() => {
            aResult = result.current.refresh()
        })
        act(() => result.current.reload())
        await waitFor(() => expect(result.current.state).toEqual({ status: "authenticated", bootstrap: fresh }))

        await act(async () => a.reject(new Error("late failure")))
        expect(await aResult).toBe(false)
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: fresh })
    })

    it("a refresh made after an invalidation does not join the old request", async () => {
        const { result } = await authenticatedHook()
        const a = gate<Bootstrap | null>()
        fetchSessionBootstrapMock.mockReturnValueOnce(a.promise).mockResolvedValue(fresh)

        act(() => {
            void result.current.refresh()
        })
        const callsBefore = fetchSessionBootstrapMock.mock.calls.length
        act(() => {
            window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
        })
        let second = false
        await act(async () => {
            second = await result.current.refresh()
        })
        expect(fetchSessionBootstrapMock.mock.calls.length).toBe(callsBefore + 1)
        expect(second).toBe(true)
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: fresh })
        await act(async () => a.resolve(other))
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: fresh })
    })

    it("an old request settling does not clear a newer in-flight request, which later callers still join", async () => {
        const { result } = await authenticatedHook()
        const a = gate<Bootstrap | null>()
        const c = gate<Bootstrap | null>()
        fetchSessionBootstrapMock.mockReturnValueOnce(a.promise).mockReturnValueOnce(c.promise)

        act(() => {
            void result.current.refresh()
        })
        act(() => {
            window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
        })
        // C is the newer in-flight request.
        let cResult: Promise<boolean> = Promise.resolve(false)
        act(() => {
            cResult = result.current.refresh()
        })
        const callsWithC = fetchSessionBootstrapMock.mock.calls.length

        // A settles (late): it must not clear C's entry.
        await act(async () => a.resolve(other))
        let dResult: Promise<boolean> = Promise.resolve(false)
        act(() => {
            dResult = result.current.refresh()
        })
        expect(fetchSessionBootstrapMock.mock.calls.length).toBe(callsWithC)

        await act(async () => c.resolve(fresh))
        expect(await cResult).toBe(true)
        expect(await dResult).toBe(true)
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: fresh })
    })

    it("a result arriving after unmount is not applied and is reported as not applied", async () => {
        const { result, unmount } = await authenticatedHook()
        const a = gate<Bootstrap | null>()
        fetchSessionBootstrapMock.mockReturnValueOnce(a.promise)
        let aResult: Promise<boolean> = Promise.resolve(true)
        act(() => {
            aResult = result.current.refresh()
        })
        unmount()
        await act(async () => a.resolve(fresh))
        expect(await aResult).toBe(false)
    })

    it("an aborted signal-bearing refresh still resolves not applied and does not disturb a newer read", async () => {
        const { result } = await authenticatedHook()
        const a = gate<Bootstrap | null>()
        fetchSessionBootstrapMock.mockReturnValueOnce(a.promise)
        const controller = new AbortController()
        let aResult: Promise<boolean> = Promise.resolve(true)
        act(() => {
            aResult = result.current.refresh(controller.signal)
        })
        controller.abort()
        await act(async () => a.resolve(fresh))
        expect(await aResult).toBe(false)
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: sessionBootstrapFixture })
    })
})

describe("useSessionBootstrap idle-check ownership", () => {
    type Bootstrap = SessionBootstrap
    const lifetime: Bootstrap = {
        ...sessionBootstrapFixture,
        session_idle_timeout_seconds: 60,
        session_absolute_expires_at: null,
    }
    // A later bootstrap with a long idle window, so only the check under test is ever due.
    const newer: Bootstrap = { ...lifetime, startup_campaign_id: "newer", session_idle_timeout_seconds: 3600 }

    interface Gate<T> {
        promise: Promise<T>
        resolve: (value: T) => void
        reject: (error: unknown) => void
    }

    function gate<T>(): Gate<T> {
        let resolve!: (value: T) => void
        let reject!: (error: unknown) => void
        const promise = new Promise<T>((res, rej) => {
            resolve = res
            reject = rej
        })
        return { promise, resolve, reject }
    }

    // Signs in with `lifetime`, then runs the clock to the idle deadline so check A is in flight.
    async function withIdleCheckInFlight() {
        vi.useFakeTimers()
        fetchSessionBootstrapMock.mockResolvedValueOnce(lifetime)
        const hook = renderHook(() => useSessionBootstrap())
        await act(async () => {
            await vi.advanceTimersByTimeAsync(0)
        })
        expect(hook.result.current.state.status).toBe("authenticated")

        const a = gate<Bootstrap | null>()
        fetchSessionBootstrapMock.mockReturnValueOnce(a.promise)
        await act(async () => {
            await vi.advanceTimersByTimeAsync(62_000)
        })
        // Sign-in read plus the idle check.
        expect(fetchSessionBootstrapMock).toHaveBeenCalledTimes(2)
        return { ...hook, a }
    }

    afterEach(() => {
        vi.useRealTimers()
    })

    // Starts a refresh that overtakes check A and publishes `newer`.
    async function overtakeWithRefresh(result: { current: ReturnType<typeof useSessionBootstrap> }) {
        const b = gate<Bootstrap | null>()
        fetchSessionBootstrapMock.mockReturnValueOnce(b.promise)
        let bResult: Promise<boolean> = Promise.resolve(false)
        act(() => {
            bResult = result.current.refresh()
        })
        await act(async () => b.resolve(newer))
        expect(await bResult).toBe(true)
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: newer })
    }

    it("an idle check overtaken by a newer refresh cannot expire the session it overtook", async () => {
        const { result, a } = await withIdleCheckInFlight()
        await overtakeWithRefresh(result)

        await act(async () => a.resolve(null))
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: newer })

        // Nothing is left over from the obsolete check: no retry, no expiry later.
        await act(async () => {
            await vi.advanceTimersByTimeAsync(120_000)
        })
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: newer })
        expect(fetchSessionBootstrapMock).toHaveBeenCalledTimes(3)
    })

    it("ownership, not effect cleanup, stops an overtaken idle check: a newer read that publishes the identical bootstrap re-runs nothing", async () => {
        const { result, a } = await withIdleCheckInFlight()
        // Same reference: React bails out of the update, the idle effect is NOT re-run and not disposed.
        const b = gate<Bootstrap | null>()
        fetchSessionBootstrapMock.mockReturnValueOnce(b.promise)
        let bResult: Promise<boolean> = Promise.resolve(false)
        act(() => {
            bResult = result.current.refresh()
        })
        await act(async () => b.resolve(lifetime))
        expect(await bResult).toBe(true)

        await act(async () => a.resolve(null))
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: lifetime })
    })

    it("an overtaken idle check that resolves authenticated renews nothing and schedules nothing", async () => {
        const { result, a } = await withIdleCheckInFlight()
        await overtakeWithRefresh(result)

        await act(async () => a.resolve(lifetime))
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: newer })
        await act(async () => {
            await vi.advanceTimersByTimeAsync(120_000)
        })
        expect(fetchSessionBootstrapMock).toHaveBeenCalledTimes(3)
    })

    it("an overtaken idle check that is rejected does not retry", async () => {
        const { result, a } = await withIdleCheckInFlight()
        await overtakeWithRefresh(result)

        await act(async () => a.reject(new Error("offline")))
        await act(async () => {
            await vi.advanceTimersByTimeAsync(60_000)
        })
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: newer })
        expect(fetchSessionBootstrapMock).toHaveBeenCalledTimes(3)
    })

    it("an idle check that a reload overtook cannot expire the reload's session", async () => {
        const { result, a } = await withIdleCheckInFlight()
        const reloaded = gate<Bootstrap | null>()
        fetchSessionBootstrapMock.mockReturnValueOnce(reloaded.promise)
        act(() => result.current.reload())
        expect(result.current.state).toEqual({ status: "loading" })

        await act(async () => a.resolve(null))
        expect(result.current.state).toEqual({ status: "loading" })

        await act(async () => reloaded.resolve(newer))
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: newer })
    })

    it("an idle check that a session-expired event overtook neither retries nor renews", async () => {
        const { result, a } = await withIdleCheckInFlight()
        act(() => {
            window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
        })
        expect(result.current.state).toEqual({ status: "unauthenticated" })

        await act(async () => a.reject(new Error("offline")))
        await act(async () => {
            await vi.advanceTimersByTimeAsync(120_000)
        })
        expect(result.current.state).toEqual({ status: "unauthenticated" })
        expect(fetchSessionBootstrapMock).toHaveBeenCalledTimes(2)
    })

    it("a current idle check that finds 401 expires the session and invalidates an older refresh", async () => {
        vi.useFakeTimers()
        fetchSessionBootstrapMock.mockResolvedValueOnce(lifetime)
        const { result } = renderHook(() => useSessionBootstrap())
        await act(async () => {
            await vi.advanceTimersByTimeAsync(0)
        })
        // R is older than the idle check and still in flight when the check decides.
        const r = gate<Bootstrap | null>()
        fetchSessionBootstrapMock.mockReturnValueOnce(r.promise)
        let rResult: Promise<boolean> = Promise.resolve(true)
        act(() => {
            rResult = result.current.refresh()
        })
        fetchSessionBootstrapMock.mockResolvedValueOnce(null)
        await act(async () => {
            await vi.advanceTimersByTimeAsync(62_000)
        })
        expect(result.current.state).toEqual({ status: "unauthenticated" })

        await act(async () => r.resolve(newer))
        expect(await rResult).toBe(false)
        expect(result.current.state).toEqual({ status: "unauthenticated" })
    })

    it("a current idle check that is rejected retries later, as before", async () => {
        const { result, a } = await withIdleCheckInFlight()
        fetchSessionBootstrapMock.mockResolvedValueOnce(lifetime)
        await act(async () => a.reject(new Error("offline")))
        await act(async () => {
            await vi.advanceTimersByTimeAsync(30_000)
        })
        expect(fetchSessionBootstrapMock).toHaveBeenCalledTimes(3)
        expect(result.current.state.status).toBe("authenticated")
    })

    it("aborts an idle check with its effect, and the abort rejection neither expires nor retries", async () => {
        vi.useFakeTimers()
        fetchSessionBootstrapMock.mockResolvedValueOnce(lifetime)
        const { result, unmount } = renderHook(() => useSessionBootstrap())
        await act(async () => {
            await vi.advanceTimersByTimeAsync(0)
        })
        fetchSessionBootstrapMock.mockImplementationOnce(abortableRead)
        await act(async () => {
            await vi.advanceTimersByTimeAsync(62_000)
        })
        const signal = fetchSessionBootstrapMock.mock.calls[1]![0] as AbortSignal
        expect(signal.aborted).toBe(false)

        // A new bootstrap re-runs the effect: the old check's signal is aborted and its rejection ignored.
        await overtakeWithRefresh(result)
        expect(signal.aborted).toBe(true)
        await act(async () => {
            await vi.advanceTimersByTimeAsync(60_000)
        })
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: newer })
        expect(fetchSessionBootstrapMock).toHaveBeenCalledTimes(3)
        unmount()
    })

    it("unmounting aborts the idle check and a result arriving afterwards does nothing", async () => {
        const { unmount, a } = await withIdleCheckInFlight()
        const signal = fetchSessionBootstrapMock.mock.calls[1]![0] as AbortSignal | undefined
        unmount()
        expect(signal?.aborted).toBe(true)
        await act(async () => a.resolve(null))
        await act(async () => {
            await vi.advanceTimersByTimeAsync(120_000)
        })
        expect(fetchSessionBootstrapMock).toHaveBeenCalledTimes(2)
    })
})

// A read that settles like fetch: pending until the signal aborts, then an AbortError rejection.
function abortableRead(signal?: AbortSignal): Promise<never> {
    return new Promise((_resolve, reject) => {
        const fail = () => reject(new DOMException("Aborted", "AbortError"))
        if (signal?.aborted) {
            fail()
            return
        }
        signal?.addEventListener("abort", fail)
    })
}

describe("useSessionBootstrap abort contract", () => {
    async function authenticatedHook() {
        fetchSessionBootstrapMock.mockResolvedValueOnce(sessionBootstrapFixture)
        const hook = renderHook(() => useSessionBootstrap())
        await waitFor(() => {
            expect(hook.result.current.state.status).toBe("authenticated")
        })
        return hook
    }

    it("a current request whose own signal is aborted rejects with the AbortError and changes nothing", async () => {
        const { result } = await authenticatedHook()
        fetchSessionBootstrapMock.mockImplementationOnce(abortableRead)
        const controller = new AbortController()
        let outcome: Promise<boolean> = Promise.resolve(true)
        act(() => {
            outcome = result.current.refresh(controller.signal)
        })
        // Attach before aborting so the rejection is never unhandled.
        const settled = outcome.then(
            () => "resolved" as const,
            (cause: unknown) => (cause instanceof DOMException ? cause.name : "other"),
        )
        controller.abort()
        expect(await settled).toBe("AbortError")
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: sessionBootstrapFixture })
    })

    it("a superseded request whose AbortError arrives late resolves not applied instead of rejecting", async () => {
        const { result } = await authenticatedHook()
        fetchSessionBootstrapMock.mockImplementationOnce(abortableRead).mockResolvedValue(sessionBootstrapFixture)
        const controller = new AbortController()
        let outcome: Promise<boolean> = Promise.resolve(true)
        act(() => {
            outcome = result.current.refresh(controller.signal)
        })
        // A reload supersedes it; only afterwards does the caller clean up and abort.
        act(() => result.current.reload())
        await waitFor(() => expect(result.current.state.status).toBe("authenticated"))
        controller.abort()
        expect(await outcome).toBe(false)
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: sessionBootstrapFixture })
    })

    it("another failure of a current request rejects and leaves the state alone", async () => {
        const { result } = await authenticatedHook()
        const failure = new Error("server error")
        fetchSessionBootstrapMock.mockRejectedValueOnce(failure)
        let current: Promise<boolean> = Promise.resolve(true)
        act(() => {
            current = result.current.refresh()
        })
        await expect(current).rejects.toBe(failure)
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: sessionBootstrapFixture })
    })

    it("a fetch that resolves after its own signal was aborted resolves not applied", async () => {
        const { result } = await authenticatedHook()
        let release!: (value: SessionBootstrap) => void
        fetchSessionBootstrapMock.mockReturnValueOnce(
            new Promise<SessionBootstrap>((resolve) => {
                release = resolve
            }),
        )
        const controller = new AbortController()
        let outcome: Promise<boolean> = Promise.resolve(true)
        act(() => {
            outcome = result.current.refresh(controller.signal)
        })
        controller.abort()
        await act(async () => release({ ...sessionBootstrapFixture, startup_campaign_id: null }))
        expect(await outcome).toBe(false)
        expect(result.current.state).toEqual({ status: "authenticated", bootstrap: sessionBootstrapFixture })
    })
})
