import { act, renderHook, waitFor } from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { RevokeResourceGrantRequestError } from "../api/revokeResourceGrant"
import { useRevokeResourceGrant } from "./useRevokeResourceGrant"

const { revokeResourceGrantMock, reloadMock, sessionStateRef } = vi.hoisted(
    () => ({
        revokeResourceGrantMock: vi.fn(),
        reloadMock: vi.fn(),
        sessionStateRef: {
            current: {
                status: "authenticated" as const,
                bootstrap: {
                    csrf_token: "fixture-csrf-token",
                },
            },
        },
    }),
)

vi.mock("../api/revokeResourceGrant", async (importOriginal) => {
    const actual =
        await importOriginal<typeof import("../api/revokeResourceGrant")>()

    return {
        ...actual,
        revokeResourceGrant: revokeResourceGrantMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        state: sessionStateRef.current,
        reload: reloadMock,
    }),
}))

beforeEach(() => {
    revokeResourceGrantMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useRevokeResourceGrant", () => {
    it("starts idle", () => {
        const { result } = renderHook(() =>
            useRevokeResourceGrant("campaign-a", vi.fn()),
        )

        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("goes pending on submit, then success, calling onSuccess and reloading the session", async () => {
        const onSuccess = vi.fn()
        let resolveRequest!: (value: { resource_grant_id: string }) => void
        revokeResourceGrantMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result } = renderHook(() =>
            useRevokeResourceGrant("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("grant-a")
        })

        expect(result.current.status).toEqual({ kind: "pending" })
        expect(revokeResourceGrantMock).toHaveBeenCalledWith(
            "campaign-a",
            "grant-a",
            "fixture-csrf-token",
            expect.any(String),
            expect.any(AbortSignal),
        )
        expect(onSuccess).not.toHaveBeenCalled()

        await act(async () => {
            resolveRequest({ resource_grant_id: "grant-a" })
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)
        expect(reloadMock).toHaveBeenCalledTimes(1)
    })

    it("ignores a second submit while one is already pending", () => {
        revokeResourceGrantMock.mockReturnValue(new Promise(() => {}))

        const { result } = renderHook(() =>
            useRevokeResourceGrant("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("grant-a")
        })
        act(() => {
            result.current.submit("grant-a")
        })

        expect(revokeResourceGrantMock).toHaveBeenCalledTimes(1)
    })

    it("reloads the session and returns to idle on an unauthorized response", async () => {
        revokeResourceGrantMock.mockRejectedValue(
            new RevokeResourceGrantRequestError(401),
        )

        const { result } = renderHook(() =>
            useRevokeResourceGrant("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("grant-a")
        })

        await waitFor(() => {
            expect(reloadMock).toHaveBeenCalledTimes(1)
        })
        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it.each([403, 404])(
        "reports a denied status for a non-disclosing %s response",
        async (status) => {
            revokeResourceGrantMock.mockRejectedValue(
                new RevokeResourceGrantRequestError(status),
            )

            const { result } = renderHook(() =>
                useRevokeResourceGrant("campaign-a", vi.fn()),
            )

            act(() => {
                result.current.submit("grant-a")
            })

            await waitFor(() => {
                expect(result.current.status).toEqual({ kind: "denied" })
            })
        },
    )

    it("reports a conflict status for a 409 response", async () => {
        revokeResourceGrantMock.mockRejectedValue(
            new RevokeResourceGrantRequestError(409),
        )

        const { result } = renderHook(() =>
            useRevokeResourceGrant("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("grant-a")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "conflict" })
        })
    })

    it("reports a recoverable error for any other failure and allows a retry, reusing the same idempotency key", async () => {
        revokeResourceGrantMock
            .mockRejectedValueOnce(new Error("network down"))
            .mockResolvedValueOnce({ resource_grant_id: "grant-a" })

        const onSuccess = vi.fn()
        const { result } = renderHook(() =>
            useRevokeResourceGrant("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("grant-a")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })

        act(() => {
            result.current.submit("grant-a")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)

        const firstKey = revokeResourceGrantMock.mock.calls[0]?.[3]
        const secondKey = revokeResourceGrantMock.mock.calls[1]?.[3]
        expect(typeof firstKey).toBe("string")
        expect(secondKey).toEqual(firstKey)
    })

    it("resets to idle", async () => {
        revokeResourceGrantMock.mockRejectedValue(
            new RevokeResourceGrantRequestError(409),
        )

        const { result } = renderHook(() =>
            useRevokeResourceGrant("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("grant-a")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "conflict" })
        })

        act(() => {
            result.current.reset()
        })

        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("aborts the in-flight request when the hook unmounts", () => {
        revokeResourceGrantMock.mockReturnValue(new Promise(() => {}))

        const { result, unmount } = renderHook(() =>
            useRevokeResourceGrant("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("grant-a")
        })

        const signal = revokeResourceGrantMock.mock.calls[0]?.[4] as AbortSignal
        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})
