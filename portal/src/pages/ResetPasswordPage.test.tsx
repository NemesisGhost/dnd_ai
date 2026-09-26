import { fireEvent, render, screen } from "@testing-library/react"
import { StrictMode } from "react"
import { MemoryRouter, Route, Routes } from "react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ResetPasswordPage } from "./ResetPasswordPage"
import type { ResetPasswordStatus } from "../hooks/useResetPassword"

const { statusRef, submitMock, resetMock } = vi.hoisted(() => ({
    statusRef: { current: { kind: "idle" } as ResetPasswordStatus },
    submitMock: vi.fn(),
    resetMock: vi.fn(),
}))

vi.mock("../hooks/useResetPassword", () => ({
    useResetPassword: () => ({ status: statusRef.current, submit: submitMock, reset: resetMock }),
}))

beforeEach(() => {
    statusRef.current = { kind: "idle" }
    submitMock.mockReset()
    resetMock.mockReset()
    window.history.replaceState(null, "", "/auth/password-reset")
})

function renderPage(path: string) {
    return render(
        <MemoryRouter initialEntries={[path]}>
            <Routes>
                <Route path="/auth/password-reset" element={<ResetPasswordPage />} />
                <Route path="/login" element={<p>Login page</p>} />
            </Routes>
        </MemoryRouter>,
    )
}

describe("ResetPasswordPage", () => {
    it("shows an invalid-link message with no token fragment", () => {
        renderPage("/auth/password-reset")
        expect(
            screen.getByRole("heading", { name: "This password-reset link is not valid" }),
        ).toBeInTheDocument()
    })

    it("clears the fragment and submits the extracted token with the new password", () => {
        window.history.replaceState(null, "", "/auth/password-reset#token=raw-token")
        renderPage("/auth/password-reset")

        expect(window.location.hash).toBe("")

        fireEvent.change(screen.getByLabelText("New passphrase"), {
            target: { value: "new-password-15-chars" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Reset password" }))

        expect(submitMock).toHaveBeenCalledWith("raw-token", "new-password-15-chars")
    })

    it("extracts the token exactly once under StrictMode's double-invoked render", () => {
        window.history.replaceState(null, "", "/auth/password-reset#token=raw-token")
        render(
            <StrictMode>
                <MemoryRouter initialEntries={["/auth/password-reset"]}>
                    <Routes>
                        <Route path="/auth/password-reset" element={<ResetPasswordPage />} />
                    </Routes>
                </MemoryRouter>
            </StrictMode>,
        )

        fireEvent.change(screen.getByLabelText("New passphrase"), {
            target: { value: "new-password-15-chars" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Reset password" }))

        expect(submitMock).toHaveBeenCalledWith("raw-token", "new-password-15-chars")
        expect(window.location.hash).toBe("")
    })

    it("shows whether other sessions were revoked", () => {
        statusRef.current = { kind: "success", result: { user_id: "user-1", sessions_revoked: true } }
        window.history.replaceState(null, "", "/auth/password-reset#token=raw-token")
        renderPage("/auth/password-reset")

        expect(screen.getByText(/every existing browser session has been signed out/i)).toBeInTheDocument()
    })
})
