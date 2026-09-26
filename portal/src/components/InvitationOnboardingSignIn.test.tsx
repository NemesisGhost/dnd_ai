import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { InvitationOnboardingSignIn } from "./InvitationOnboardingSignIn"

const { submitMock } = vi.hoisted(() => ({ submitMock: vi.fn() }))

vi.mock("../hooks/useLogin", () => ({
    useLogin: () => ({ state: { status: "idle" }, submit: submitMock }),
}))

beforeEach(() => {
    submitMock.mockReset()
})

describe("InvitationOnboardingSignIn", () => {
    it("submits credentials and calls onSignedIn only on success", async () => {
        submitMock.mockResolvedValue(true)
        const onSignedIn = vi.fn()

        render(<InvitationOnboardingSignIn onSignedIn={onSignedIn} />)

        fireEvent.change(screen.getByLabelText("Login name"), {
            target: { value: "existing.user" },
        })
        fireEvent.change(screen.getByLabelText("Password"), {
            target: { value: "correct-password-15-chars" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Sign in" }))

        await vi.waitFor(() => {
            expect(submitMock).toHaveBeenCalledWith({
                login_name: "existing.user",
                password: "correct-password-15-chars",
            })
        })
        await vi.waitFor(() => {
            expect(onSignedIn).toHaveBeenCalledTimes(1)
        })
    })

    it("does not call onSignedIn when sign-in fails", async () => {
        submitMock.mockResolvedValue(false)
        const onSignedIn = vi.fn()

        render(<InvitationOnboardingSignIn onSignedIn={onSignedIn} />)

        fireEvent.change(screen.getByLabelText("Login name"), { target: { value: "someone" } })
        fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrong-password" } })
        fireEvent.click(screen.getByRole("button", { name: "Sign in" }))

        await vi.waitFor(() => {
            expect(submitMock).toHaveBeenCalledTimes(1)
        })
        expect(onSignedIn).not.toHaveBeenCalled()
    })
})
