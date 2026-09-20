import { act, renderHook, waitFor } from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { AddResourceGrantRequestError } from "../api/addResourceGrant"
import { useAddResourceGrant } from "./useAddResourceGrant"

const { addResourceGrantMock, reloadMock, sessionStateRef } = vi.hoisted(
    () => ({
        addResourceGrantMock: vi.fn(),
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

vi.mock("../api/addResourceGrant", async (importOriginal) => {
    const actual =
        await importOriginal<typeof import("../api/addResourceGrant")>()

    return {
        ...actual,
        addResourceGrant: addResourceGrantMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        state: sessionStateRef.current,
        reload: reloadMock,
    }),
}))

beforeEach(() => {
    addResourceGrantMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useAddResourceGrant", () => {
    it("starts idle", () => {
        const { result } = renderHook(() =>
            useAddResourceGrant("campaign-a", vi.fn()),
        )

        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("goes pending on submit, then success, calling onSuccess and reloading the session", async () => {
        const onSuccess = vi.fn()
        let resolveRequest!: (value: { resource_grant_id: string }) => void
        addResourceGrantMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result } = renderHook(() =>
            useAddResourceGrant("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "character.view_full",
            )
        })

        expect(result.current.status).toEqual({ kind: "pending" })
        expect(addResourceGrantMock).toHaveBeenCalledWith(
            "campaign-a",
            "membership-a",
            "character-a",
            "character.view_full",
            "fixture-csrf-token",
            expect.any(String),
            expect.any(AbortSignal),
        )
        expect(onSuccess).not.toHaveBeenCalled()

        await act(async () => {
            resolveRequest({ resource_grant_id: "new-grant" })
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)
        expect(reloadMock).toHaveBeenCalledTimes(1)
    })

    it("ignores a second submit while one is already pending", () => {
        addResourceGrantMock.mockReturnValue(new Promise(() => {}))

        const { result } = renderHook(() =>
            useAddResourceGrant("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "character.view_full",
            )
        })
        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "character.view_summary",
            )
        })

        expect(addResourceGrantMock).toHaveBeenCalledTimes(1)
    })

    it("reloads the session and returns to idle on an unauthorized response", async () => {
        addResourceGrantMock.mockRejectedValue(
            new AddResourceGrantRequestError(401),
        )

        const { result } = renderHook(() =>
            useAddResourceGrant("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "character.view_full",
            )
        })

        await waitFor(() => {
            expect(reloadMock).toHaveBeenCalledTimes(1)
        })
        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it.each([403, 404])(
        "reports a denied status for a non-disclosing %s response",
        async (status) => {
            addResourceGrantMock.mockRejectedValue(
                new AddResourceGrantRequestError(status),
            )

            const { result } = renderHook(() =>
                useAddResourceGrant("campaign-a", vi.fn()),
            )

            act(() => {
                result.current.submit(
                    "membership-a",
                    "character-a",
                    "character.view_full",
                )
            })

            await waitFor(() => {
                expect(result.current.status).toEqual({ kind: "denied" })
            })
        },
    )

    it.each([400, 409])(
        "reports a conflict status for a %s response",
        async (status) => {
            addResourceGrantMock.mockRejectedValue(
                new AddResourceGrantRequestError(status),
            )

            const { result } = renderHook(() =>
                useAddResourceGrant("campaign-a", vi.fn()),
            )

            act(() => {
                result.current.submit(
                    "membership-a",
                    "character-a",
                    "character.view_full",
                )
            })

            await waitFor(() => {
                expect(result.current.status).toEqual({ kind: "conflict" })
            })
        },
    )

    it("reports a recoverable error for any other failure and allows a retry, reusing the same idempotency key", async () => {
        addResourceGrantMock
            .mockRejectedValueOnce(new Error("network down"))
            .mockResolvedValueOnce({ resource_grant_id: "new-grant" })

        const onSuccess = vi.fn()
        const { result } = renderHook(() =>
            useAddResourceGrant("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "character.view_full",
            )
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })

        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "character.view_full",
            )
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)

        const firstKey = addResourceGrantMock.mock.calls[0]?.[5]
        const secondKey = addResourceGrantMock.mock.calls[1]?.[5]
        expect(typeof firstKey).toBe("string")
        expect(secondKey).toEqual(firstKey)
    })

    it("generates a different key for a different character/capability selection", async () => {
        addResourceGrantMock
            .mockRejectedValueOnce(new Error("network down"))
            .mockResolvedValueOnce({ resource_grant_id: "new-grant" })

        const { result } = renderHook(() =>
            useAddResourceGrant("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "character.view_full",
            )
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })

        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "character.view_summary",
            )
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })

        const firstKey = addResourceGrantMock.mock.calls[0]?.[5]
        const secondKey = addResourceGrantMock.mock.calls[1]?.[5]
        expect(secondKey).not.toEqual(firstKey)
    })

    it("resets to idle", async () => {
        addResourceGrantMock.mockRejectedValue(
            new AddResourceGrantRequestError(409),
        )

        const { result } = renderHook(() =>
            useAddResourceGrant("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "character.view_full",
            )
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "conflict" })
        })

        act(() => {
            result.current.reset()
        })

        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("ignores a late response after the campaign changes, and aborts the in-flight request", async () => {
        const onSuccess = vi.fn()
        let resolveRequest!: (value: { resource_grant_id: string }) => void
        addResourceGrantMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result, rerender } = renderHook(
            ({ campaignId }) => useAddResourceGrant(campaignId, onSuccess),
            { initialProps: { campaignId: "campaign-a" } },
        )

        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "character.view_full",
            )
        })
        expect(result.current.status).toEqual({ kind: "pending" })

        const signal = addResourceGrantMock.mock.calls[0]?.[6] as AbortSignal

        rerender({ campaignId: "campaign-b" })

        expect(signal.aborted).toBe(true)
        expect(result.current.status).toEqual({ kind: "idle" })

        await act(async () => {
            resolveRequest({ resource_grant_id: "new-grant" })
        })

        expect(onSuccess).not.toHaveBeenCalled()
        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("aborts the in-flight request when the hook unmounts", () => {
        addResourceGrantMock.mockReturnValue(new Promise(() => {}))

        const { result, unmount } = renderHook(() =>
            useAddResourceGrant("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "character.view_full",
            )
        })

        const signal = addResourceGrantMock.mock.calls[0]?.[6] as AbortSignal
        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})
