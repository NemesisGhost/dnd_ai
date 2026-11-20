import { renderHook, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { AccessWriteScopeContext, useAccessWriteCompletion } from "./useAccessWriteCompletion"

function setup(refresh: (signal?: AbortSignal) => Promise<boolean>, affectsCaller?: boolean) {
    const reload = vi.fn()
    const refreshMock = vi.fn(refresh)
    const wrapper = ({ children }: { children: ReactNode }) => (
        <SessionContext.Provider
            value={{
                state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
                reload,
                refresh: refreshMock,
            }}
        >
            {affectsCaller === undefined ? (
                children
            ) : (
                <AccessWriteScopeContext.Provider value={{ affectsCaller }}>{children}</AccessWriteScopeContext.Provider>
            )}
        </SessionContext.Provider>
    )
    const { result } = renderHook(() => useAccessWriteCompletion(), { wrapper })
    return { complete: result.current, reload, refresh: refreshMock }
}

describe("useAccessWriteCompletion", () => {
    it("reloads the session, and reads nothing in place, when there is no scope (the conservative default)", () => {
        const { complete, reload, refresh } = setup(async () => true)
        complete()
        expect(reload).toHaveBeenCalledTimes(1)
        expect(refresh).not.toHaveBeenCalled()
    })

    it("reloads for a write that may affect the caller", () => {
        const { complete, reload, refresh } = setup(async () => true, true)
        complete()
        expect(reload).toHaveBeenCalledTimes(1)
        expect(refresh).not.toHaveBeenCalled()
    })

    it("re-reads in place with a signal of its own, and does not reload when the fresh state was applied", async () => {
        const { complete, reload, refresh } = setup(async () => true, false)
        complete()
        await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1))
        // A read with no signal would join one already in flight, which may have started before this write.
        expect(refresh.mock.calls[0]![0]).toBeInstanceOf(AbortSignal)
        expect(refresh.mock.calls[0]![0]!.aborted).toBe(false)
        await Promise.resolve()
        expect(reload).not.toHaveBeenCalled()
    })

    it.each([
        ["was not applied (resolved false)", async () => false],
        ["gave no answer (resolved undefined)", async () => undefined as unknown as boolean],
        ["failed (rejected)", async () => Promise.reject(new Error("read failed"))],
    ])("falls back to a full reload when the in-place read %s", async (_label, refresh) => {
        const { complete, reload } = setup(refresh, false)
        complete()
        await waitFor(() => expect(reload).toHaveBeenCalledTimes(1))
    })

    it("falls back to a full reload when starting the read throws", () => {
        const { complete, reload } = setup(() => {
            throw new Error("boom")
        }, false)
        complete()
        expect(reload).toHaveBeenCalledTimes(1)
    })
})
