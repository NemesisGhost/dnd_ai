import { act, renderHook, waitFor } from "@testing-library/react"
import type { PropsWithChildren } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { installMockServer } from "../test/authoringHarness"
import { useAuthoringResource } from "./useAuthoringResource"

function wrapperWith(reload = vi.fn()) {
    return function Wrapper({ children }: PropsWithChildren) {
        return (
            <SessionContext.Provider
                value={{
                    state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
                    reload,
                    refresh: vi.fn(),
                }}
            >
                {children}
            </SessionContext.Provider>
        )
    }
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("useAuthoringResource", () => {
    it("loads, then is ready with the data", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/1", { body: { name: "One" } })
        const { result } = renderHook(() => useAuthoringResource<{ name: string }>("/worlds/1"), {
            wrapper: wrapperWith(),
        })
        expect(result.current.state.kind).toBe("loading")
        await waitFor(() => expect(result.current.state.kind).toBe("ready"))
        expect(result.current.state).toMatchObject({ data: { name: "One" }, refreshing: false })
    })

    it.each([
        [404, "unavailable"],
        [403, "denied"],
        [500, "error"],
    ])("maps %i to %s", async (status, kind) => {
        const server = installMockServer()
        server.on("GET", "/worlds/1", { status })
        const { result } = renderHook(() => useAuthoringResource("/worlds/1"), {
            wrapper: wrapperWith(),
        })
        await waitFor(() => expect(result.current.state.kind).toBe(kind))
    })

    it("reloads the session on a 401", async () => {
        const reload = vi.fn()
        const server = installMockServer()
        server.on("GET", "/worlds/1", { status: 401 })
        renderHook(() => useAuthoringResource("/worlds/1"), { wrapper: wrapperWith(reload) })
        await waitFor(() => expect(reload).toHaveBeenCalledTimes(1))
    })

    it("never shows a record loaded for one URL under another while the next one loads", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/1", { body: { name: "One" } })
        let release!: () => void
        server.on("GET", "/worlds/2", async () => {
            await new Promise<void>((resolve) => {
                release = resolve
            })
            return { body: { name: "Two" } }
        })
        const { result, rerender } = renderHook(
            ({ path }: { path: string }) => useAuthoringResource<{ name: string }>(path),
            { wrapper: wrapperWith(), initialProps: { path: "/worlds/1" } },
        )
        await waitFor(() => expect(result.current.state.kind).toBe("ready"))

        rerender({ path: "/worlds/2" })
        expect(result.current.state.kind).toBe("loading")
        await waitFor(() => expect(release).toBeDefined())
        await act(async () => release())
        await waitFor(() => expect(result.current.state).toMatchObject({ data: { name: "Two" } }))
    })

    it("refetch keeps the current data marked refreshing, then applies the new data", async () => {
        const server = installMockServer()
        let version = 1
        server.on("GET", "/worlds/1", async () => ({ body: { version: version++ } }))
        const { result } = renderHook(() => useAuthoringResource<{ version: number }>("/worlds/1"), {
            wrapper: wrapperWith(),
        })
        await waitFor(() => expect(result.current.state.kind).toBe("ready"))

        let pending!: Promise<"ok" | "failed" | "superseded">
        act(() => {
            pending = result.current.refetch()
        })
        expect(result.current.state).toMatchObject({ kind: "ready", data: { version: 1 }, refreshing: true })
        await act(async () => pending)
        expect(result.current.state).toMatchObject({ data: { version: 2 }, refreshing: false })
    })

    describe("refetch outcome", () => {
        it("says ok when the record was read again and failed when it was not, without rejecting", async () => {
            const server = installMockServer()
            let status = 200
            server.on("GET", "/worlds/1", () => ({ status, body: { name: "One" } }))
            const { result } = renderHook(() => useAuthoringResource<{ name: string }>("/worlds/1"), {
                wrapper: wrapperWith(),
            })
            await waitFor(() => expect(result.current.state.kind).toBe("ready"))
            let outcome: string | undefined
            await act(async () => {
                outcome = await result.current.refetch()
            })
            expect(outcome).toBe("ok")
            status = 500
            await act(async () => {
                outcome = await result.current.refetch()
            })
            expect(outcome).toBe("failed")
            expect(result.current.state.kind).toBe("error")
            expect(result.current.refreshOk.current).toBe(false)
            status = 403
            await act(async () => {
                outcome = await result.current.refetch()
            })
            expect(outcome).toBe("failed")
            expect(result.current.state.kind).toBe("denied")
        })

        it("says superseded when a newer read replaced it", async () => {
            const server = installMockServer()
            server.on("GET", "/worlds/1", { body: { name: "One" } })
            const { result } = renderHook(() => useAuthoringResource<{ name: string }>("/worlds/1"), {
                wrapper: wrapperWith(),
            })
            await waitFor(() => expect(result.current.state.kind).toBe("ready"))
            const outcomes: string[] = []
            await act(async () => {
                const first = result.current.refetch().then((o) => outcomes.push(o))
                const second = result.current.refetch().then((o) => outcomes.push(o))
                await Promise.all([first, second])
            })
            expect(outcomes.sort()).toEqual(["ok", "superseded"])
        })

        it("ignores a late answer for the previous record after the path changes", async () => {
            const server = installMockServer()
            server.on("GET", "/worlds/1", { body: { name: "One" } })
            server.on("GET", "/worlds/2", { status: 500 })
            const { result, rerender } = renderHook(
                ({ path }: { path: string }) => useAuthoringResource<{ name: string }>(path),
                { wrapper: wrapperWith(), initialProps: { path: "/worlds/1" } },
            )
            await waitFor(() => expect(result.current.state.kind).toBe("ready"))
            rerender({ path: "/worlds/2" })
            expect(result.current.state.kind).toBe("loading")
            await waitFor(() => expect(result.current.state.kind).toBe("error"))
        })
    })
})
