import { act, renderHook, waitFor } from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { AssignMembershipRoleRequestError } from "../api/assignMembershipRole"
import { useAssignMembershipRole } from "./useAssignMembershipRole"

const { assignMembershipRoleMock, reloadMock, sessionStateRef } =
    vi.hoisted(() => ({
        assignMembershipRoleMock: vi.fn(),
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

vi.mock("../api/assignMembershipRole", async (importOriginal) => {
    const actual =
        await importOriginal<
            typeof import("../api/assignMembershipRole")
        >()

    return {
        ...actual,
        assignMembershipRole: assignMembershipRoleMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        state: sessionStateRef.current,
        reload: reloadMock,
    }),
}))

beforeEach(() => {
    assignMembershipRoleMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useAssignMembershipRole", () => {
    it("starts idle", () => {
        const { result } = renderHook(() =>
            useAssignMembershipRole("campaign-a", vi.fn()),
        )

        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("goes pending on submit, then success, calling onSuccess and reloading the session", async () => {
        const onSuccess = vi.fn()
        let resolveRequest!: (value: {
            membership_role_id: string
        }) => void
        assignMembershipRoleMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result } = renderHook(() =>
            useAssignMembershipRole("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("membership-a", "role-b")
        })

        expect(result.current.status).toEqual({ kind: "pending" })
        expect(assignMembershipRoleMock).toHaveBeenCalledWith(
            "campaign-a",
            "membership-a",
            "role-b",
            "fixture-csrf-token",
            expect.any(String),
            expect.any(AbortSignal),
        )
        expect(onSuccess).not.toHaveBeenCalled()

        await act(async () => {
            resolveRequest({ membership_role_id: "new-membership-role" })
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)
        expect(reloadMock).toHaveBeenCalledTimes(1)
    })

    it("ignores a second submit while one is already pending", () => {
        assignMembershipRoleMock.mockReturnValue(new Promise(() => {}))

        const { result } = renderHook(() =>
            useAssignMembershipRole("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-a", "role-b")
        })
        act(() => {
            result.current.submit("membership-a", "role-c")
        })

        expect(assignMembershipRoleMock).toHaveBeenCalledTimes(1)
    })

    it("reloads the session and returns to idle on an unauthorized response", async () => {
        assignMembershipRoleMock.mockRejectedValue(
            new AssignMembershipRoleRequestError(401),
        )

        const { result } = renderHook(() =>
            useAssignMembershipRole("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-a", "role-b")
        })

        await waitFor(() => {
            expect(reloadMock).toHaveBeenCalledTimes(1)
        })
        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it.each([403, 404])(
        "reports a denied status for a non-disclosing %s response",
        async (status) => {
            assignMembershipRoleMock.mockRejectedValue(
                new AssignMembershipRoleRequestError(status),
            )

            const { result } = renderHook(() =>
                useAssignMembershipRole("campaign-a", vi.fn()),
            )

            act(() => {
                result.current.submit("membership-a", "role-b")
            })

            await waitFor(() => {
                expect(result.current.status).toEqual({ kind: "denied" })
            })
        },
    )

    it("reports a conflict status for a 409 response", async () => {
        assignMembershipRoleMock.mockRejectedValue(
            new AssignMembershipRoleRequestError(409),
        )

        const { result } = renderHook(() =>
            useAssignMembershipRole("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-a", "role-b")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "conflict" })
        })
    })

    it("reports a recoverable error for any other failure and allows a retry, reusing the same idempotency key", async () => {
        assignMembershipRoleMock
            .mockRejectedValueOnce(new Error("network down"))
            .mockResolvedValueOnce({
                membership_role_id: "new-membership-role",
            })

        const onSuccess = vi.fn()
        const { result } = renderHook(() =>
            useAssignMembershipRole("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("membership-a", "role-b")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })

        act(() => {
            result.current.submit("membership-a", "role-b")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)

        const firstKey = assignMembershipRoleMock.mock.calls[0]?.[4]
        const secondKey = assignMembershipRoleMock.mock.calls[1]?.[4]
        expect(typeof firstKey).toBe("string")
        expect(secondKey).toEqual(firstKey)
    })

    it("generates a different key for a different target membership", async () => {
        assignMembershipRoleMock
            .mockRejectedValueOnce(new Error("network down"))
            .mockResolvedValueOnce({
                membership_role_id: "new-membership-role",
            })

        const { result } = renderHook(() =>
            useAssignMembershipRole("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-a", "role-b")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })

        act(() => {
            result.current.submit("membership-z", "role-b")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })

        const firstKey = assignMembershipRoleMock.mock.calls[0]?.[4]
        const secondKey = assignMembershipRoleMock.mock.calls[1]?.[4]
        expect(secondKey).not.toEqual(firstKey)
    })

    it("resets to idle", async () => {
        assignMembershipRoleMock.mockRejectedValue(
            new AssignMembershipRoleRequestError(409),
        )

        const { result } = renderHook(() =>
            useAssignMembershipRole("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-a", "role-b")
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
        assignMembershipRoleMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result, rerender } = renderHook(
            ({ campaignId }) =>
                useAssignMembershipRole(campaignId, onSuccess),
            { initialProps: { campaignId: "campaign-a" } },
        )

        act(() => {
            result.current.submit("membership-a", "role-b")
        })
        expect(result.current.status).toEqual({ kind: "pending" })

        const signal = assignMembershipRoleMock.mock
            .calls[0]?.[5] as AbortSignal

        rerender({ campaignId: "campaign-b" })

        expect(signal.aborted).toBe(true)
        expect(result.current.status).toEqual({ kind: "idle" })

        await act(async () => {
            resolveRequest({ membership_role_id: "new-membership-role" })
        })

        expect(onSuccess).not.toHaveBeenCalled()
        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("aborts the in-flight request when the hook unmounts", () => {
        assignMembershipRoleMock.mockReturnValue(new Promise(() => {}))

        const { result, unmount } = renderHook(() =>
            useAssignMembershipRole("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-a", "role-b")
        })

        const signal = assignMembershipRoleMock.mock
            .calls[0]?.[5] as AbortSignal
        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})
