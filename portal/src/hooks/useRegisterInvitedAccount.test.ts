import { act, renderHook, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { InvitationOnboardingRequestError } from "../api/invitationOnboarding"
import { useRegisterInvitedAccount } from "./useRegisterInvitedAccount"

const { registerInvitedAccountMock } = vi.hoisted(() => ({
    registerInvitedAccountMock: vi.fn(),
}))

vi.mock("../api/invitationOnboarding", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/invitationOnboarding")>()
    return {
        ...actual,
        registerInvitedAccount: registerInvitedAccountMock,
    }
})

const input = {
    loginName: "new.player",
    displayName: "New Player",
    password: "correct-onboarding-password-15",
    onboardingCsrfToken: "onboarding-csrf",
}

describe("useRegisterInvitedAccount", () => {
    it("registers successfully", async () => {
        const onSuccess = vi.fn()
        registerInvitedAccountMock.mockResolvedValue({
            csrf_token: "session-csrf",
            campaign_display_name: "Fixture Campaign",
        })

        const { result } = renderHook(() => useRegisterInvitedAccount(onSuccess))

        act(() => {
            result.current.submit(input)
        })

        await waitFor(() => {
            expect(result.current.status.kind).toBe("success")
        })
        expect(onSuccess).toHaveBeenCalledWith({
            csrf_token: "session-csrf",
            campaign_display_name: "Fixture Campaign",
        })
        expect(registerInvitedAccountMock).toHaveBeenCalledWith(
            "new.player",
            "New Player",
            "correct-onboarding-password-15",
            "onboarding-csrf",
            expect.anything(),
        )
    })

    it("maps a 400 to policy_violation", async () => {
        registerInvitedAccountMock.mockRejectedValue(
            new InvitationOnboardingRequestError(400, "weak password"),
        )
        const { result } = renderHook(() => useRegisterInvitedAccount(vi.fn()))

        act(() => {
            result.current.submit(input)
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "policy_violation" })
        })
    })

    it("maps a 409 to login_name_taken", async () => {
        registerInvitedAccountMock.mockRejectedValue(
            new InvitationOnboardingRequestError(409, "taken"),
        )
        const { result } = renderHook(() => useRegisterInvitedAccount(vi.fn()))

        act(() => {
            result.current.submit(input)
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "login_name_taken" })
        })
    })

    it("maps a 404 to unavailable", async () => {
        registerInvitedAccountMock.mockRejectedValue(
            new InvitationOnboardingRequestError(404, "unavailable"),
        )
        const { result } = renderHook(() => useRegisterInvitedAccount(vi.fn()))

        act(() => {
            result.current.submit(input)
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "unavailable" })
        })
    })
})
