import { fireEvent, render, screen } from "@testing-library/react"
import { StrictMode } from "react"
import { MemoryRouter, Route, Routes } from "react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ActivateAccountPage } from "./ActivateAccountPage"
import type { ActivateAccountStatus } from "../hooks/useActivateAccount"

const { statusRef, submitMock, resetMock } = vi.hoisted(() => ({
    statusRef: { current: { kind: "idle" } as ActivateAccountStatus },
    submitMock: vi.fn(),
    resetMock: vi.fn(),
}))

vi.mock("../hooks/useActivateAccount", () => ({
    useActivateAccount: () => ({ status: statusRef.current, submit: submitMock, reset: resetMock }),
}))

beforeEach(() => {
    statusRef.current = { kind: "idle" }
    submitMock.mockReset()
    resetMock.mockReset()
    window.history.replaceState(null, "", "/auth/activate")
})

function renderPage(path: string) {
    return render(
        <MemoryRouter initialEntries={[path]}>
            <Routes>
                <Route path="/auth/activate" element={<ActivateAccountPage />} />
                <Route path="/login" element={<p>Login page</p>} />
            </Routes>
        </MemoryRouter>,
    )
}

describe("ActivateAccountPage", () => {
    it("shows an invalid-link message with no token fragment", () => {
        renderPage("/auth/activate")
        expect(
            screen.getByRole("heading", { name: "This activation link is not valid" }),
        ).toBeInTheDocument()
    })

    it("clears the fragment and submits the extracted token with the entered password", () => {
        window.history.replaceState(null, "", "/auth/activate#token=raw-token")
        renderPage("/auth/activate")

        expect(window.location.hash).toBe("")

        fireEvent.change(screen.getByLabelText("Choose a passphrase"), {
            target: { value: "correct-password-15-chars" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Activate account" }))

        expect(submitMock).toHaveBeenCalledWith("raw-token", "correct-password-15-chars")
    })

    it("extracts the token exactly once under StrictMode's double-invoked render", () => {
        window.history.replaceState(null, "", "/auth/activate#token=raw-token")
        render(
            <StrictMode>
                <MemoryRouter initialEntries={["/auth/activate"]}>
                    <Routes>
                        <Route path="/auth/activate" element={<ActivateAccountPage />} />
                    </Routes>
                </MemoryRouter>
            </StrictMode>,
        )

        fireEvent.change(screen.getByLabelText("Choose a passphrase"), {
            target: { value: "correct-password-15-chars" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Activate account" }))

        expect(submitMock).toHaveBeenCalledWith("raw-token", "correct-password-15-chars")
        expect(window.location.hash).toBe("")
    })

    it("shows the success screen with a link to sign in, never auto-navigating", () => {
        statusRef.current = { kind: "success", result: { user_id: "user-1", login_name: "new.gm" } }
        window.history.replaceState(null, "", "/auth/activate#token=raw-token")
        renderPage("/auth/activate")

        expect(screen.getByRole("heading", { name: "Account activated" })).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Go to sign in" })).toHaveAttribute(
            "href",
            "/login",
        )
        expect(screen.queryByText("Login page")).not.toBeInTheDocument()
    })
})
