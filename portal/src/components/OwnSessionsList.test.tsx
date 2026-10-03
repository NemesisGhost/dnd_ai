import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { OwnSessionsList } from "./OwnSessionsList"
import type { OwnBrowserSession } from "../types/accountSessions"

const sessions: OwnBrowserSession[] = [
    {
        browser_session_id: "session-1",
        created_at: "2026-09-01T00:00:00Z",
        last_used_at: "2026-09-02T00:00:00Z",
        idle_expires_at: "2026-09-02T00:30:00Z",
        absolute_expires_at: "2026-09-01T12:00:00Z",
        created_ip: "203.0.113.5",
        last_used_ip: "203.0.113.5",
        user_agent: "TestAgent/1.0",
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
]

describe("OwnSessionsList", () => {
    it("renders a real table with headers, IP/device as plain text", () => {
        render(<OwnSessionsList sessions={sessions} onRevoke={vi.fn()} revokingSessionId={null} />)

        expect(screen.getByRole("table")).toBeInTheDocument()
        expect(screen.getByRole("columnheader", { name: "Current" })).toBeInTheDocument()
        expect(screen.getByText("203.0.113.5")).toBeInTheDocument()
        expect(screen.queryByRole("link")).not.toBeInTheDocument()
    })

    it("calls onRevoke with the session id and isCurrent flag", () => {
        const onRevoke = vi.fn()
        render(<OwnSessionsList sessions={sessions} onRevoke={onRevoke} revokingSessionId={null} />)

        const revokeButtons = screen.getAllByRole("button", { name: "Revoke" })
        fireEvent.click(revokeButtons[0]!)
        expect(onRevoke).toHaveBeenCalledWith("session-1", true)

        fireEvent.click(revokeButtons[1]!)
        expect(onRevoke).toHaveBeenCalledWith("session-2", false)
    })

    it("disables only the row currently being revoked", () => {
        render(
            <OwnSessionsList
                sessions={sessions}
                onRevoke={vi.fn()}
                revokingSessionId="session-2"
            />,
        )

        const revokeButtons = screen.getAllByRole("button", { name: "Revoke" })
        expect(revokeButtons[0]).not.toBeDisabled()
        expect(revokeButtons[1]).toBeDisabled()
    })
})
