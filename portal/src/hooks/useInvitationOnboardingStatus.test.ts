import { act, renderHook, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { InvitationOnboardingRequestError } from "../api/invitationOnboarding"
import { useInvitationOnboardingStatus } from "./useInvitationOnboardingStatus"

const { fetchInvitationOnboardingStatusMock } = vi.hoisted(() => ({
    fetchInvitationOnboardingStatusMock: vi.fn(),
}))

vi.mock("../api/invitationOnboarding", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/invitationOnboarding")>()
    return {
        ...actual,
        fetchInvitationOnboardingStatus: fetchInvitationOnboardingStatusMock,
    }
})

describe("useInvitationOnboardingStatus", () => {
    it("starts loading then resolves to success", async () => {
        fetchInvitationOnboardingStatusMock.mockResolvedValue({
            campaign_display_name: "Fixture Campaign",
            invitation_expires_at: "2026-10-01T00:00:00Z",
            onboarding_expires_at: "2026-09-25T00:20:00Z",
            next_action: "confirm",
            signed_in_display_name: "Existing User",
        })

        const { result } = renderHook(() => useInvitationOnboardingStatus())

        expect(result.current.state).toEqual({ status: "loading" })

        await waitFor(() => {
            expect(result.current.state.status).toBe("success")
        })
        expect(result.current.state).toMatchObject({
            status: "success",
            data: { next_action: "confirm", signed_in_display_name: "Existing User" },
        })
    })

    it("maps a 404 to unavailable, not an error", async () => {
        fetchInvitationOnboardingStatusMock.mockRejectedValue(
            new InvitationOnboardingRequestError(404, "not available"),
        )

        const { result } = renderHook(() => useInvitationOnboardingStatus())

        await waitFor(() => {
            expect(result.current.state).toEqual({ status: "unavailable" })
        })
    })

    it("retry issues a fresh request", async () => {
        fetchInvitationOnboardingStatusMock.mockRejectedValue(
            new InvitationOnboardingRequestError(404, "not available"),
        )

        const { result } = renderHook(() => useInvitationOnboardingStatus())
        await waitFor(() => {
            expect(result.current.state).toEqual({ status: "unavailable" })
        })

        fetchInvitationOnboardingStatusMock.mockClear()
        fetchInvitationOnboardingStatusMock.mockResolvedValue({
            campaign_display_name: "Fixture Campaign",
            invitation_expires_at: "2026-10-01T00:00:00Z",
            onboarding_expires_at: "2026-09-25T00:20:00Z",
            next_action: "sign_in_or_register",
            signed_in_display_name: null,
        })

        act(() => {
            result.current.retry()
        })

        await waitFor(() => {
            expect(result.current.state.status).toBe("success")
        })
        expect(fetchInvitationOnboardingStatusMock).toHaveBeenCalledTimes(1)
    })
})
