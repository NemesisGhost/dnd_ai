import { act, renderHook, waitFor } from "@testing-library/react"
import type { PropsWithChildren } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { installMockServer } from "../test/authoringHarness"
import { useAuthoringResource } from "./useAuthoringResource"

function Wrapper({ children }: PropsWithChildren) {
    return (
        <SessionContext.Provider
            value={{
                state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
                reload: vi.fn(),
                refresh: vi.fn(),
            }}
        >
            {children}
        </SessionContext.Provider>
    )
}

afterEach(() => {
    vi.unstubAllGlobals()
})

// `startedSeq` orders reads by when they STARTED (docs/UI_DESIGN.md §4.8.12), so a later answer from an
// earlier read can never outrank a read that began after it.
describe("useAuthoringResource startedSeq", () => {
    it("is null while loading and set once the read settles, including a refusal", async () => {
        const server = installMockServer()
        server.on("GET", "/a", { body: {} })
        server.on("GET", "/b", { status: 404 })
        const { result, rerender } = renderHook(({ path }) => useAuthoringResource(path), {
            wrapper: Wrapper,
            initialProps: { path: "/a" },
        })
        expect(result.current.startedSeq).toBeNull()
        await waitFor(() => expect(result.current.state.kind).toBe("ready"))
        const first = result.current.startedSeq
        expect(first).toEqual(expect.any(Number))

        rerender({ path: "/b" })
        expect(result.current.startedSeq).toBeNull()
        await waitFor(() => expect(result.current.state.kind).toBe("unavailable"))
        expect(result.current.startedSeq).toBeGreaterThan(first!)
    })

    it("belongs to the data on screen: a refetch in flight keeps the earlier value until it answers", async () => {
        const server = installMockServer()
        let release!: () => void
        let calls = 0
        server.on("GET", "/a", () => {
            calls += 1
            return calls === 1
                ? { body: { n: 1 } }
                : new Promise((resolve) => {
                      release = () => resolve({ body: { n: 2 } })
                  })
        })
        const { result } = renderHook(() => useAuthoringResource<{ n: number }>("/a"), { wrapper: Wrapper })
        await waitFor(() => expect(result.current.state.kind).toBe("ready"))
        const first = result.current.startedSeq

        let pending!: Promise<unknown>
        act(() => {
            pending = result.current.refetch()
        })
        await waitFor(() => expect(calls).toBe(2))
        expect(result.current.startedSeq).toBe(first)

        await act(async () => {
            release()
            await pending
        })
        expect(result.current.state).toMatchObject({ kind: "ready", data: { n: 2 } })
        expect(result.current.startedSeq).toBeGreaterThan(first!)
    })

    it("is taken at the start of a read, not when it answers", async () => {
        const server = installMockServer()
        const releases: (() => void)[] = []
        server.on(
            "GET",
            "/a",
            () =>
                new Promise((resolve) => {
                    releases.push(() => resolve({ body: {} }))
                }),
        )
        server.on("GET", "/b", { body: {} })
        const slow = renderHook(() => useAuthoringResource("/a"), { wrapper: Wrapper })
        await waitFor(() => expect(releases).toHaveLength(1))
        const fast = renderHook(() => useAuthoringResource("/b"), { wrapper: Wrapper })
        await waitFor(() => expect(fast.result.current.state.kind).toBe("ready"))
        await act(async () => {
            releases[0]!()
        })
        await waitFor(() => expect(slow.result.current.state.kind).toBe("ready"))

        // /a answered last but started first.
        expect(slow.result.current.startedSeq).toBeLessThan(fast.result.current.startedSeq!)
    })
})

// `startedOwner` is the user and browser session the data on screen STARTED under, so a settled result is
// never read as a later owner's.
describe("useAuthoringResource startedOwner", () => {
    it("is null while loading, names the owner at start, and keeps naming it after the owner changes", async () => {
        const server = installMockServer()
        server.on("GET", "/a", { body: {} })
        const reload = vi.fn()
        const refresh = vi.fn()
        let browserSession = "session-1"
        function OwnerWrapper({ children }: PropsWithChildren) {
            return (
                <SessionContext.Provider
                    value={{
                        state: {
                            status: "authenticated",
                            bootstrap: { ...sessionBootstrapFixture, browser_session_id: browserSession },
                        },
                        reload,
                        refresh,
                    }}
                >
                    {children}
                </SessionContext.Provider>
            )
        }
        const { result, rerender } = renderHook(() => useAuthoringResource("/a"), { wrapper: OwnerWrapper })
        expect(result.current.startedOwner).toBeNull()
        await waitFor(() => expect(result.current.state.kind).toBe("ready"))
        const first = result.current.startedOwner
        expect(first).toContain("session-1")

        // The same data stays on screen under the owner that started it; a refetch starts under the new one.
        browserSession = "session-2"
        rerender()
        expect(result.current.startedOwner).toBe(first)
        await act(async () => {
            await result.current.refetch()
        })
        expect(result.current.startedOwner).toContain("session-2")
    })
})
