import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it, vi } from "vitest"
import { AdminAccountsNavLink } from "./AdminAccountsNavLink"

const { sessionStateRef } = vi.hoisted(() => ({
    sessionStateRef: { current: { status: "unauthenticated" as string } },
}))

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: sessionStateRef.current, reload: vi.fn() }),
}))

describe("AdminAccountsNavLink", () => {
    it("renders nothing when unauthenticated", () => {
        sessionStateRef.current = { status: "unauthenticated" }
        render(<AdminAccountsNavLink />, { wrapper: MemoryRouter })
        expect(screen.queryByRole("link")).not.toBeInTheDocument()
    })

    it("renders nothing for an authenticated non-administrator", () => {
        sessionStateRef.current = {
            status: "authenticated",
            bootstrap: { is_platform_administrator: false },
        } as never
        render(<AdminAccountsNavLink />, { wrapper: MemoryRouter })
        expect(screen.queryByRole("link")).not.toBeInTheDocument()
    })

    it("renders the link for an authenticated administrator", () => {
        sessionStateRef.current = {
            status: "authenticated",
            bootstrap: { is_platform_administrator: true },
        } as never
        render(<AdminAccountsNavLink />, { wrapper: MemoryRouter })
        expect(screen.getByRole("link", { name: "Platform accounts" })).toHaveAttribute(
            "href",
            "/admin/accounts",
        )
    })
})
