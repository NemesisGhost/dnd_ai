import { act, renderHook, waitFor } from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { EligibleAccountRequestError } from "../api/eligibleAccount"
import { useEligibleAccountLookup } from "./useEligibleAccountLookup"

const { fetchEligibleCampaignAccountMock, reloadMock, sessionStateRef } =
    vi.hoisted(() => ({
        fetchEligibleCampaignAccountMock: vi.fn(),
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

vi.mock("../api/eligibleAccount", async (importOriginal) => {
    const actual =
        await importOriginal<typeof import("../api/eligibleAccount")>()

    return {
        ...actual,
        fetchEligibleCampaignAccount: fetchEligibleCampaignAccountMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        state: sessionStateRef.current,
        reload: reloadMock,
    }),
}))

beforeEach(() => {
    fetchEligibleCampaignAccountMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useEligibleAccountLookup", () => {
    it("starts idle", () => {
        const { result } = renderHook(() =>
            useEligibleAccountLookup("campaign-a"),
        )

        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("goes pending on lookup, then found, with the matched account", async () => {
        let resolveRequest!: (value: {
            account: { user_id: string; display_name: string } | null
        }) => void
        fetchEligibleCampaignAccountMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result } = renderHook(() =>
            useEligibleAccountLookup("campaign-a"),
        )

        act(() => {
            result.current.lookup("player.one")
        })

        expect(result.current.status).toEqual({ kind: "pending" })
        expect(fetchEligibleCampaignAccountMock).toHaveBeenCalledWith(
            "campaign-a",
            "player.one",
            expect.any(AbortSignal),
        )

        await act(async () => {
            resolveRequest({
                account: {
                    user_id: "user-1",
                    display_name: "Player One",
                },
            })
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({
                kind: "found",
                account: {
                    user_id: "user-1",
                    display_name: "Player One",
                },
            })
        })
    })

    it("reports not_found for a successful response with no match", async () => {
        fetchEligibleCampaignAccountMock.mockResolvedValue({
            account: null,
        })

        const { result } = renderHook(() =>
            useEligibleAccountLookup("campaign-a"),
        )

        act(() => {
            result.current.lookup("nonexistent")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "not_found" })
        })
    })

    it("reloads the session and returns to idle on an unauthorized response", async () => {
        fetchEligibleCampaignAccountMock.mockRejectedValue(
            new EligibleAccountRequestError(401),
        )

        const { result } = renderHook(() =>
            useEligibleAccountLookup("campaign-a"),
        )

        act(() => {
            result.current.lookup("someone")
        })

        await waitFor(() => {
            expect(reloadMock).toHaveBeenCalledTimes(1)
        })
        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it.each([403, 404])(
        "reports a denied status for a non-disclosing %s response",
        async (status) => {
            fetchEligibleCampaignAccountMock.mockRejectedValue(
                new EligibleAccountRequestError(status),
            )

            const { result } = renderHook(() =>
                useEligibleAccountLookup("campaign-a"),
            )

            act(() => {
                result.current.lookup("someone")
            })

            await waitFor(() => {
                expect(result.current.status).toEqual({ kind: "denied" })
            })
        },
    )

    it("reports a recoverable error for any other failure and allows a retry", async () => {
        fetchEligibleCampaignAccountMock
            .mockRejectedValueOnce(new Error("network down"))
            .mockResolvedValueOnce({ account: null })

        const { result } = renderHook(() =>
            useEligibleAccountLookup("campaign-a"),
        )

        act(() => {
            result.current.lookup("someone")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "error" })
        })

        act(() => {
            result.current.lookup("someone")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "not_found" })
        })
    })

    it("aborts a still-pending lookup when a new one starts", () => {
        fetchEligibleCampaignAccountMock.mockReturnValue(
            new Promise(() => {}),
        )

        const { result } = renderHook(() =>
            useEligibleAccountLookup("campaign-a"),
        )

        act(() => {
            result.current.lookup("first")
        })
        const firstSignal = fetchEligibleCampaignAccountMock.mock
            .calls[0]?.[2] as AbortSignal

        act(() => {
            result.current.lookup("second")
        })

        expect(firstSignal.aborted).toBe(true)
        expect(fetchEligibleCampaignAccountMock).toHaveBeenCalledTimes(2)
    })

    it("resets to idle and aborts any pending lookup", () => {
        fetchEligibleCampaignAccountMock.mockReturnValue(
            new Promise(() => {}),
        )

        const { result } = renderHook(() =>
            useEligibleAccountLookup("campaign-a"),
        )

        act(() => {
            result.current.lookup("someone")
        })
        const signal = fetchEligibleCampaignAccountMock.mock
            .calls[0]?.[2] as AbortSignal

        act(() => {
            result.current.reset()
        })

        expect(signal.aborted).toBe(true)
        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("ignores a late response after the campaign changes, and aborts the in-flight request", async () => {
        let resolveRequest!: (value: {
            account: { user_id: string; display_name: string } | null
        }) => void
        fetchEligibleCampaignAccountMock.mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            }),
        )

        const { result, rerender } = renderHook(
            ({ campaignId }) => useEligibleAccountLookup(campaignId),
            { initialProps: { campaignId: "campaign-a" } },
        )

        act(() => {
            result.current.lookup("someone")
        })
        expect(result.current.status).toEqual({ kind: "pending" })

        const signal = fetchEligibleCampaignAccountMock.mock
            .calls[0]?.[2] as AbortSignal

        rerender({ campaignId: "campaign-b" })

        expect(signal.aborted).toBe(true)
        expect(result.current.status).toEqual({ kind: "idle" })

        await act(async () => {
            resolveRequest({ account: null })
        })

        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("aborts the in-flight request when the hook unmounts", () => {
        fetchEligibleCampaignAccountMock.mockReturnValue(
            new Promise(() => {}),
        )

        const { result, unmount } = renderHook(() =>
            useEligibleAccountLookup("campaign-a"),
        )

        act(() => {
            result.current.lookup("someone")
        })

        const signal = fetchEligibleCampaignAccountMock.mock
            .calls[0]?.[2] as AbortSignal
        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})
