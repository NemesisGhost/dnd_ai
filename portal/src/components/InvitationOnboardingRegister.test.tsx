import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { InvitationOnboardingRegister } from "./InvitationOnboardingRegister"

const { registerHookRef, submitMock, resetMock } = vi.hoisted(() => ({
    registerHookRef: { current: { kind: "idle" as string } },
    submitMock: vi.fn(),
    resetMock: vi.fn(),
}))

vi.mock("../hooks/useRegisterInvitedAccount", () => ({
    useRegisterInvitedAccount: (onSuccess: (result: unknown) => void) => ({
        status: { kind: registerHookRef.current.kind },
        submit: submitMock,
        reset: resetMock,
        __onSuccess: onSuccess,
    }),
}))

beforeEach(() => {
    registerHookRef.current = { kind: "idle" }
    submitMock.mockReset()
    resetMock.mockReset()
})

describe("InvitationOnboardingRegister", () => {
    it("submits the form fields plus the onboarding csrf token", () => {
        render(
            <InvitationOnboardingRegister
                onboardingCsrfToken="onboarding-csrf"
                onRegistered={vi.fn()}
            />,
        )

        fireEvent.change(screen.getByLabelText("Choose a login name"), {
            target: { value: "new.player" },
        })
        fireEvent.change(screen.getByLabelText("Display name"), {
            target: { value: "New Player" },
        })
        fireEvent.change(screen.getByLabelText("Choose a passphrase"), {
            target: { value: "correct-onboarding-password-15" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Create account and join" }))

        expect(submitMock).toHaveBeenCalledWith({
            loginName: "new.player",
            displayName: "New Player",
            password: "correct-onboarding-password-15",
            onboardingCsrfToken: "onboarding-csrf",
        })
    })

    it("shows a login-name-taken message and does not disclose more", () => {
        registerHookRef.current = { kind: "login_name_taken" }

        render(
            <InvitationOnboardingRegister
                onboardingCsrfToken="onboarding-csrf"
                onRegistered={vi.fn()}
            />,
        )

        expect(screen.getByRole("alert")).toHaveTextContent(/already claimed/i)
    })

    it("disables the submit button while pending", () => {
        registerHookRef.current = { kind: "pending" }

        render(
            <InvitationOnboardingRegister
                onboardingCsrfToken="onboarding-csrf"
                onRegistered={vi.fn()}
            />,
        )

        expect(screen.getByRole("button", { name: /creating your account/i })).toBeDisabled()
    })
})
