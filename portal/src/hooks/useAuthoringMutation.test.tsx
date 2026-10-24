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
        expect(onSuccess).toHaveBeenCalledWith("done", { name: "x" })
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
        // Without holdUnresolved an edited body is simply a new request with a new key.
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

    describe("confirmed writes and uncertain writes", () => {
        const network = () => new ApiRequestError(0, null, null)

        it("retries an unconfirmed write with the same body, the same key and the request as first sent", async () => {
            const sent: { body: Body; key: string; version: number }[] = []
            let version = 3
            const request = vi
                .fn<(b: Body, c: MutationRequestContext) => Promise<string>>()
                .mockImplementation((body, ctx) => {
                    sent.push({ body, key: ctx.idempotencyKey, version })
                    return sent.length === 1 ? Promise.reject(network()) : Promise.resolve("done")
                })
            // The component re-renders with a newer row version between the failure and the retry.
            const { result, rerender } = renderHook(
                ({ v }: { v: number }) =>
                    useAuthoringMutation<Body, string>({
                        scopeKey: "a",
                        request: (b, c) => {
                            version = v
                            return request(b, c)
                        },
                    }),
                { wrapper: wrapperWith(), initialProps: { v: 3 } },
            )
            act(() => result.current.submit({ name: "x" }))
            await waitFor(() => expect(result.current.status).toMatchObject({ kind: "error", error: { kind: "network" } }))
            rerender({ v: 4 })
            act(() => result.current.retry())
            await waitFor(() => expect(result.current.status.kind).toBe("success"))
            expect(sent).toHaveLength(2)
            expect(sent[1]!.key).toBe(sent[0]!.key)
            expect(sent[1]!.body).toEqual(sent[0]!.body)
            // The retry went through the request closure captured at the first send.
            expect(sent[1]!.version).toBe(3)
        })

        it("resolves a lost-answer write before edited input can become a second write, then gives the edit a new key", async () => {
            const sent: { body: Body; key: string }[] = []
            let lose = true
            const request = vi.fn((b: Body, c: MutationRequestContext) => {
                sent.push({ body: b, key: c.idempotencyKey })
                if (lose && b.name === "x") {
                    lose = false
                    // The server committed it; the answer never arrived.
                    return Promise.reject(network())
                }
                return Promise.resolve("done")
            })
            const confirmed: Body[] = []
            const { result } = renderHook(
                () =>
                    useAuthoringMutation<Body, string>({
                        scopeKey: "a",
                        request,
                        holdUnresolved: true,
                        onSuccess: (_r, body) => {
                            confirmed.push(body)
                        },
                    }),
                { wrapper: wrapperWith() },
            )
            act(() => result.current.submit({ name: "x" }))
            await waitFor(() => expect(result.current.status.kind).toBe("error"))
            let outcome: string | undefined
            act(() => {
                outcome = result.current.submit({ name: "edited" })
            })
            expect(outcome).toBe("resolving-earlier")
            await waitFor(() => expect(result.current.status.kind).toBe("success"))
            // Only the original body was sent again, under its own key; the edit was not sent.
            expect(sent.map((s) => s.body.name)).toEqual(["x", "x"])
            expect(sent[1]!.key).toBe(sent[0]!.key)
            expect(confirmed).toEqual([{ name: "x" }])
            // Now that it is final, the edit is an ordinary new request with a new key.
            act(() => result.current.submit({ name: "edited" }))
            await waitFor(() => expect(sent).toHaveLength(3))
            expect(sent[2]!.key).not.toBe(sent[0]!.key)
        })

        it("re-sends the unresolved attempt exactly for an unchanged ordinary submission", async () => {
            const sent: { body: Body; key: string }[] = []
            const request = vi.fn((b: Body, c: MutationRequestContext) => {
                sent.push({ body: b, key: c.idempotencyKey })
                return sent.length === 1 ? Promise.reject(network()) : Promise.resolve("done")
            })
            const { result } = renderHook(() => useAuthoringMutation<Body, string>({ scopeKey: "a", request }), {
                wrapper: wrapperWith(),
            })
            act(() => result.current.submit({ name: "x" }))
            await waitFor(() => expect(result.current.status.kind).toBe("error"))
            act(() => result.current.submit({ name: "x" }))
            await waitFor(() => expect(result.current.status.kind).toBe("success"))
            expect(sent[1]).toEqual(sent[0])
        })

        it("lets a definitive refusal release the unresolved attempt", async () => {
            const request = vi
                .fn<(b: Body, c: MutationRequestContext) => Promise<string>>()
                .mockRejectedValueOnce(network())
                .mockRejectedValueOnce(new ApiRequestError(400, "x", null))
                .mockResolvedValue("done")
            const { result } = renderHook(
                () => useAuthoringMutation<Body, string>({ scopeKey: "a", request, holdUnresolved: true }),
                { wrapper: wrapperWith() },
            )
            act(() => result.current.submit({ name: "x" }))
            await waitFor(() => expect(result.current.status.kind).toBe("error"))
            act(() => result.current.retry())
            await waitFor(() => expect(request).toHaveBeenCalledTimes(2))
            await waitFor(() => expect(result.current.status).toMatchObject({ error: { kind: "invalid" } }))
            act(() => result.current.submit({ name: "edited" }))
            await waitFor(() => expect(request).toHaveBeenCalledTimes(3))
            expect(request.mock.calls[2]![0]).toEqual({ name: "edited" })
        })

        it("reports a confirmed write whose refresh returned failed as confirmed, never as an error, and cannot be retried", async () => {
            const request = vi.fn().mockResolvedValue({ row_version: 5 })
            const { result } = renderHook(
                () =>
                    useAuthoringMutation<Body, { row_version: number }>({
                        scopeKey: "a",
                        request,
                        onSuccess: () => "failed",
                    }),
                { wrapper: wrapperWith() },
            )
            act(() => result.current.submit({ name: "x" }))
            await waitFor(() => expect(result.current.status).toEqual({ kind: "confirmed", refresh: "failed" }))
            expect(result.current.receipt).toEqual({ row_version: 5 })
            // The key and body are spent: retry does nothing, so the write cannot be repeated.
            act(() => result.current.retry())
            expect(request).toHaveBeenCalledTimes(1)
        })

        it("treats a throwing onSuccess as a failed refresh of a confirmed write, not a failed write", async () => {
            const request = vi.fn().mockResolvedValue("done")
            const { result } = renderHook(
                () =>
                    useAuthoringMutation<Body, string>({
                        scopeKey: "a",
                        request,
                        onSuccess: () => {
                            throw new Error("secret detail")
                        },
                    }),
                { wrapper: wrapperWith() },
            )
            act(() => result.current.submit({ name: "x" }))
            await waitFor(() => expect(result.current.status.kind).toBe("confirmed"))
            expect(JSON.stringify(result.current.status)).not.toContain("secret")
            act(() => result.current.retry())
            expect(request).toHaveBeenCalledTimes(1)
        })

        it("keeps a write whose refresh was superseded unresolved, and a plain success when nothing was reported", async () => {
            const { result } = renderHook(
                () =>
                    useAuthoringMutation<Body, string>({
                        scopeKey: "a",
                        request: vi.fn().mockResolvedValue("done"),
                        onSuccess: () => "superseded",
                    }),
                { wrapper: wrapperWith() },
            )
            act(() => result.current.submit({ name: "x" }))
            await waitFor(() => expect(result.current.status.kind).toBe("confirmed"))
        })

        it("keeps a stale-version refusal as an error the caller resolves, with no receipt", async () => {
            const stale = new ApiRequestError(409, "stale_write", "corr")
            const { result } = renderHook(
                () => useAuthoringMutation<Body, string>({ scopeKey: "a", request: vi.fn().mockRejectedValue(stale) }),
                { wrapper: wrapperWith() },
            )
            act(() => result.current.submit({ name: "x" }))
            await waitFor(() => expect(result.current.status).toMatchObject({ kind: "error", error: { kind: "stale" } }))
            expect(result.current.receipt).toBeNull()
        })

        it("drops a confirmed receipt when the scope changes", async () => {
            const { result, rerender } = renderHook(
                ({ scope }: { scope: string }) =>
                    useAuthoringMutation<Body, string>({
                        scopeKey: scope,
                        request: vi.fn().mockResolvedValue("done"),
                    }),
                { wrapper: wrapperWith(), initialProps: { scope: "a" } },
            )
            act(() => result.current.submit({ name: "x" }))
            await waitFor(() => expect(result.current.receipt).toBe("done"))
            rerender({ scope: "b" })
            expect(result.current.receipt).toBeNull()
            expect(result.current.status.kind).toBe("idle")
        })

        it("aborts a pending request on unmount and ignores its late failure", async () => {
            const gate = deferred<string>()
            const { result, unmount } = renderHook(
                () => useAuthoringMutation<Body, string>({ scopeKey: "a", request: () => gate.promise }),
                { wrapper: wrapperWith() },
            )
            act(() => result.current.submit({ name: "x" }))
            expect(result.current.status.kind).toBe("pending")
            unmount()
            await act(async () => gate.reject(network()))
        })
    })
})
