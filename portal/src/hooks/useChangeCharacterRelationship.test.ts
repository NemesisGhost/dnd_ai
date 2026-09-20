import { act, renderHook, waitFor } from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { ChangeCharacterRelationshipRequestError } from "../api/changeCharacterRelationship"
import { useChangeCharacterRelationship } from "./useChangeCharacterRelationship"

const { changeCharacterRelationshipMock, reloadMock, sessionStateRef } =
    vi.hoisted(() => ({
        changeCharacterRelationshipMock: vi.fn(),
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

vi.mock("../api/changeCharacterRelationship", async (importOriginal) => {
    const actual =
        await importOriginal<
            typeof import("../api/changeCharacterRelationship")
        >()

    return {
        ...actual,
        changeCharacterRelationship: changeCharacterRelationshipMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        state: sessionStateRef.current,
        reload: reloadMock,
    }),
}))

beforeEach(() => {
    changeCharacterRelationshipMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useChangeCharacterRelationship", () => {
    it("starts idle", () => {
        const { result } = renderHook(() =>
            useChangeCharacterRelationship("campaign-a", vi.fn()),
        )

        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("goes pending on submit, then success, calling onSuccess and reloading the session", async () => {
        const onSuccess = vi.fn()
        let resolveRequest!: (value: {
            membership_character_relationship_id: string
        }) => void
        changeCharacterRelationshipMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result } = renderHook(() =>
            useChangeCharacterRelationship("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("relationship-a", "type-b")
        })

        expect(result.current.status).toEqual({ kind: "pending" })
        expect(changeCharacterRelationshipMock).toHaveBeenCalledWith(
            "campaign-a",
            "relationship-a",
            "type-b",
            "fixture-csrf-token",
            expect.any(String),
            expect.any(AbortSignal),
        )
        expect(onSuccess).not.toHaveBeenCalled()

        await act(async () => {
            resolveRequest({
                membership_character_relationship_id: "new-relationship",
            })
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)
        expect(reloadMock).toHaveBeenCalledTimes(1)
    })

    it("ignores a second submit while one is already pending", () => {
        changeCharacterRelationshipMock.mockReturnValue(new Promise(() => {}))

        const { result } = renderHook(() =>
            useChangeCharacterRelationship("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("relationship-a", "type-b")
        })
        act(() => {
            result.current.submit("relationship-a", "type-c")
        })

        expect(changeCharacterRelationshipMock).toHaveBeenCalledTimes(1)
    })

    it("reloads the session and returns to idle on an unauthorized response", async () => {
        changeCharacterRelationshipMock.mockRejectedValue(
            new ChangeCharacterRelationshipRequestError(401),
        )

        const { result } = renderHook(() =>
            useChangeCharacterRelationship("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("relationship-a", "type-b")
        })

        await waitFor(() => {
            expect(reloadMock).toHaveBeenCalledTimes(1)
        })
        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it.each([403, 404])(
        "reports a denied status for a non-disclosing %s response",
        async (status) => {
            changeCharacterRelationshipMock.mockRejectedValue(
                new ChangeCharacterRelationshipRequestError(status),
            )

            const { result } = renderHook(() =>
                useChangeCharacterRelationship("campaign-a", vi.fn()),
            )

            act(() => {
                result.current.submit("relationship-a", "type-b")
            })

            await waitFor(() => {
                expect(result.current.status).toEqual({ kind: "denied" })
            })
        },
    )

    it("reports a conflict status for a 409 response", async () => {
        changeCharacterRelationshipMock.mockRejectedValue(
            new ChangeCharacterRelationshipRequestError(409),
        )

        const { result } = renderHook(() =>
            useChangeCharacterRelationship("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("relationship-a", "type-b")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "conflict" })
        })
    })

    it("reports a validation status for a 422 response", async () => {
        changeCharacterRelationshipMock.mockRejectedValue(
            new ChangeCharacterRelationshipRequestError(422),
        )

        const { result } = renderHook(() =>
            useChangeCharacterRelationship("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("relationship-a", "type-b")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "validation" })
        })
    })

    it("reports a recoverable error for any other failure and allows a retry, reusing the same idempotency key", async () => {
        changeCharacterRelationshipMock
            .mockRejectedValueOnce(new Error("network down"))
            .mockResolvedValueOnce({
                membership_character_relationship_id: "new-relationship",
            })

        const onSuccess = vi.fn()
        const { result } = renderHook(() =>
            useChangeCharacterRelationship("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("relationship-a", "type-b")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })

        act(() => {
            result.current.submit("relationship-a", "type-b")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)

        const firstKey = changeCharacterRelationshipMock.mock.calls[0]?.[4]
        const secondKey = changeCharacterRelationshipMock.mock.calls[1]?.[4]
        expect(typeof firstKey).toBe("string")
        expect(secondKey).toEqual(firstKey)
    })

    it("resets to idle", async () => {
        changeCharacterRelationshipMock.mockRejectedValue(
            new ChangeCharacterRelationshipRequestError(409),
        )

        const { result } = renderHook(() =>
            useChangeCharacterRelationship("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("relationship-a", "type-b")
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
        changeCharacterRelationshipMock.mockReturnValue(new Promise(() => {}))

        const { result, unmount } = renderHook(() =>
            useChangeCharacterRelationship("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("relationship-a", "type-b")
        })

        const signal = changeCharacterRelationshipMock.mock
            .calls[0]?.[5] as AbortSignal
        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})
