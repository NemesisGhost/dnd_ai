import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { SystemRolesEditor } from "./SystemRolesEditor"
import type { PlatformAccount } from "../types/platformAccounts"

const { changeMock, statusRef } = vi.hoisted(() => ({
    changeMock: vi.fn(),
    statusRef: { current: { kind: "idle" } as { kind: string; message?: string } },
}))

vi.mock("../hooks/useSystemRoleChange", () => ({
    useSystemRoleChange: () => ({ status: statusRef.current, change: changeMock }),
}))

const account: PlatformAccount = {
    user_id: "user-1",
    display_name: "Dungeon Master",
    login_name: "dm",
    lifecycle_status_code: "active",
    is_platform_administrator: false,
    system_roles: ["player"],
    has_local_credential: true,
    has_outstanding_activation: false,
    last_login_at: null,
    active_session_count: 0,
}

beforeEach(() => {
    changeMock.mockReset()
    statusRef.current = { kind: "idle" }
})

describe("SystemRolesEditor", () => {
    it("shows held roles as checked", () => {
        render(<SystemRolesEditor account={account} canGrantAdmin={false} onChanged={vi.fn()} />)

        expect(screen.getByRole("checkbox", { name: "Player" })).toBeChecked()
        expect(screen.getByRole("checkbox", { name: "Game master" })).not.toBeChecked()
    })

    it("assigns Game master for the target account when ticked", () => {
        render(<SystemRolesEditor account={account} canGrantAdmin={false} onChanged={vi.fn()} />)

        fireEvent.click(screen.getByRole("checkbox", { name: "Game master" }))

        expect(changeMock).toHaveBeenCalledWith("user-1", "gm", true)
    })

    it("revokes a held role when unticked", () => {
        render(<SystemRolesEditor account={account} canGrantAdmin={false} onChanged={vi.fn()} />)

        fireEvent.click(screen.getByRole("checkbox", { name: "Player" }))

        expect(changeMock).toHaveBeenCalledWith("user-1", "player", false)
    })

    it("disables a new Administrator grant and explains the operator script", () => {
        render(<SystemRolesEditor account={account} canGrantAdmin={false} onChanged={vi.fn()} />)

        expect(screen.getByRole("checkbox", { name: "Administrator" })).toBeDisabled()
        expect(
            screen.getByText(/Granting Administrator is done by the operator script/),
        ).toBeInTheDocument()
    })

    it("enables the Administrator grant only when the server says it is allowed", () => {
        render(<SystemRolesEditor account={account} canGrantAdmin onChanged={vi.fn()} />)

        const admin = screen.getByRole("checkbox", { name: "Administrator" })
        expect(admin).toBeEnabled()
        fireEvent.click(admin)
        expect(changeMock).toHaveBeenCalledWith("user-1", "admin", true)
    })

    it("still lets an existing Administrator be revoked when granting is disabled", () => {
        render(
            <SystemRolesEditor
                account={{ ...account, system_roles: ["admin"] }}
                canGrantAdmin={false}
                onChanged={vi.fn()}
            />,
        )

        expect(screen.getByRole("checkbox", { name: "Administrator" })).toBeEnabled()
    })

    it("reports the last-administrator conflict", () => {
        statusRef.current = { kind: "conflict", message: "Only active administrator." }
        render(<SystemRolesEditor account={account} canGrantAdmin onChanged={vi.fn()} />)

        expect(screen.getByRole("status")).toHaveTextContent("Only active administrator.")
    })
})
