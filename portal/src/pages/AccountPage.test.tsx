import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { AccountPage } from "./AccountPage"
import type { ChangePasswordStatus } from "../hooks/useChangePassword"
import type { OwnSessionsState } from "../hooks/useOwnSessions"

const {
    changeStatusRef,
    changeSubmitMock,
    sessionsStateRef,
    retrySessionsMock,
    revokeSubmitMock,
    revokeSuccessRef,
    reloadMock,
} = vi.hoisted(() => ({
    changeStatusRef: { current: { kind: "idle" as ChangePasswordStatus["kind"] } },
    changeSubmitMock: vi.fn(),
    sessionsStateRef: { current: { status: "loading" } as OwnSessionsState },
    retrySessionsMock: vi.fn(),
    revokeSubmitMock: vi.fn(),
    revokeSuccessRef: { current: null as null | ((id: string, isCurrent: boolean) => void) },
    reloadMock: vi.fn(),
}))

vi.mock("../hooks/useChangePassword", () => ({
    useChangePassword: (onSuccess: () => void) => {
        void onSuccess
        return { status: changeStatusRef.current, submit: changeSubmitMock, reset: vi.fn() }
    },
}))
vi.mock("../hooks/useOwnSessions", () => ({
    useOwnSessions: () => ({ state: sessionsStateRef.current, retry: retrySessionsMock }),
}))
vi.mock("../hooks/useRevokeOwnSession", () => ({
    useRevokeOwnSession: (onSuccess: (id: string, isCurrent: boolean) => void) => {
        revokeSuccessRef.current = onSuccess
        return { status: { kind: "idle" }, submit: revokeSubmitMock, reset: vi.fn() }
    },
}))
vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: { status: "authenticated" }, reload: reloadMock }),
}))

beforeEach(() => {
    changeStatusRef.current = { kind: "idle" }
    changeSubmitMock.mockReset()
    sessionsStateRef.current = { status: "loading" }
    retrySessionsMock.mockReset()
    revokeSubmitMock.mockReset()
    revokeSuccessRef.current = null
    reloadMock.mockReset()
})

describe("AccountPage", () => {
    it("shows a loading state for sessions", () => {
        render(<AccountPage />)
        expect(screen.getByText("Loading sessions…")).toBeInTheDocument()
    })

    it("shows a generic message for a weak new password", () => {
        changeStatusRef.current = { kind: "policy_violation" }
        render(<AccountPage />)
        expect(screen.getByText(/choose a passphrase of at least 15 characters/i)).toBeInTheDocument()
    })

    it("shows a generic message for a wrong current password", () => {
        changeStatusRef.current = { kind: "denied" }
        render(<AccountPage />)
        expect(screen.getByText(/current password did not match/i)).toBeInTheDocument()
    })

    it("submits the change-password form with both password fields", () => {
        render(<AccountPage />)
        fireEvent.change(screen.getByLabelText("Current password"), {
            target: { value: "old-password-15-chars" },
        })
        fireEvent.change(screen.getByLabelText("New password"), {
            target: { value: "new-password-15-chars" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Change password" }))

        expect(changeSubmitMock).toHaveBeenCalledWith(
            "old-password-15-chars",
            "new-password-15-chars",
        )
    })

    it("marks the current session and revoking another refreshes the list", () => {
        sessionsStateRef.current = {
            status: "success",
            sessions: [
                {
                    browser_session_id: "session-1",
                    created_at: "2026-09-01T00:00:00Z",
                    last_used_at: "2026-09-01T00:00:00Z",
                    idle_expires_at: "2026-09-01T00:30:00Z",
                    absolute_expires_at: "2026-09-01T12:00:00Z",
                    created_ip: null,
                    last_used_ip: null,
                    user_agent: null,
                    is_current: true,
                },
                {
                    browser_session_id: "session-2",
                    created_at: "2026-09-01T00:00:00Z",
                    last_used_at: "2026-09-01T00:00:00Z",
                    idle_expires_at: "2026-09-01T00:30:00Z",
                    absolute_expires_at: "2026-09-01T12:00:00Z",
                    created_ip: null,
                    last_used_ip: null,
                    user_agent: null,
                    is_current: false,
                },
            ],
        }
        render(<AccountPage />)

        const revokeButtons = screen.getAllByRole("button", { name: "Revoke" })
        fireEvent.click(revokeButtons[1]!)
        expect(revokeSubmitMock).toHaveBeenCalledWith("session-2", false)

        revokeSuccessRef.current?.("session-2", false)
        expect(retrySessionsMock).toHaveBeenCalledTimes(1)
        expect(reloadMock).not.toHaveBeenCalled()
    })

    it("reloads the session (triggering sign-out) when revoking the current session", () => {
        sessionsStateRef.current = {
            status: "success",
            sessions: [
                {
                    browser_session_id: "session-1",
                    created_at: "2026-09-01T00:00:00Z",
                    last_used_at: "2026-09-01T00:00:00Z",
                    idle_expires_at: "2026-09-01T00:30:00Z",
                    absolute_expires_at: "2026-09-01T12:00:00Z",
                    created_ip: null,
                    last_used_ip: null,
                    user_agent: null,
                    is_current: true,
                },
            ],
        }
        render(<AccountPage />)

        fireEvent.click(screen.getByRole("button", { name: "Revoke" }))
        revokeSuccessRef.current?.("session-1", true)

        expect(reloadMock).toHaveBeenCalledTimes(1)
        expect(retrySessionsMock).not.toHaveBeenCalled()
    })
})
