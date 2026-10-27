import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react"
import { useEffect } from "react"
import type { PropsWithChildren } from "react"
import { describe, expect, it, vi } from "vitest"
import { AnnouncerContext } from "../components/authoring/announcer"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { useAuthoringMutation } from "./useAuthoringMutation"
import type { AuthoringMutationStatus, MutationRequestContext, RefreshOutcome } from "./useAuthoringMutation"
import { useConfirmedRefresh, useUnreadWrite } from "./useConfirmedRefresh"

// Recovery of one write must never touch another: the recovered write's cleanup is tied to that write's
// own status, so a write that has started (or finished) at the boundary is left exactly as it is.

function Session({ children }: PropsWithChildren) {
    return (
        <SessionContext.Provider
            value={{
                state: {
                    status: "authenticated",
                    bootstrap: { ...sessionBootstrapFixture, csrf_token: "csrf-1" },
                },
                reload: vi.fn(),
                refresh: vi.fn(),
            }}
        >
            {children}
        </SessionContext.Provider>
    )
}

function deferred<T>() {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((res) => {
        resolve = res
    })
    return { promise, resolve }
}

describe("recovery is specific to the write it recovered", () => {
    it("does not reset or repeat a write that starts at the moment the page's read recovers the previous one", async () => {
        const announce = vi.fn()
        const gates = [deferred<string>(), deferred<string>()]
        let sent = 0
        const request = vi.fn<(body: string, ctx: MutationRequestContext) => Promise<string>>(() => gates[sent++]!.promise)
        // The page's current submit, kept where the test can call it (refreshed after every commit).
        const handle: { submit: (body: string) => unknown } = { submit: () => undefined }
        const submit = (body: string) => handle.submit(body)

        function Page({ pageStale }: { pageStale: boolean }) {
            const mutation = useAuthoringMutation<string, string>({
                scopeKey: "boundary",
                request,
                // Every write is confirmed, and its read-back never completes.
                onSuccess: async (): Promise<RefreshOutcome> => "failed",
                ownsRefreshNotice: true,
            })
            useEffect(() => {
                handle.submit = mutation.submit
            })
            const refreshed = useConfirmedRefresh({
                status: mutation.status,
                reset: mutation.reset,
                what: "party list",
                message: "Party archived",
                read: async () => "ok",
                pageStale,
            })
            return (
                <div>
                    {refreshed.notice}
                    <span data-testid="status">{mutation.status.kind}</span>
                    <span data-testid="held">{String(refreshed.held)}</span>
                </div>
            )
        }
        const wrap = (stale: boolean) => (
            <Session>
                <AnnouncerContext.Provider value={{ announce }}>
                    <Page pageStale={stale} />
                </AnnouncerContext.Provider>
            </Session>
        )

        // First write: confirmed, its read-back fails, the page's own read is then what is stale.
        const view = render(wrap(false))
        act(() => submit("first"))
        await act(async () => gates[0]!.resolve("receipt-1"))
        await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("confirmed"))
        view.rerender(wrap(true))
        expect(screen.getByTestId("held")).toHaveTextContent("true")

        // The page's read recovers the first write and, in the same batch, before any passive effect of
        // that recovery has run, the person starts a second write.
        act(() => {
            view.rerender(wrap(false))
            submit("second")
        })
        expect(request).toHaveBeenCalledTimes(2)
        expect(screen.getByTestId("status")).toHaveTextContent("pending")
        // Another press while it is pending is ignored: the second write is sent exactly once.
        act(() => submit("second"))
        expect(request).toHaveBeenCalledTimes(2)
        // Recovering the first write did not clear the second's pending state, and nothing was announced
        // for a write whose recovery was never shown.
        expect(announce).not.toHaveBeenCalled()

        // The second write confirms with its own failed read: it is reported afresh, and held.
        await act(async () => gates[1]!.resolve("receipt-2"))
        await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("confirmed"))
        view.rerender(wrap(true))
        expect(screen.getByTestId("held")).toHaveTextContent("true")
        expect(screen.getByText(/Party archived\. The latest party list could not be loaded/)).toBeInTheDocument()
        expect(request).toHaveBeenCalledTimes(2)
        expect(request.mock.calls[0]![1].idempotencyKey).not.toBe(request.mock.calls[1]![1].idempotencyKey)
    })

    it("ends an episode only while it is still the current one (mutation status)", async () => {
        const gate = deferred<string>()
        const request = vi.fn<(body: string, ctx: MutationRequestContext) => Promise<string>>(() => gate.promise)
        const { result } = renderHook(
            () => useAuthoringMutation<string, string>({ scopeKey: "s", request, onSuccess: async (): Promise<RefreshOutcome> => "failed" }),
            { wrapper: Session },
        )
        act(() => result.current.submit("first"))
        await act(async () => gate.resolve("r"))
        await waitFor(() => expect(result.current.status.kind).toBe("confirmed"))
        const earlier: AuthoringMutationStatus = result.current.status

        // Resetting for an episode that is not the current status leaves the current one alone ...
        act(() => result.current.reset({ kind: "confirmed", refresh: "failed" }))
        expect(result.current.status).toBe(earlier)
        // ... and resetting the current one (or with no argument) returns to idle.
        act(() => result.current.reset(earlier))
        expect(result.current.status.kind).toBe("idle")
    })

    it("ends an unread write only while it is still the one that was marked", () => {
        const { result } = renderHook(() => useUnreadWrite<string>())
        act(() => result.current.mark("first"))
        const first = result.current.status
        act(() => result.current.mark("second"))
        // The newer write is not the one being ended, whatever its message says.
        act(() => result.current.end(first))
        expect(result.current.value).toBe("second")
        expect(result.current.status.kind).toBe("confirmed")
        act(() => result.current.end(result.current.status))
        expect(result.current.value).toBeNull()
        expect(result.current.status.kind).toBe("idle")
    })

    it("keeps one announcement per recovered write when Load latest answers after another write was marked", async () => {
        const announce = vi.fn()
        const gate = deferred<RefreshOutcome>()
        function Caller() {
            const unread = useUnreadWrite<string>()
            const refreshed = useConfirmedRefresh({
                status: unread.status,
                reset: unread.end,
                what: "world",
                message: unread.value,
                read: () => gate.promise,
            })
            return (
                <div>
                    {refreshed.notice}
                    <span data-testid="held">{String(refreshed.held)}</span>
                    <button type="button" onClick={() => unread.mark("World restored")}>
                        mark
                    </button>
                </div>
            )
        }
        render(
            <AnnouncerContext.Provider value={{ announce }}>
                <Caller />
            </AnnouncerContext.Provider>,
        )
        fireEvent.click(screen.getByRole("button", { name: "mark" }))
        fireEvent.click(screen.getByRole("button", { name: "Load latest" }))
        // While that read is in flight another write is marked (its own episode) ...
        fireEvent.click(screen.getByRole("button", { name: "mark" }))
        // ... then the first read answers: it recovers the first write and leaves the newer one in place.
        await act(async () => gate.resolve("ok"))
        expect(announce).toHaveBeenCalledTimes(1)
        expect(screen.getByTestId("held")).toHaveTextContent("true")
        expect(screen.getByText(/World restored\. The latest world could not be loaded/)).toBeInTheDocument()
    })
})
