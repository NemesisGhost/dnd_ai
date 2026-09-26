import { act, renderHook, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { InvitationOnboardingRequestError } from "../api/invitationOnboarding"
import { useBeginInvitationOnboarding } from "./useBeginInvitationOnboarding"

const { beginInvitationOnboardingMock } = vi.hoisted(() => ({
    beginInvitationOnboardingMock: vi.fn(),
}))

vi.mock("../api/invitationOnboarding", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/invitationOnboarding")>()
    return {
        ...actual,
        beginInvitationOnboarding: beginInvitationOnboardingMock,
    }
})

describe("useBeginInvitationOnboarding", () => {
    it("begins successfully", async () => {
        beginInvitationOnboardingMock.mockResolvedValue({
            campaign_display_name: "Fixture Campaign",
            invitation_expires_at: "2026-10-01T00:00:00Z",
            onboarding_expires_at: "2026-09-25T00:20:00Z",
            onboarding_csrf_token: "onboarding-csrf",
            next_action: "sign_in_or_register",
            signed_in_display_name: null,
        })

        const { result } = renderHook(() => useBeginInvitationOnboarding())

        act(() => {
            result.current.submit("raw-invitation-token")
        })

        expect(result.current.status).toEqual({ kind: "pending" })

        await waitFor(() => {
            expect(result.current.status.kind).toBe("success")
        })
        expect(beginInvitationOnboardingMock).toHaveBeenCalledWith(
            "raw-invitation-token",
            expect.anything(),
        )
    })

    it("maps a 404 to unavailable", async () => {
        beginInvitationOnboardingMock.mockRejectedValue(
            new InvitationOnboardingRequestError(404, "not available"),
        )

        const { result } = renderHook(() => useBeginInvitationOnboarding())

        act(() => {
            result.current.submit("raw-invitation-token")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "unavailable" })
        })
    })

    it("maps a 429 to rate_limited", async () => {
        beginInvitationOnboardingMock.mockRejectedValue(
            new InvitationOnboardingRequestError(429, "too many"),
        )

        const { result } = renderHook(() => useBeginInvitationOnboarding())

        act(() => {
            result.current.submit("raw-invitation-token")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "rate_limited" })
        })
    })

    it("reset returns to idle", async () => {
        beginInvitationOnboardingMock.mockRejectedValue(
            new InvitationOnboardingRequestError(404, "not available"),
        )

        const { result } = renderHook(() => useBeginInvitationOnboarding())

        act(() => {
            result.current.submit("raw-invitation-token")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "unavailable" })
        })

        act(() => {
            result.current.reset()
        })
        expect(result.current.status).toEqual({ kind: "idle" })
    })
})
