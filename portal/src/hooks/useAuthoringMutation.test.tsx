import { act, renderHook, waitFor } from "@testing-library/react"
import type { PropsWithChildren } from "react"
import { describe, expect, it, vi } from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { ApiRequestError } from "../api/http"
import type { MutationRequestContext } from "./useAuthoringMutation"
import { useAuthoringMutation } from "./useAuthoringMutation"

function wrapperWith(reload = vi.fn()) {
    return function Wrapper({ children }: PropsWithChildren) {
        return (
            <SessionContext.Provider
                value={{
                    state: {
                        status: "authenticated",
                        bootstrap: { ...sessionBootstrapFixture, csrf_token: "csrf-1" },
                    },
                    reload,
                    refresh: vi.fn(),
                }}
            >
                {children}
            </SessionContext.Provider>
        )
    }
}

interface Body {
    name: string
}

function deferred<T>() {
    let resolve!: (value: T) => void
    let reject!: (reason: unknown) => void
    const promise = new Promise<T>((res, rej) => {
        resolve = res
        reject = rej
    })
    return { promise, resolve, reject }
}

describe("useAuthoringMutation", () => {
    it("sends the session CSRF token and a fresh idempotency key, then succeeds after onSuccess", async () => {
        const request = vi.fn<(b: Body, c: MutationRequestContext) => Promise<string>>()
        request.mockResolvedValue("done")
        const order: string[] = []
        const onSuccess = vi.fn(async () => {
            order.push("onSuccess")
        })

        const { result } = renderHook(
            () => useAuthoringMutation<Body, string>({ scopeKey: "a", request, onSuccess }),
            { wrapper: wrapperWith() },
        )

        act(() => result.current.submit({ name: "x" }))
        expect(result.current.status.kind).toBe("pending")
        await waitFor(() => expect(result.current.status.kind).toBe("success"))

        expect(request.mock.calls[0]![1]).toMatchObject({ csrfToken: "csrf-1" })
        expect(request.mock.calls[0]![1].idempotencyKey).toMatch(/[0-9a-f-]{36}/)
        expect(onSuccess).toHaveBeenCalledWith("done")
        expect(order).toEqual(["onSuccess"])
    })

    it("is not a success until the authoritative onSuccess refetch has finished", async () => {
        const gate = deferred<void>()
        const { result } = renderHook(
            () =>
                useAuthoringMutation<Body, string>({
                    scopeKey: "a",
                    request: vi.fn().mockResolvedValue("done"),
                    onSuccess: () => gate.promise,
                }),
            { wrapper: wrapperWith() },
        )
        act(() => result.current.submit({ name: "x" }))
        await waitFor(() => expect(result.current.status.kind).toBe("pending"))
        await Promise.resolve()
        expect(result.current.status.kind).toBe("pending")
        await act(async () => gate.resolve())
        await waitFor(() => expect(result.current.status.kind).toBe("success"))
    })

    it("reuses the idempotency key for an unchanged body (retry) and rotates it when the body changes", async () => {
        const keys: string[] = []
        const request = vi.fn(async (_b: Body, c: MutationRequestContext) => {
            keys.push(c.idempotencyKey)
            throw new ApiRequestError(500, "internal_error", null)
        })
        const { result } = renderHook(
            () => useAuthoringMutation<Body, string>({ scopeKey: "a", request }),
            { wrapper: wrapperWith() },
        )

        act(() => result.current.submit({ name: "same" }))
        await waitFor(() => expect(result.current.status.kind).toBe("error"))
        act(() => result.current.retry())
        await waitFor(() => expect(request).toHaveBeenCalledTimes(2))
        await waitFor(() => expect(result.current.status.kind).toBe("error"))
        act(() => result.current.submit({ name: "changed" }))
        await waitFor(() => expect(request).toHaveBeenCalledTimes(3))

        expect(keys[0]).toBe(keys[1])
        expect(keys[2]).not.toBe(keys[0])
    })

    it("ignores a second submit while pending", async () => {
        const gate = deferred<string>()
        const request = vi.fn(() => gate.promise)
        const { result } = renderHook(
            () => useAuthoringMutation<Body, string>({ scopeKey: "a", request }),
            { wrapper: wrapperWith() },
        )
        act(() => result.current.submit({ name: "x" }))
        act(() => result.current.submit({ name: "x" }))
        expect(request).toHaveBeenCalledTimes(1)
        await act(async () => gate.resolve("ok"))
    })

    it.each([
        [403, null, "denied"],
        [404, null, "unavailable"],
        [409, "stale_write", "stale"],
        [409, "conflict", "conflict"],
        [422, "invalid_request", "invalid"],
        [500, null, "server"],
        [0, "network_error", "network"],
    ])("classifies %i %s as %s and keeps the error", async (status, code, kind) => {
        const { result } = renderHook(
            () =>
                useAuthoringMutation<Body, string>({
                    scopeKey: "a",
                    request: vi.fn().mockRejectedValue(new ApiRequestError(status, code, "c1")),
                }),
            { wrapper: wrapperWith() },
        )
        act(() => result.current.submit({ name: "x" }))
        await waitFor(() => expect(result.current.status.kind).toBe("error"))
        expect(result.current.status).toMatchObject({ error: { kind, code } })
    })

    it("reloads the session on 401 instead of showing an error", async () => {
        const reload = vi.fn()
        const { result } = renderHook(
            () =>
                useAuthoringMutation<Body, string>({
                    scopeKey: "a",
                    request: vi.fn().mockRejectedValue(new ApiRequestError(401, null, null)),
                }),
            { wrapper: wrapperWith(reload) },
        )
        act(() => result.current.submit({ name: "x" }))
        await waitFor(() => expect(reload).toHaveBeenCalledTimes(1))
        expect(result.current.status.kind).toBe("idle")
    })

    it("aborts on unmount and ignores the late response", async () => {
        const gate = deferred<string>()
        let signal: AbortSignal | undefined
        const onSuccess = vi.fn()
        const { result, unmount } = renderHook(
            () =>
                useAuthoringMutation<Body, string>({
                    scopeKey: "a",
                    request: (_b, c) => {
                        signal = c.signal
                        return gate.promise
                    },
                    onSuccess,
                }),
            { wrapper: wrapperWith() },
        )
        act(() => result.current.submit({ name: "x" }))
        unmount()
        expect(signal?.aborted).toBe(true)
        await act(async () => gate.resolve("late"))
        expect(onSuccess).not.toHaveBeenCalled()
    })

    it("aborts and resets when the scope changes, so a result never shows under another record", async () => {
        const gate = deferred<string>()
        let signal: AbortSignal | undefined
        const { result, rerender } = renderHook(
            ({ scope }: { scope: string }) =>
                useAuthoringMutation<Body, string>({
                    scopeKey: scope,
                    request: (_b, c) => {
                        signal = c.signal
                        return gate.promise
                    },
                }),
            { wrapper: wrapperWith(), initialProps: { scope: "world-1" } },
        )
        act(() => result.current.submit({ name: "x" }))
        rerender({ scope: "world-2" })
        expect(signal?.aborted).toBe(true)
        expect(result.current.status.kind).toBe("idle")
        await act(async () => gate.resolve("late"))
        expect(result.current.status.kind).toBe("idle")
    })
})
