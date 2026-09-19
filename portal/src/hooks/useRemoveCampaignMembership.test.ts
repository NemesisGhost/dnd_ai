import { act, renderHook, waitFor } from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { RemoveCampaignMembershipRequestError } from "../api/removeCampaignMembership"
import { useRemoveCampaignMembership } from "./useRemoveCampaignMembership"

const { removeCampaignMembershipMock, reloadMock, sessionStateRef } =
    vi.hoisted(() => ({
        removeCampaignMembershipMock: vi.fn(),
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

vi.mock("../api/removeCampaignMembership", async (importOriginal) => {
    const actual =
        await importOriginal<
            typeof import("../api/removeCampaignMembership")
        >()

    return {
        ...actual,
        removeCampaignMembership: removeCampaignMembershipMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        state: sessionStateRef.current,
        reload: reloadMock,
    }),
}))

beforeEach(() => {
    removeCampaignMembershipMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useRemoveCampaignMembership", () => {
    it("starts idle", () => {
        const { result } = renderHook(() =>
            useRemoveCampaignMembership("campaign-a", vi.fn()),
        )

        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("goes pending on submit, then success, calling onSuccess and reloading the session", async () => {
        const onSuccess = vi.fn()
        let resolveRequest!: (value: {
            campaign_membership_id: string
        }) => void
        removeCampaignMembershipMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result } = renderHook(() =>
            useRemoveCampaignMembership("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("membership-a")
        })

        expect(result.current.status).toEqual({ kind: "pending" })
        expect(removeCampaignMembershipMock).toHaveBeenCalledWith(
            "campaign-a",
            "membership-a",
            "fixture-csrf-token",
            expect.any(String),
            expect.any(AbortSignal),
        )
        expect(onSuccess).not.toHaveBeenCalled()

        await act(async () => {
            resolveRequest({ campaign_membership_id: "membership-a" })
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)
        expect(reloadMock).toHaveBeenCalledTimes(1)
    })

    it("ignores a second submit while one is already pending", () => {
        removeCampaignMembershipMock.mockReturnValue(new Promise(() => {}))

        const { result } = renderHook(() =>
            useRemoveCampaignMembership("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-a")
        })
        act(() => {
            result.current.submit("membership-a")
        })

        expect(removeCampaignMembershipMock).toHaveBeenCalledTimes(1)
    })

    it("reloads the session and returns to idle on an unauthorized response", async () => {
        removeCampaignMembershipMock.mockRejectedValue(
            new RemoveCampaignMembershipRequestError(401),
        )

        const { result } = renderHook(() =>
            useRemoveCampaignMembership("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-a")
        })

        await waitFor(() => {
            expect(reloadMock).toHaveBeenCalledTimes(1)
        })
        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it.each([403, 404])(
        "reports a denied status for a non-disclosing %s response",
        async (status) => {
            removeCampaignMembershipMock.mockRejectedValue(
                new RemoveCampaignMembershipRequestError(status),
            )

            const { result } = renderHook(() =>
                useRemoveCampaignMembership("campaign-a", vi.fn()),
            )

            act(() => {
                result.current.submit("membership-a")
            })

            await waitFor(() => {
                expect(result.current.status).toEqual({ kind: "denied" })
            })
        },
    )

    it("reports a last_manager status for a 400 response", async () => {
        removeCampaignMembershipMock.mockRejectedValue(
            new RemoveCampaignMembershipRequestError(400),
        )

        const { result } = renderHook(() =>
            useRemoveCampaignMembership("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-a")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "last_manager" })
        })
    })

    it("reports a conflict status for a 409 response", async () => {
        removeCampaignMembershipMock.mockRejectedValue(
            new RemoveCampaignMembershipRequestError(409),
        )

        const { result } = renderHook(() =>
            useRemoveCampaignMembership("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-a")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "conflict" })
        })
    })

    it("reports a recoverable error for any other failure and allows a retry, reusing the same idempotency key", async () => {
        removeCampaignMembershipMock
            .mockRejectedValueOnce(new Error("network down"))
            .mockResolvedValueOnce({
                campaign_membership_id: "membership-a",
            })

        const onSuccess = vi.fn()
        const { result } = renderHook(() =>
            useRemoveCampaignMembership("campaign-a", onSuccess),
        )

        act(() => {
            result.current.submit("membership-a")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })

        act(() => {
            result.current.submit("membership-a")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)

        const firstKey = removeCampaignMembershipMock.mock.calls[0]?.[3]
        const secondKey = removeCampaignMembershipMock.mock.calls[1]?.[3]
        expect(typeof firstKey).toBe("string")
        expect(secondKey).toEqual(firstKey)
    })

    it("generates a different key for a different target membership", async () => {
        removeCampaignMembershipMock
            .mockRejectedValueOnce(new Error("network down"))
            .mockResolvedValueOnce({
                campaign_membership_id: "membership-z",
            })

        const { result } = renderHook(() =>
            useRemoveCampaignMembership("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-a")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })

        act(() => {
            result.current.submit("membership-z")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })

        const firstKey = removeCampaignMembershipMock.mock.calls[0]?.[3]
        const secondKey = removeCampaignMembershipMock.mock.calls[1]?.[3]
        expect(secondKey).not.toEqual(firstKey)
    })

    it("resets to idle", async () => {
        removeCampaignMembershipMock.mockRejectedValue(
            new RemoveCampaignMembershipRequestError(409),
        )

        const { result } = renderHook(() =>
            useRemoveCampaignMembership("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-a")
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
            campaign_membership_id: string
        }) => void
        removeCampaignMembershipMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result, rerender } = renderHook(
            ({ campaignId }) =>
                useRemoveCampaignMembership(campaignId, onSuccess),
            { initialProps: { campaignId: "campaign-a" } },
        )

        act(() => {
            result.current.submit("membership-a")
        })
        expect(result.current.status).toEqual({ kind: "pending" })

        const signal = removeCampaignMembershipMock.mock
            .calls[0]?.[4] as AbortSignal

        rerender({ campaignId: "campaign-b" })

        expect(signal.aborted).toBe(true)
        expect(result.current.status).toEqual({ kind: "idle" })

        await act(async () => {
            resolveRequest({ campaign_membership_id: "membership-a" })
        })

        expect(onSuccess).not.toHaveBeenCalled()
        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("aborts the in-flight request when the hook unmounts", () => {
        removeCampaignMembershipMock.mockReturnValue(new Promise(() => {}))

        const { result, unmount } = renderHook(() =>
            useRemoveCampaignMembership("campaign-a", vi.fn()),
        )

        act(() => {
            result.current.submit("membership-a")
        })

        const signal = removeCampaignMembershipMock.mock
            .calls[0]?.[4] as AbortSignal
        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})
