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
} = vi.hoisted(() => ({
    resetSubmitMock: vi.fn(),
    disableSubmitMock: vi.fn(),
    reactivateSubmitMock: vi.fn(),
    revokeSubmitMock: vi.fn(),
    resetSuccessRef: { current: null as null | ((result: unknown) => void) },
    disableSuccessRef: { current: null as null | (() => void) },
    disableStatusRef: { current: { kind: "idle" as string } },
}))

vi.mock("../hooks/useIssuePasswordReset", () => ({
    useIssuePasswordReset: (onSuccess: (result: unknown) => void) => {
        resetSuccessRef.current = onSuccess
        return { status: { kind: "idle" }, submit: resetSubmitMock, reset: vi.fn() }
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
})

describe("AccountLifecycleActions", () => {
    it("requires an explicit confirm click before disabling", () => {
        render(<AccountLifecycleActions account={activeAccount} onChanged={vi.fn()} />)

        fireEvent.click(screen.getByRole("button", { name: "Disable" }))
        expect(disableSubmitMock).not.toHaveBeenCalled()

        fireEvent.click(screen.getByRole("button", { name: "Confirm disable" }))
        expect(disableSubmitMock).toHaveBeenCalledWith("user-1")
    })

    it("cancel returns to the Disable button without submitting", () => {
        render(<AccountLifecycleActions account={activeAccount} onChanged={vi.fn()} />)

        fireEvent.click(screen.getByRole("button", { name: "Disable" }))
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))

        expect(screen.getByRole("button", { name: "Disable" })).toBeInTheDocument()
        expect(disableSubmitMock).not.toHaveBeenCalled()
    })

    it("shows Reactivate instead of Disable for an inactive account", () => {
        render(
            <AccountLifecycleActions
                account={{ ...activeAccount, lifecycle_status_code: "inactive" }}
                onChanged={vi.fn()}
            />,
        )

        expect(screen.getByRole("button", { name: "Reactivate" })).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Disable" })).not.toBeInTheDocument()
    })

    it("shows the one-time password-reset link once issued", () => {
        const onChanged = vi.fn()
        render(<AccountLifecycleActions account={activeAccount} onChanged={onChanged} />)

        fireEvent.click(screen.getByRole("button", { name: "Issue password reset" }))
        expect(resetSubmitMock).toHaveBeenCalledWith("user-1", true)

        act(() => {
            resetSuccessRef.current?.({
                user_id: "user-1",
                raw_reset_token: "raw-reset-token",
                expires_at: "2026-10-01T00:00:00Z",
            })
        })

        expect(onChanged).toHaveBeenCalledTimes(1)
        expect(screen.getByLabelText("Password-reset link")).toHaveValue(
            `${window.location.origin}/auth/password-reset#token=raw-reset-token`,
        )
    })

    it("surfaces the last-active-administrator conflict message", () => {
        disableStatusRef.current = {
            kind: "conflict",
            message: "This is the platform's only active administrator account and cannot be disabled.",
        } as never

        render(<AccountLifecycleActions account={activeAccount} onChanged={vi.fn()} />)

        expect(screen.getByRole("status")).toHaveTextContent(/only active administrator/i)
    })
})
