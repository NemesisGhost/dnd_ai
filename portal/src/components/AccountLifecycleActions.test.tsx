import { act, fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { AccountLifecycleActions } from "./AccountLifecycleActions"
import type { PlatformAccount } from "../types/platformAccounts"

const {
    resetSubmitMock,
    disableSubmitMock,
    reactivateSubmitMock,
    revokeSubmitMock,
    resetSuccessRef,
    disableSuccessRef,
    disableStatusRef,
    resetStatusRef,
} = vi.hoisted(() => ({
    resetSubmitMock: vi.fn(),
    disableSubmitMock: vi.fn(),
    reactivateSubmitMock: vi.fn(),
    revokeSubmitMock: vi.fn(),
    resetSuccessRef: { current: null as null | ((result: unknown) => void) },
    disableSuccessRef: { current: null as null | (() => void) },
    disableStatusRef: { current: { kind: "idle" as string } },
    resetStatusRef: { current: { kind: "idle" as string } },
}))

vi.mock("../hooks/useIssuePasswordReset", () => ({
    useIssuePasswordReset: (onSuccess: (result: unknown) => void) => {
        resetSuccessRef.current = onSuccess
        return { status: resetStatusRef.current, submit: resetSubmitMock, reset: vi.fn() }
    },
}))
vi.mock("../hooks/useDisableAccount", () => ({
    useDisableAccount: (onSuccess: () => void) => {
        disableSuccessRef.current = onSuccess
        return { status: disableStatusRef.current, submit: disableSubmitMock, reset: vi.fn() }
    },
}))
vi.mock("../hooks/useReactivateAccount", () => ({
    useReactivateAccount: () => ({
        status: { kind: "idle" },
        submit: reactivateSubmitMock,
        reset: vi.fn(),
    }),
}))
vi.mock("../hooks/useRevokeAllSessions", () => ({
    useRevokeAllSessions: () => ({
        status: { kind: "idle" },
        submit: revokeSubmitMock,
        reset: vi.fn(),
    }),
}))

const activeAccount: PlatformAccount = {
    user_id: "user-1",
    display_name: "Active Account",
    login_name: "active.account",
    lifecycle_status_code: "active",
    is_platform_administrator: false,
    system_roles: ["player"],
    has_local_credential: true,
    has_outstanding_activation: false,
    last_login_at: null,
    active_session_count: 1,
}

beforeEach(() => {
    resetSubmitMock.mockReset()
    disableSubmitMock.mockReset()
    reactivateSubmitMock.mockReset()
    revokeSubmitMock.mockReset()
    resetSuccessRef.current = null
    disableSuccessRef.current = null
    disableStatusRef.current = { kind: "idle" }
    resetStatusRef.current = { kind: "idle" }
})

function renderActions(account: PlatformAccount = activeAccount) {
    const props = {
        account,
        onChanged: vi.fn(),
        onResetStarted: vi.fn(),
        onResetIssued: vi.fn(),
    }
    render(<AccountLifecycleActions {...props} />)
    return props
}

describe("AccountLifecycleActions", () => {
    it("requires an explicit confirm click before disabling", () => {
        renderActions()

        fireEvent.click(screen.getByRole("button", { name: "Disable" }))
        expect(disableSubmitMock).not.toHaveBeenCalled()

        fireEvent.click(screen.getByRole("button", { name: "Confirm disable" }))
        expect(disableSubmitMock).toHaveBeenCalledWith("user-1")
    })

    it("cancel returns to the Disable button without submitting", () => {
        renderActions()

        fireEvent.click(screen.getByRole("button", { name: "Disable" }))
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))

        expect(screen.getByRole("button", { name: "Disable" })).toBeInTheDocument()
        expect(disableSubmitMock).not.toHaveBeenCalled()
    })

    it("shows Reactivate instead of Disable for an inactive account", () => {
        renderActions({ ...activeAccount, lifecycle_status_code: "inactive" })

        expect(screen.getByRole("button", { name: "Reactivate" })).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Disable" })).not.toBeInTheDocument()
    })

    it("clears any older link, then issues for the target user with session revocation", () => {
        const props = renderActions()

        fireEvent.click(screen.getByRole("button", { name: "Issue password reset" }))

        expect(props.onResetStarted).toHaveBeenCalledTimes(1)
        expect(resetSubmitMock).toHaveBeenCalledWith("user-1", true)
    })

    it("reports the issued secret to the owner and refreshes the list", () => {
        const props = renderActions()

        act(() => {
            resetSuccessRef.current?.({
                user_id: "user-1",
                raw_reset_token: "raw-reset-token",
                expires_at: "2026-10-01T00:00:00Z",
            })
        })

        expect(props.onChanged).toHaveBeenCalledTimes(1)
        expect(props.onResetIssued).toHaveBeenCalledWith({
            displayName: "Active Account",
            rawToken: "raw-reset-token",
            expiresAt: "2026-10-01T00:00:00Z",
        })
        expect(screen.queryByLabelText("Password-reset link")).not.toBeInTheDocument()
    })

    it("shows pending status and disables the issue button", () => {
        resetStatusRef.current = { kind: "pending" }
        renderActions()

        expect(screen.getByRole("status")).toHaveTextContent("Issuing password-reset link")
        expect(screen.getByRole("button", { name: "Issue password reset" })).toBeDisabled()
    })

    it("announces success", () => {
        resetStatusRef.current = { kind: "success" }
        renderActions()

        expect(screen.getByRole("status")).toHaveTextContent(/link issued/i)
    })

    it("reports a recoverable error and keeps the button usable", () => {
        resetStatusRef.current = { kind: "error" }
        renderActions()

        expect(screen.getByRole("status")).toHaveTextContent(
            "The password-reset link could not be issued. Try again.",
        )
        const button = screen.getByRole("button", { name: "Issue password reset" })
        expect(button).toBeEnabled()
        fireEvent.click(button)
        expect(resetSubmitMock).toHaveBeenCalledWith("user-1", true)
    })

    it("keeps the denied presentation non-disclosing", () => {
        resetStatusRef.current = { kind: "denied" }
        renderActions()

        expect(screen.getByRole("status")).toHaveTextContent(
            "You do not have permission to make this change.",
        )
    })

    it("surfaces the last-active-administrator conflict message", () => {
        disableStatusRef.current = {
            kind: "conflict",
            message: "This is the platform's only active administrator account and cannot be disabled.",
        } as never

        renderActions()

        expect(screen.getByRole("status")).toHaveTextContent(/only active administrator/i)
    })
})
