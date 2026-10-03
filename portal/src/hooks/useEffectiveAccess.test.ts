import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { EffectiveAccessRequestError } from "../api/effectiveAccess"
import type { MemberEffectiveAccess } from "../types/effectiveAccess"
import { useEffectiveAccess } from "./useEffectiveAccess"

const { fetchMemberEffectiveAccessMock, reloadMock } = vi.hoisted(() => ({
    fetchMemberEffectiveAccessMock: vi.fn(),
    reloadMock: vi.fn(),
}))

vi.mock("../api/effectiveAccess", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/effectiveAccess")>()
    return {
        ...actual,
        fetchMemberEffectiveAccess: fetchMemberEffectiveAccessMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ reload: reloadMock }),
}))

const firstMemberAccess: MemberEffectiveAccess = {
    display_name: "Player One",
    capabilities: [
        {
            code: "campaign.view",
            display_name: "View Campaign",
            sources: [{ kind: "role", label: "Player", target_display_name: null }],
        },
    ],
    denials: [],
}

const secondMemberAccess: MemberEffectiveAccess = {
    display_name: "Player Two",
    capabilities: [],
    denials: [],
}

beforeEach(() => {
    fetchMemberEffectiveAccessMock.mockReset()
    reloadMock.mockReset()
    reloadMock.mockResolvedValue(undefined)
})

describe("useEffectiveAccess", () => {
    it("loads the authorized member's effective access", async () => {
        fetchMemberEffectiveAccessMock.mockResolvedValue(firstMemberAccess)

        const { result } = renderHook(() => useEffectiveAccess("campaign-a", "membership-a"))

        expect(result.current.state).toEqual({ status: "loading" })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                access: firstMemberAccess,
            })
        })

        expect(fetchMemberEffectiveAccessMock).toHaveBeenCalledWith(
            "campaign-a",
            "membership-a",
            expect.any(AbortSignal),
        )
    })

    it.each([403, 404])("treats HTTP %s as unavailable", async (status) => {
        fetchMemberEffectiveAccessMock.mockRejectedValue(new EffectiveAccessRequestError(status))

        const { result } = renderHook(() => useEffectiveAccess("campaign-a", "membership-a"))

        await waitFor(() => {
            expect(result.current.state).toEqual({ status: "unavailable" })
        })
    })

    it("reloads the browser session after an unauthorized response", async () => {
        fetchMemberEffectiveAccessMock.mockRejectedValue(new EffectiveAccessRequestError(401))

        renderHook(() => useEffectiveAccess("campaign-a", "membership-a"))

        await waitFor(() => {
            expect(reloadMock).toHaveBeenCalledTimes(1)
        })
    })

    it("returns a recoverable error for other failures", async () => {
        const requestError = new Error("The effective access service is unavailable")
        fetchMemberEffectiveAccessMock.mockRejectedValue(requestError)

        const { result } = renderHook(() => useEffectiveAccess("campaign-a", "membership-a"))

        await waitFor(() => {
            expect(result.current.state).toEqual({ status: "error", error: requestError })
        })
    })

    it("retries the effective access request", async () => {
        const requestError = new Error("The effective access service is unavailable")
        fetchMemberEffectiveAccessMock
            .mockRejectedValueOnce(requestError)
            .mockResolvedValueOnce(firstMemberAccess)

        const { result } = renderHook(() => useEffectiveAccess("campaign-a", "membership-a"))

        await waitFor(() => {
            expect(result.current.state.status).toBe("error")
        })

        act(() => {
            result.current.retry()
        })

        expect(result.current.state).toEqual({ status: "loading" })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                access: firstMemberAccess,
            })
        })

        expect(fetchMemberEffectiveAccessMock).toHaveBeenCalledTimes(2)
    })

    it("clears the previous member's access and aborts its request when the member changes", async () => {
        let resolveSecondRequest: ((access: MemberEffectiveAccess) => void) | undefined

        const secondRequest = new Promise<MemberEffectiveAccess>((resolve) => {
            resolveSecondRequest = resolve
        })

        fetchMemberEffectiveAccessMock
            .mockResolvedValueOnce(firstMemberAccess)
            .mockReturnValueOnce(secondRequest)

        const { result, rerender } = renderHook(
            ({ campaignMembershipId }: { campaignMembershipId: string }) =>
                useEffectiveAccess("campaign-a", campaignMembershipId),
            { initialProps: { campaignMembershipId: "membership-a" } },
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                access: firstMemberAccess,
            })
        })

        const firstSignal = fetchMemberEffectiveAccessMock.mock.calls[0]?.[2] as AbortSignal

        rerender({ campaignMembershipId: "membership-b" })

        expect(firstSignal.aborted).toBe(true)
        expect(result.current.state).toEqual({ status: "loading" })

        act(() => {
            resolveSecondRequest?.(secondMemberAccess)
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                access: secondMemberAccess,
            })
        })
    })

    it("aborts the request when the hook unmounts", () => {
        fetchMemberEffectiveAccessMock.mockReturnValue(new Promise<MemberEffectiveAccess>(() => {}))

        const { unmount } = renderHook(() => useEffectiveAccess("campaign-a", "membership-a"))

        const signal = fetchMemberEffectiveAccessMock.mock.calls[0]?.[2] as AbortSignal

        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})
