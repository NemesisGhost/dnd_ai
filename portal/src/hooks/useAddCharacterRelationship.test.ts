import { act, renderHook, waitFor } from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { AddCharacterRelationshipRequestError } from "../api/addCharacterRelationship"
import { useAddCharacterRelationship } from "./useAddCharacterRelationship"

const { addCharacterRelationshipMock, reloadMock, sessionStateRef } =
    vi.hoisted(() => ({
        addCharacterRelationshipMock: vi.fn(),
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

vi.mock("../api/addCharacterRelationship", async (importOriginal) => {
    const actual =
        await importOriginal<
            typeof import("../api/addCharacterRelationship")
        >()

    return {
        ...actual,
        addCharacterRelationship: addCharacterRelationshipMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        state: sessionStateRef.current,
        reload: reloadMock,
    }),
}))

beforeEach(() => {
    addCharacterRelationshipMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useAddCharacterRelationship", () => {
    it("starts idle", () => {
        const { result } = renderHook(() =>
            useAddCharacterRelationship("campaign-a", vi.fn()),
        )

        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("goes pending on submit, then success, calling onSuccess and reloading the session", async () => {
        const onSuccess = vi.fn()
        let resolveRequest!: (value: {
            membership_character_relationship_id: string
        }) => void
        addCharacterRelationshipMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result } = renderHook(() =>
            useAddCharacterRelationship("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "viewer",
            )
        })

        expect(result.current.status).toEqual({ kind: "pending" })
        expect(addCharacterRelationshipMock).toHaveBeenCalledWith(
            "campaign-a",
            "membership-a",
            "character-a",
            "viewer",
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
        addCharacterRelationshipMock.mockReturnValue(new Promise(() => {}))

        const { result } = renderHook(() =>
            useAddCharacterRelationship("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "viewer",
            )
        })
        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "portrayer",
            )
        })

        expect(addCharacterRelationshipMock).toHaveBeenCalledTimes(1)
    })

    it("reloads the session and returns to idle on an unauthorized response", async () => {
        addCharacterRelationshipMock.mockRejectedValue(
            new AddCharacterRelationshipRequestError(401),
        )

        const { result } = renderHook(() =>
            useAddCharacterRelationship("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "viewer",
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
            addCharacterRelationshipMock.mockRejectedValue(
                new AddCharacterRelationshipRequestError(status),
            )

            const { result } = renderHook(() =>
                useAddCharacterRelationship("campaign-a", vi.fn()),
            )

            act(() => {
                result.current.submit(
                    "membership-a",
                    "character-a",
                    "viewer",
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
            addCharacterRelationshipMock.mockRejectedValue(
                new AddCharacterRelationshipRequestError(status),
            )

            const { result } = renderHook(() =>
                useAddCharacterRelationship("campaign-a", vi.fn()),
            )

            act(() => {
                result.current.submit(
                    "membership-a",
                    "character-a",
                    "viewer",
                )
            })

            await waitFor(() => {
                expect(result.current.status).toEqual({ kind: "conflict" })
            })
        },
    )

    it("reports a recoverable error for any other failure and allows a retry, reusing the same idempotency key", async () => {
        addCharacterRelationshipMock
            .mockRejectedValueOnce(new Error("network down"))
            .mockResolvedValueOnce({
                membership_character_relationship_id: "new-relationship",
            })

        const onSuccess = vi.fn()
        const { result } = renderHook(() =>
            useAddCharacterRelationship("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "viewer",
            )
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })

        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "viewer",
            )
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)

        const firstKey = addCharacterRelationshipMock.mock.calls[0]?.[5]
        const secondKey = addCharacterRelationshipMock.mock.calls[1]?.[5]
        expect(typeof firstKey).toBe("string")
        expect(secondKey).toEqual(firstKey)
    })

    it("generates a different key for a different character/type selection", async () => {
        addCharacterRelationshipMock
            .mockRejectedValueOnce(new Error("network down"))
            .mockResolvedValueOnce({
                membership_character_relationship_id: "new-relationship",
            })

        const { result } = renderHook(() =>
            useAddCharacterRelationship("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "viewer",
            )
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })

        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "portrayer",
            )
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })

        const firstKey = addCharacterRelationshipMock.mock.calls[0]?.[5]
        const secondKey = addCharacterRelationshipMock.mock.calls[1]?.[5]
        expect(secondKey).not.toEqual(firstKey)
    })

    it("resets to idle", async () => {
        addCharacterRelationshipMock.mockRejectedValue(
            new AddCharacterRelationshipRequestError(409),
        )

        const { result } = renderHook(() =>
            useAddCharacterRelationship("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "viewer",
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
        let resolveRequest!: (value: {
            membership_character_relationship_id: string
        }) => void
        addCharacterRelationshipMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result, rerender } = renderHook(
            ({ campaignId }) =>
                useAddCharacterRelationship(campaignId, onSuccess),
            { initialProps: { campaignId: "campaign-a" } },
        )

        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "viewer",
            )
        })
        expect(result.current.status).toEqual({ kind: "pending" })

        const signal = addCharacterRelationshipMock.mock
            .calls[0]?.[6] as AbortSignal

        rerender({ campaignId: "campaign-b" })

        expect(signal.aborted).toBe(true)
        expect(result.current.status).toEqual({ kind: "idle" })

        await act(async () => {
            resolveRequest({
                membership_character_relationship_id: "new-relationship",
            })
        })

        expect(onSuccess).not.toHaveBeenCalled()
        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("aborts the in-flight request when the hook unmounts", () => {
        addCharacterRelationshipMock.mockReturnValue(new Promise(() => {}))

        const { result, unmount } = renderHook(() =>
            useAddCharacterRelationship("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit(
                "membership-a",
                "character-a",
                "viewer",
            )
        })

        const signal = addCharacterRelationshipMock.mock
            .calls[0]?.[6] as AbortSignal
        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})
