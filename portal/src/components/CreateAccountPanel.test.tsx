import { act, fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { CreateAccountPanel } from "./CreateAccountPanel"

const { statusRef, submitMock, resetMock, successCallbackRef } = vi.hoisted(() => ({
    statusRef: { current: { kind: "idle" as string } },
    submitMock: vi.fn(),
    resetMock: vi.fn(),
    successCallbackRef: { current: null as null | ((result: unknown) => void) },
}))

vi.mock("../hooks/useCreateAccount", () => ({
    useCreateAccount: (onSuccess: (result: unknown) => void) => {
        successCallbackRef.current = onSuccess
        return { status: statusRef.current, submit: submitMock, reset: resetMock }
    },
}))

beforeEach(() => {
    statusRef.current = { kind: "idle" }
    submitMock.mockReset()
    resetMock.mockReset()
    successCallbackRef.current = null
})

describe("CreateAccountPanel", () => {
    it("submits trimmed login name, display name, and null for a blank email", () => {
        const onCreated = vi.fn()
        render(<CreateAccountPanel onCreated={onCreated} />)

        fireEvent.change(screen.getByLabelText("Login name"), {
            target: { value: "  new.gm  " },
        })
        fireEvent.change(screen.getByLabelText("Display name"), {
            target: { value: "  New GM  " },
        })
        fireEvent.click(screen.getByRole("button", { name: "Create account" }))

        expect(submitMock).toHaveBeenCalledWith("new.gm", "New GM", null)
    })

    it("shows the one-time activation link once the account is created", () => {
        const onCreated = vi.fn()
        render(<CreateAccountPanel onCreated={onCreated} />)

        fireEvent.change(screen.getByLabelText("Login name"), { target: { value: "new.gm" } })
        fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "New GM" } })

        act(() => {
            successCallbackRef.current?.({
                user_id: "user-1",
                login_name: "new.gm",
                raw_activation_token: "raw-token",
                expires_at: "2026-10-01T00:00:00Z",
            })
        })

        expect(onCreated).toHaveBeenCalledTimes(1)
        const link = screen.getByLabelText("Activation link")
        expect(link).toHaveValue(`${window.location.origin}/activate#token=raw-token`)
    })
})
