import { renderHook } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import * as userPreferences from "../api/userPreferences"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { SessionBootstrap } from "../types/bootstrap"
import { useRecordLastVisitedCampaign } from "./useRecordLastVisitedCampaign"

vi.mock("../api/userPreferences", () => ({
    recordLastVisitedCampaign: vi.fn(),
}))

const record = vi.mocked(userPreferences.recordLastVisitedCampaign)

function bootstrapWith(lastVisited: string | null): SessionBootstrap {
    return {
        ...sessionBootstrapFixture,
        campaign_preferences: {
            startup_mode: "resume_last_visited",
            preferred_campaign_id: null,
            last_visited_campaign_id: lastVisited,
        },
    }
}

beforeEach(() => {
    record.mockReset()
    record.mockResolvedValue(undefined)
})

describe("useRecordLastVisitedCampaign", () => {
    it("records a campaign that differs from the stored value, with the csrf token", () => {
        renderHook(() => useRecordLastVisitedCampaign("campaign-a", bootstrapWith(null)))

        expect(record).toHaveBeenCalledTimes(1)
        expect(record).toHaveBeenCalledWith(
            "campaign-a",
            sessionBootstrapFixture.csrf_token,
            expect.any(AbortSignal),
        )
    })

    it("does nothing when the campaign is already the stored last visited", () => {
        renderHook(() =>
            useRecordLastVisitedCampaign("campaign-a", bootstrapWith("campaign-a")),
        )
        expect(record).not.toHaveBeenCalled()
    })

    it("does nothing for a null (unauthorized or unresolved) campaign", () => {
        renderHook(() => useRecordLastVisitedCampaign(null, bootstrapWith(null)))
        expect(record).not.toHaveBeenCalled()
    })

    it("aborts the in-flight request on unmount", () => {
        const { unmount } = renderHook(() =>
            useRecordLastVisitedCampaign("campaign-a", bootstrapWith(null)),
        )
        const signal = record.mock.calls[0]![2] as AbortSignal
        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })

    it("aborts the previous campaign request when the campaign changes", () => {
        const { rerender } = renderHook(
            ({ id }) => useRecordLastVisitedCampaign(id, bootstrapWith(null)),
            { initialProps: { id: "campaign-a" as string | null } },
        )
        const first = record.mock.calls[0]![2] as AbortSignal

        rerender({ id: "campaign-b" })

        expect(first.aborted).toBe(true)
        expect(record).toHaveBeenCalledTimes(2)
        expect(record.mock.calls[1]![0]).toBe("campaign-b")
    })

    it("swallows request failures", async () => {
        record.mockRejectedValue(new Error("boom"))

        expect(() =>
            renderHook(() => useRecordLastVisitedCampaign("campaign-a", bootstrapWith(null))),
        ).not.toThrow()
        await Promise.resolve()
    })
})
