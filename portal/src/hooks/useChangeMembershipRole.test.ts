import { act, renderHook, waitFor } from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { ChangeMembershipRoleRequestError } from "../api/changeMembershipRole"
import { useChangeMembershipRole } from "./useChangeMembershipRole"

const { changeMembershipRoleMock, reloadMock, sessionStateRef } =
    vi.hoisted(() => ({
        changeMembershipRoleMock: vi.fn(),
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

vi.mock("../api/changeMembershipRole", async (importOriginal) => {
    const actual =
        await importOriginal<
            typeof import("../api/changeMembershipRole")
        >()

    return {
        ...actual,
        changeMembershipRole: changeMembershipRoleMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        state: sessionStateRef.current,
        reload: reloadMock,
    }),
}))

beforeEach(() => {
    changeMembershipRoleMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useChangeMembershipRole", () => {
    it("starts idle", () => {
        const { result } = renderHook(() =>
            useChangeMembershipRole("campaign-a", vi.fn()),
        )

        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("goes pending on submit, then success, calling onSuccess and reloading the session", async () => {
        const onSuccess = vi.fn()
        let resolveRequest!: (value: {
            membership_role_id: string
        }) => void
        changeMembershipRoleMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result } = renderHook(() =>
            useChangeMembershipRole("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("membership-role-a", "role-b")
        })

        expect(result.current.status).toEqual({ kind: "pending" })
        expect(changeMembershipRoleMock).toHaveBeenCalledWith(
            "campaign-a",
            "membership-role-a",
            "role-b",
            "fixture-csrf-token",
            expect.any(String),
            expect.any(AbortSignal),
        )
        expect(onSuccess).not.toHaveBeenCalled()

        await act(async () => {
            resolveRequest({ membership_role_id: "new-role-assignment" })
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)
        expect(reloadMock).toHaveBeenCalledTimes(1)
    })

    it("ignores a second submit while one is already pending", () => {
        changeMembershipRoleMock.mockReturnValue(new Promise(() => {}))

        const { result } = renderHook(() =>
            useChangeMembershipRole("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-role-a", "role-b")
        })
        act(() => {
            result.current.submit("membership-role-a", "role-c")
        })

        expect(changeMembershipRoleMock).toHaveBeenCalledTimes(1)
    })

    it("reloads the session and returns to idle on an unauthorized response", async () => {
        changeMembershipRoleMock.mockRejectedValue(
            new ChangeMembershipRoleRequestError(401),
        )

        const { result } = renderHook(() =>
            useChangeMembershipRole("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-role-a", "role-b")
        })

        await waitFor(() => {
            expect(reloadMock).toHaveBeenCalledTimes(1)
        })
        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it.each([403, 404])(
        "reports a denied status for a non-disclosing %s response",
        async (status) => {
            changeMembershipRoleMock.mockRejectedValue(
                new ChangeMembershipRoleRequestError(status),
            )

            const { result } = renderHook(() =>
                useChangeMembershipRole("campaign-a", vi.fn()),
            )

            act(() => {
                result.current.submit("membership-role-a", "role-b")
            })

            await waitFor(() => {
                expect(result.current.status).toEqual({ kind: "denied" })
            })
        },
    )

    it("reports a conflict status for a 409 response", async () => {
        changeMembershipRoleMock.mockRejectedValue(
            new ChangeMembershipRoleRequestError(409),
        )

        const { result } = renderHook(() =>
            useChangeMembershipRole("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-role-a", "role-b")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "conflict" })
        })
    })

    it("reports a validation status for a 422 response", async () => {
        changeMembershipRoleMock.mockRejectedValue(
            new ChangeMembershipRoleRequestError(422),
        )

        const { result } = renderHook(() =>
            useChangeMembershipRole("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-role-a", "role-b")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "validation" })
        })
    })

    it("reports a recoverable error for any other failure and allows a retry", async () => {
        changeMembershipRoleMock
            .mockRejectedValueOnce(new Error("network down"))
            .mockResolvedValueOnce({
                membership_role_id: "new-role-assignment",
            })

        const onSuccess = vi.fn()
        const { result } = renderHook(() =>
            useChangeMembershipRole("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("membership-role-a", "role-b")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })

        act(() => {
            result.current.submit("membership-role-a", "role-b")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)
    })

    it("resets to idle", async () => {
        changeMembershipRoleMock.mockRejectedValue(
            new ChangeMembershipRoleRequestError(409),
        )

        const { result } = renderHook(() =>
            useChangeMembershipRole("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-role-a", "role-b")
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
            membership_role_id: string
        }) => void
        changeMembershipRoleMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result, rerender } = renderHook(
            ({ campaignId }) =>
                useChangeMembershipRole(campaignId, onSuccess),
            { initialProps: { campaignId: "campaign-a" } },
        )

        act(() => {
            result.current.submit("membership-role-a", "role-b")
        })
        expect(result.current.status).toEqual({ kind: "pending" })

        const signal = changeMembershipRoleMock.mock
            .calls[0]?.[5] as AbortSignal

        rerender({ campaignId: "campaign-b" })

        expect(signal.aborted).toBe(true)
        expect(result.current.status).toEqual({ kind: "idle" })

        await act(async () => {
            resolveRequest({ membership_role_id: "new-role-assignment" })
        })

        expect(onSuccess).not.toHaveBeenCalled()
        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("aborts the in-flight request when the hook unmounts", () => {
        changeMembershipRoleMock.mockReturnValue(new Promise(() => {}))

        const { result, unmount } = renderHook(() =>
            useChangeMembershipRole("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-role-a", "role-b")
        })

        const signal = changeMembershipRoleMock.mock
            .calls[0]?.[5] as AbortSignal
        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })

    describe("idempotency key", () => {
        it("reuses the same key when retrying the identical selection", async () => {
            changeMembershipRoleMock
                .mockRejectedValueOnce(new Error("network down"))
                .mockResolvedValueOnce({
                    membership_role_id: "new-role-assignment",
                })

            const { result } = renderHook(() =>
                useChangeMembershipRole("campaign-a", vi.fn()),
            )

            act(() => {
                result.current.submit("membership-role-a", "role-b")
            })
            await waitFor(() => {
                expect(result.current.status).toEqual({ kind: "error" })
            })

            act(() => {
                result.current.submit("membership-role-a", "role-b")
            })
            await waitFor(() => {
                expect(result.current.status).toEqual({ kind: "success" })
            })

            const firstKey = changeMembershipRoleMock.mock.calls[0]?.[4]
            const secondKey = changeMembershipRoleMock.mock.calls[1]?.[4]
            expect(typeof firstKey).toBe("string")
            expect(secondKey).toEqual(firstKey)
        })

        it("generates a different key for a different new_role_id on the same row", async () => {
            changeMembershipRoleMock
                .mockRejectedValueOnce(new Error("network down"))
                .mockResolvedValueOnce({
                    membership_role_id: "new-role-assignment",
                })

            const { result } = renderHook(() =>
                useChangeMembershipRole("campaign-a", vi.fn()),
            )

            act(() => {
                result.current.submit("membership-role-a", "role-b")
            })
            await waitFor(() => {
                expect(result.current.status).toEqual({ kind: "error" })
            })

            act(() => {
                result.current.submit("membership-role-a", "role-c")
            })
            await waitFor(() => {
                expect(result.current.status).toEqual({ kind: "success" })
            })

            const firstKey = changeMembershipRoleMock.mock.calls[0]?.[4]
            const secondKey = changeMembershipRoleMock.mock.calls[1]?.[4]
            expect(secondKey).not.toEqual(firstKey)
        })

        it("generates a different key for a different target membership_role_id", async () => {
            changeMembershipRoleMock
                .mockRejectedValueOnce(new Error("network down"))
                .mockResolvedValueOnce({
                    membership_role_id: "new-role-assignment",
                })

            const { result } = renderHook(() =>
                useChangeMembershipRole("campaign-a", vi.fn()),
            )

            act(() => {
                result.current.submit("membership-role-a", "role-b")
            })
            await waitFor(() => {
                expect(result.current.status).toEqual({ kind: "error" })
            })

            act(() => {
                result.current.submit("membership-role-z", "role-b")
            })
            await waitFor(() => {
                expect(result.current.status).toEqual({ kind: "success" })
            })

            const firstKey = changeMembershipRoleMock.mock.calls[0]?.[4]
            const secondKey = changeMembershipRoleMock.mock.calls[1]?.[4]
            expect(secondKey).not.toEqual(firstKey)
        })

        it("generates a fresh key after a successful completion, even for the identical selection", async () => {
            changeMembershipRoleMock
                .mockResolvedValueOnce({
                    membership_role_id: "first-assignment",
                })
                .mockResolvedValueOnce({
                    membership_role_id: "second-assignment",
                })

            const { result } = renderHook(() =>
                useChangeMembershipRole("campaign-a", vi.fn()),
            )

            act(() => {
                result.current.submit("membership-role-a", "role-b")
            })
            await waitFor(() => {
                expect(result.current.status).toEqual({ kind: "success" })
            })

            act(() => {
                result.current.submit("membership-role-a", "role-b")
            })
            await waitFor(() => {
                expect(changeMembershipRoleMock).toHaveBeenCalledTimes(2)
            })

            const firstKey = changeMembershipRoleMock.mock.calls[0]?.[4]
            const secondKey = changeMembershipRoleMock.mock.calls[1]?.[4]
            expect(secondKey).not.toEqual(firstKey)
        })

        it("does not reuse a key across a campaign change, even for the identical selection", async () => {
            let resolveFirst!: (value: {
                membership_role_id: string
            }) => void
            changeMembershipRoleMock
                .mockReturnValueOnce(
                    new Promise((resolve) => {
                        resolveFirst = resolve
                    }),
                )
                .mockResolvedValueOnce({
                    membership_role_id: "second-assignment",
                })

            const { result, rerender } = renderHook(
                ({ campaignId }) =>
                    useChangeMembershipRole(campaignId, vi.fn()),
                { initialProps: { campaignId: "campaign-a" } },
            )

            act(() => {
                result.current.submit("membership-role-a", "role-b")
            })
            expect(result.current.status).toEqual({ kind: "pending" })

            rerender({ campaignId: "campaign-b" })
            expect(result.current.status).toEqual({ kind: "idle" })

            act(() => {
                result.current.submit("membership-role-a", "role-b")
            })
            await waitFor(() => {
                expect(changeMembershipRoleMock).toHaveBeenCalledTimes(2)
            })

            const firstKey = changeMembershipRoleMock.mock.calls[0]?.[4]
            const secondKey = changeMembershipRoleMock.mock.calls[1]?.[4]
            expect(secondKey).not.toEqual(firstKey)

            // Resolve the first (aborted, campaign-a) request harmlessly —
            // it must never be left as an unresolved dangling promise.
            await act(async () => {
                resolveFirst({ membership_role_id: "first-assignment" })
            })
        })
    })
})
