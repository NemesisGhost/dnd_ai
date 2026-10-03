import { fireEvent, render, screen, within } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it, vi } from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { NavigationDrawerControl } from "../hooks/useNavigationDrawer"
import type { SessionBootstrapState } from "../hooks/useSessionBootstrap"
import { PortalHeader } from "./PortalHeader"

const authenticated: SessionBootstrapState = {
    status: "authenticated",
    bootstrap: sessionBootstrapFixture,
}

function drawerControl(open = false): NavigationDrawerControl {
    return {
        open,
        toggle: vi.fn(),
        close: vi.fn(),
        closeAndFocusToggle: vi.fn(),
    }
}

function renderHeader(
    state: SessionBootstrapState,
    drawer?: NavigationDrawerControl,
) {
    return render(
        <SessionContext.Provider value={{ state, reload: vi.fn() }}>
            <MemoryRouter>
                <PortalHeader drawer={drawer} />
            </MemoryRouter>
        </SessionContext.Provider>,
    )
}

describe("PortalHeader", () => {
    it("holds only branding, the drawer toggle, and the account menu", () => {
        renderHeader(authenticated, drawerControl())
        const header = screen.getByRole("banner")

        expect(
            within(header).getByRole("link", { name: "D&D AI Portal" }),
        ).toHaveAttribute("href", "/home")
        expect(
            within(header).getByRole("button", { name: /account menu/i }),
        ).toBeInTheDocument()
        expect(within(header).queryByRole("navigation")).not.toBeInTheDocument()
        expect(
            within(header).queryByRole("combobox", { name: "Appearance" }),
        ).not.toBeInTheDocument()
        expect(within(header).queryAllByRole("link")).toHaveLength(1)
    })

    it("renders the drawer toggle wired to the main navigation", () => {
        const drawer = drawerControl()
        renderHeader(authenticated, drawer)

        const toggle = screen.getByRole("button", { name: "Open navigation" })
        expect(toggle).toHaveAttribute("aria-controls", "main-navigation")
        expect(toggle).toHaveAttribute("aria-expanded", "false")

        fireEvent.click(toggle)

        expect(drawer.toggle).toHaveBeenCalledTimes(1)
    })

    it("labels the toggle for closing while the drawer is open", () => {
        renderHeader(authenticated, drawerControl(true))

        expect(
            screen.getByRole("button", { name: "Close navigation" }),
        ).toHaveAttribute("aria-expanded", "true")
    })

    it("has no drawer toggle outside the authenticated shell", () => {
        renderHeader(authenticated)

        expect(
            screen.queryByRole("button", { name: /navigation/i }),
        ).not.toBeInTheDocument()
    })

    it("shows an unlinked brand and no profile menu when signed out", () => {
        renderHeader({ status: "unauthenticated" })
        const header = screen.getByRole("banner")

        expect(within(header).queryByRole("link")).not.toBeInTheDocument()
        expect(
            within(header).queryByRole("button", { name: /account menu/i }),
        ).not.toBeInTheDocument()
        expect(within(header).getByText("D&D AI Portal")).toBeInTheDocument()
    })
})
