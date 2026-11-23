import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { SystemRolesPanel } from "./SystemRolesPanel"
import type { PlatformAccount } from "../types/platformAccounts"
import type { SystemRoleCode } from "../utils/systemAccess"

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

function renderPanel(
    draft: SystemRoleCode[],
    overrides: Partial<Parameters<typeof SystemRolesPanel>[0]> = {},
) {
    const props = {
        account,
        draft,
        ownAccount: false,
        canGrantAdmin: false,
        reasonId: "reason",
        focusSignal: 1,
        onToggle: vi.fn(),
        onCancel: vi.fn(),
        onClose: vi.fn(),
        ...overrides,
    }
    return { props, ...render(<SystemRolesPanel {...props} />) }
}

describe("SystemRolesPanel", () => {
    it("binds the checkboxes to the draft and reports a press without sending anything", () => {
        const { props } = renderPanel(["player"])
        expect(screen.getByRole("checkbox", { name: "Player" })).toBeChecked()
        fireEvent.click(screen.getByRole("checkbox", { name: "Game master" }))
        expect(props.onToggle).toHaveBeenCalledWith("gm", true)
    })

    it("takes focus on its heading when opened and again when Edit roles is pressed again", () => {
        const { rerender, props } = renderPanel(["player"])
        const heading = screen.getByRole("heading", { level: 2, name: "System roles for Dungeon Master" })
        expect(heading).toHaveFocus()
        screen.getByRole("checkbox", { name: "Player" }).focus()
        rerender(<SystemRolesPanel {...props} focusSignal={2} />)
        expect(heading).toHaveFocus()
    })

    it("offers Close and No changes when clean, and no Save", () => {
        const { props } = renderPanel(["player"])
        expect(screen.getByText("No changes")).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Close" }))
        expect(props.onClose).toHaveBeenCalledTimes(1)
        expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull()
        expect(screen.queryByRole("button", { name: /save/i })).toBeNull()
        expect(screen.getByText("Changes are saved one at a time; some can be saved while others are not.")).toBeInTheDocument()
    })

    it("lists the staged changes and offers Cancel when dirty", () => {
        const { props } = renderPanel(["gm"])
        expect(screen.getByRole("list", { name: "Changes not saved yet" })).toHaveTextContent(
            "Add Game masterRemove Player",
        )
        expect(screen.getByText("Save or cancel these changes before editing another account.")).toHaveAttribute(
            "id",
            "reason",
        )
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        expect(props.onCancel).toHaveBeenCalledTimes(1)
        expect(screen.queryByRole("button", { name: "Close" })).toBeNull()
    })

    it("lists the signed-in account's own Administrator removal last", () => {
        renderPanel(["observer"], { account: { ...account, system_roles: ["admin", "player"] }, ownAccount: true })
        expect(screen.getByRole("list", { name: "Changes not saved yet" })).toHaveTextContent(
            "Add ObserverRemove PlayerRemove Administrator",
        )
    })
})
