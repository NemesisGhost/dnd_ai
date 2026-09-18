import { act, renderHook, waitFor } from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { RevokeMembershipRoleRequestError } from "../api/revokeMembershipRole"
import { useRevokeMembershipRole } from "./useRevokeMembershipRole"

const { revokeMembershipRoleMock, reloadMock, sessionStateRef } =
    vi.hoisted(() => ({
        revokeMembershipRoleMock: vi.fn(),
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

vi.mock("../api/revokeMembershipRole", async (importOriginal) => {
    const actual =
        await importOriginal<
            typeof import("../api/revokeMembershipRole")
        >()

    return {
        ...actual,
        revokeMembershipRole: revokeMembershipRoleMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        state: sessionStateRef.current,
        reload: reloadMock,
    }),
}))

beforeEach(() => {
    revokeMembershipRoleMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useRevokeMembershipRole", () => {
    it("starts idle", () => {
        const { result } = renderHook(() =>
            useRevokeMembershipRole("campaign-a", vi.fn()),
        )

        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("goes pending on submit, then success, calling onSuccess and reloading the session", async () => {
        const onSuccess = vi.fn()
        let resolveRequest!: (value: {
            membership_role_id: string
        }) => void
        revokeMembershipRoleMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result } = renderHook(() =>
            useRevokeMembershipRole("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("membership-role-a")
        })

        expect(result.current.status).toEqual({ kind: "pending" })
        expect(revokeMembershipRoleMock).toHaveBeenCalledWith(
            "campaign-a",
            "membership-role-a",
            "fixture-csrf-token",
            expect.any(String),
            expect.any(AbortSignal),
        )
        expect(onSuccess).not.toHaveBeenCalled()

        await act(async () => {
            resolveRequest({ membership_role_id: "membership-role-a" })
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)
        expect(reloadMock).toHaveBeenCalledTimes(1)
    })

    it("ignores a second submit while one is already pending", () => {
        revokeMembershipRoleMock.mockReturnValue(new Promise(() => {}))

        const { result } = renderHook(() =>
            useRevokeMembershipRole("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-role-a")
        })
        act(() => {
            result.current.submit("membership-role-a")
        })

        expect(revokeMembershipRoleMock).toHaveBeenCalledTimes(1)
    })

    it("reloads the session and returns to idle on an unauthorized response", async () => {
        revokeMembershipRoleMock.mockRejectedValue(
            new RevokeMembershipRoleRequestError(401),
        )

        const { result } = renderHook(() =>
            useRevokeMembershipRole("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-role-a")
        })

        await waitFor(() => {
            expect(reloadMock).toHaveBeenCalledTimes(1)
        })
        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it.each([403, 404])(
        "reports a denied status for a non-disclosing %s response",
        async (status) => {
            revokeMembershipRoleMock.mockRejectedValue(
                new RevokeMembershipRoleRequestError(status),
            )

            const { result } = renderHook(() =>
                useRevokeMembershipRole("campaign-a", vi.fn()),
            )

            act(() => {
                result.current.submit("membership-role-a")
            })

            await waitFor(() => {
                expect(result.current.status).toEqual({ kind: "denied" })
            })
        },
    )

    it("reports a conflict status for a 409 response", async () => {
        revokeMembershipRoleMock.mockRejectedValue(
            new RevokeMembershipRoleRequestError(409),
        )

        const { result } = renderHook(() =>
            useRevokeMembershipRole("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-role-a")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "conflict" })
        })
    })

    it("reports a recoverable error for any other failure and allows a retry, reusing the same idempotency key", async () => {
        revokeMembershipRoleMock
            .mockRejectedValueOnce(new Error("network down"))
            .mockResolvedValueOnce({
                membership_role_id: "membership-role-a",
            })

        const onSuccess = vi.fn()
        const { result } = renderHook(() =>
            useRevokeMembershipRole("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("membership-role-a")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })

        act(() => {
            result.current.submit("membership-role-a")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)

        const firstKey = revokeMembershipRoleMock.mock.calls[0]?.[3]
        const secondKey = revokeMembershipRoleMock.mock.calls[1]?.[3]
        expect(typeof firstKey).toBe("string")
        expect(secondKey).toEqual(firstKey)
    })

    it("generates a different key for a different target row", async () => {
        revokeMembershipRoleMock
            .mockRejectedValueOnce(new Error("network down"))
            .mockResolvedValueOnce({
                membership_role_id: "membership-role-z",
            })

        const { result } = renderHook(() =>
            useRevokeMembershipRole("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-role-a")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })

        act(() => {
            result.current.submit("membership-role-z")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })

        const firstKey = revokeMembershipRoleMock.mock.calls[0]?.[3]
        const secondKey = revokeMembershipRoleMock.mock.calls[1]?.[3]
        expect(secondKey).not.toEqual(firstKey)
    })

    it("resets to idle", async () => {
        revokeMembershipRoleMock.mockRejectedValue(
            new RevokeMembershipRoleRequestError(409),
        )

        const { result } = renderHook(() =>
            useRevokeMembershipRole("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-role-a")
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
        revokeMembershipRoleMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result, rerender } = renderHook(
            ({ campaignId }) =>
                useRevokeMembershipRole(campaignId, onSuccess),
            { initialProps: { campaignId: "campaign-a" } },
        )

        act(() => {
            result.current.submit("membership-role-a")
        })
        expect(result.current.status).toEqual({ kind: "pending" })

        const signal = revokeMembershipRoleMock.mock
            .calls[0]?.[4] as AbortSignal

        rerender({ campaignId: "campaign-b" })

        expect(signal.aborted).toBe(true)
        expect(result.current.status).toEqual({ kind: "idle" })

        await act(async () => {
            resolveRequest({ membership_role_id: "membership-role-a" })
        })

        expect(onSuccess).not.toHaveBeenCalled()
        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("aborts the in-flight request when the hook unmounts", () => {
        revokeMembershipRoleMock.mockReturnValue(new Promise(() => {}))

        const { result, unmount } = renderHook(() =>
            useRevokeMembershipRole("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-role-a")
        })

        const signal = revokeMembershipRoleMock.mock
            .calls[0]?.[4] as AbortSignal
        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})
