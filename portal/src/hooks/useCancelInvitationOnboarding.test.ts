import { act, renderHook, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { InvitationOnboardingRequestError } from "../api/invitationOnboarding"
import { useCancelInvitationOnboarding } from "./useCancelInvitationOnboarding"

const { cancelInvitationOnboardingMock } = vi.hoisted(() => ({
    cancelInvitationOnboardingMock: vi.fn(),
}))

vi.mock("../api/invitationOnboarding", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/invitationOnboarding")>()
    return {
        ...actual,
        cancelInvitationOnboarding: cancelInvitationOnboardingMock,
    }
})

describe("useCancelInvitationOnboarding", () => {
    it("cancels successfully", async () => {
        const onSuccess = vi.fn()
        cancelInvitationOnboardingMock.mockResolvedValue(undefined)

        const { result } = renderHook(() => useCancelInvitationOnboarding(onSuccess))

        act(() => {
            result.current.submit("onboarding-csrf")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledTimes(1)
        expect(cancelInvitationOnboardingMock).toHaveBeenCalledWith(
            "onboarding-csrf",
            expect.anything(),
        )
    })

    it("maps a 404 to unavailable", async () => {
        cancelInvitationOnboardingMock.mockRejectedValue(
            new InvitationOnboardingRequestError(404, "unavailable"),
        )
        const { result } = renderHook(() => useCancelInvitationOnboarding(vi.fn()))

        act(() => {
            result.current.submit("onboarding-csrf")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "unavailable" })
        })
    })
})
