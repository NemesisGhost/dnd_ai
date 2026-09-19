import { act, renderHook, waitFor } from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { RevokeCharacterRelationshipRequestError } from "../api/revokeCharacterRelationship"
import { useRevokeCharacterRelationship } from "./useRevokeCharacterRelationship"

const { revokeCharacterRelationshipMock, reloadMock, sessionStateRef } =
    vi.hoisted(() => ({
        revokeCharacterRelationshipMock: vi.fn(),
        reloadMock: vi.fn(),
        sessionStateRef: {
            current: {
                status: "authenticated" as const,
                bootstrap: {
                    csrf_token: "fixture-csrf-token",
                },
            },
        },
    }))

vi.mock("../api/revokeCharacterRelationship", async (importOriginal) => {
    const actual =
        await importOriginal<
            typeof import("../api/revokeCharacterRelationship")
        >()

    return {
        ...actual,
        revokeCharacterRelationship: revokeCharacterRelationshipMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        state: sessionStateRef.current,
        reload: reloadMock,
    }),
}))

beforeEach(() => {
    revokeCharacterRelationshipMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useRevokeCharacterRelationship", () => {
    it("starts idle", () => {
        const { result } = renderHook(() =>
            useRevokeCharacterRelationship("campaign-a", vi.fn()),
        )

        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("goes pending on submit, then success, calling onSuccess and reloading the session", async () => {
        const onSuccess = vi.fn()
        let resolveRequest!: (value: {
            membership_character_relationship_id: string
        }) => void
        revokeCharacterRelationshipMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result } = renderHook(() =>
            useRevokeCharacterRelationship("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("relationship-a")
        })

        expect(result.current.status).toEqual({ kind: "pending" })
        expect(revokeCharacterRelationshipMock).toHaveBeenCalledWith(
            "campaign-a",
            "relationship-a",
            "fixture-csrf-token",
            expect.any(String),
            expect.any(AbortSignal),
        )
        expect(onSuccess).not.toHaveBeenCalled()

        await act(async () => {
            resolveRequest({
                membership_character_relationship_id: "relationship-a",
            })
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)
        expect(reloadMock).toHaveBeenCalledTimes(1)
    })

    it("ignores a second submit while one is already pending", () => {
        revokeCharacterRelationshipMock.mockReturnValue(new Promise(() => {}))

        const { result } = renderHook(() =>
            useRevokeCharacterRelationship("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("relationship-a")
        })
        act(() => {
            result.current.submit("relationship-a")
        })

        expect(revokeCharacterRelationshipMock).toHaveBeenCalledTimes(1)
    })

    it("reloads the session and returns to idle on an unauthorized response", async () => {
        revokeCharacterRelationshipMock.mockRejectedValue(
            new RevokeCharacterRelationshipRequestError(401),
        )

        const { result } = renderHook(() =>
            useRevokeCharacterRelationship("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("relationship-a")
        })

        await waitFor(() => {
            expect(reloadMock).toHaveBeenCalledTimes(1)
        })
        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it.each([403, 404])(
        "reports a denied status for a non-disclosing %s response",
        async (status) => {
            revokeCharacterRelationshipMock.mockRejectedValue(
                new RevokeCharacterRelationshipRequestError(status),
            )

            const { result } = renderHook(() =>
                useRevokeCharacterRelationship("campaign-a", vi.fn()),
            )

            act(() => {
                result.current.submit("relationship-a")
            })

            await waitFor(() => {
                expect(result.current.status).toEqual({ kind: "denied" })
            })
        },
    )

    it("reports a conflict status for a 409 response", async () => {
        revokeCharacterRelationshipMock.mockRejectedValue(
            new RevokeCharacterRelationshipRequestError(409),
        )

        const { result } = renderHook(() =>
            useRevokeCharacterRelationship("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("relationship-a")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "conflict" })
        })
    })

    it("reports a recoverable error for any other failure and allows a retry, reusing the same idempotency key", async () => {
        revokeCharacterRelationshipMock
            .mockRejectedValueOnce(new Error("network down"))
            .mockResolvedValueOnce({
                membership_character_relationship_id: "relationship-a",
            })

        const onSuccess = vi.fn()
        const { result } = renderHook(() =>
            useRevokeCharacterRelationship("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("relationship-a")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })

        act(() => {
            result.current.submit("relationship-a")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)

        const firstKey = revokeCharacterRelationshipMock.mock.calls[0]?.[3]
        const secondKey = revokeCharacterRelationshipMock.mock.calls[1]?.[3]
        expect(typeof firstKey).toBe("string")
        expect(secondKey).toEqual(firstKey)
    })

    it("resets to idle", async () => {
        revokeCharacterRelationshipMock.mockRejectedValue(
            new RevokeCharacterRelationshipRequestError(409),
        )

        const { result } = renderHook(() =>
            useRevokeCharacterRelationship("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("relationship-a")
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
        revokeCharacterRelationshipMock.mockReturnValue(new Promise(() => {}))

        const { result, unmount } = renderHook(() =>
            useRevokeCharacterRelationship("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("relationship-a")
        })

        const signal = revokeCharacterRelationshipMock.mock
            .calls[0]?.[4] as AbortSignal
        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})
