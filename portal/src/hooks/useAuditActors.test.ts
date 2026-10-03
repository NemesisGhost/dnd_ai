import { renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { AuditHistoryRequestError } from "../api/auditHistory"
import type { AuditActor } from "../types/auditHistory"
import { useAuditActors } from "./useAuditActors"

const { fetchAuditActorsMock, reloadMock } = vi.hoisted(() => ({
    fetchAuditActorsMock: vi.fn(),
    reloadMock: vi.fn(),
}))

vi.mock("../api/auditHistory", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/auditHistory")>()
    return {
        ...actual,
        fetchAuditActors: fetchAuditActorsMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ reload: reloadMock }),
}))

const firstCampaignActors: AuditActor[] = [
    { user_id: "user-a", display_name: "Player One" },
]
const secondCampaignActors: AuditActor[] = [
    { user_id: "user-b", display_name: "Player Two" },
]

beforeEach(() => {
    fetchAuditActorsMock.mockReset()
    reloadMock.mockReset()
})

describe("useAuditActors", () => {
    it("starts loading, then reports the fetched actor list", async () => {
        fetchAuditActorsMock.mockResolvedValue(firstCampaignActors)

        const { result } = renderHook(() => useAuditActors("campaign-a"))

        expect(result.current.state).toEqual({ status: "loading" })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                actors: firstCampaignActors,
            })
        })
    })

    it("maps a 403/404 to unavailable, never a retryable error", async () => {
        fetchAuditActorsMock.mockRejectedValue(new AuditHistoryRequestError(403))

        const { result } = renderHook(() => useAuditActors("campaign-a"))

        await waitFor(() => {
            expect(result.current.state).toEqual({ status: "unavailable" })
        })
    })

    it("maps an unexpected failure to a plain error state", async () => {
        fetchAuditActorsMock.mockRejectedValue(new Error("network down"))

        const { result } = renderHook(() => useAuditActors("campaign-a"))

        await waitFor(() => {
            expect(result.current.state).toEqual({ status: "error" })
        })
    })

    it("reloads the session on a 401 and clears any retained state", async () => {
        fetchAuditActorsMock.mockRejectedValue(new AuditHistoryRequestError(401))

        const { result } = renderHook(() => useAuditActors("campaign-a"))

        await waitFor(() => {
            expect(reloadMock).toHaveBeenCalledTimes(1)
        })
        expect(result.current.state).toEqual({ status: "loading" })
    })

    it("clears the previous campaign's actors and aborts its request when the campaign changes", async () => {
        let resolveSecondRequest: ((actors: AuditActor[]) => void) | undefined
        const secondRequest = new Promise<AuditActor[]>((resolve) => {
            resolveSecondRequest = resolve
        })

        fetchAuditActorsMock
            .mockResolvedValueOnce(firstCampaignActors)
            .mockReturnValueOnce(secondRequest)

        const { result, rerender } = renderHook(
            ({ campaignId }) => useAuditActors(campaignId),
            { initialProps: { campaignId: "campaign-a" } },
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                actors: firstCampaignActors,
            })
        })

        const firstSignal = fetchAuditActorsMock.mock.calls[0]?.[1] as AbortSignal

        rerender({ campaignId: "campaign-b" })

        // The previous campaign's request is aborted and its actors are no
        // longer exposed while the new campaign's own request is pending.
        expect(firstSignal.aborted).toBe(true)
        expect(result.current.state).toEqual({ status: "loading" })

        resolveSecondRequest?.(secondCampaignActors)
        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                actors: secondCampaignActors,
            })
        })
    })
})
