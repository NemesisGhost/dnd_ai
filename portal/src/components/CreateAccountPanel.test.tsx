import { act, fireEvent, render, screen } from "@testing-library/react"
import { RouterProvider, createMemoryRouter } from "react-router"
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

// A data router, because the panel guards unsaved input with useBlocker. The page-level behavior (the route,
// the guard questions, focus and the one-time link's lifecycle) is covered in pages/CreateAccountPage.test.tsx.
function renderPanel() {
    const router = createMemoryRouter(
        [
            {
                path: "/platform/accounts/new",
                element: <CreateAccountPanel returnTo={{ pathname: "/platform/accounts", search: "" }} />,
            },
        ],
        { initialEntries: ["/platform/accounts/new"] },
    )
    return render(<RouterProvider router={router} />)
}

beforeEach(() => {
    statusRef.current = { kind: "idle" }
    submitMock.mockReset()
    resetMock.mockReset()
    successCallbackRef.current = null
})

describe("CreateAccountPanel", () => {
    it("submits trimmed login name, display name, and null for a blank email", () => {
        renderPanel()

        fireEvent.change(screen.getByLabelText("Login name"), {
            target: { value: "  new.gm  " },
        })
        fireEvent.change(screen.getByLabelText("Display name"), {
            target: { value: "  New GM  " },
        })
        fireEvent.click(screen.getByRole("button", { name: "Create account" }))

        expect(submitMock).toHaveBeenCalledWith("new.gm", "New GM", null, ["player"])
    })

    it("shows the one-time activation link, for the named account, once the account is created", () => {
        renderPanel()

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

        expect(
            screen.getByRole("heading", { name: "Copy the activation link for New GM now" }),
        ).toBeInTheDocument()
        const link = screen.getByLabelText("Activation link")
        expect(link).toHaveValue(`${window.location.origin}/activate#token=raw-token`)
        expect(screen.getByRole("button", { name: "Back to accounts" })).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Create another account" })).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Dismiss" })).not.toBeInTheDocument()
    })
})
