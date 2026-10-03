import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it, vi } from "vitest"
import { AccountNavLink } from "./AccountNavLink"

const { sessionStateRef } = vi.hoisted(() => ({
    sessionStateRef: { current: { status: "unauthenticated" as string } },
}))

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: sessionStateRef.current, reload: vi.fn() }),
}))

describe("AccountNavLink", () => {
    it("renders nothing when unauthenticated", () => {
        sessionStateRef.current = { status: "unauthenticated" }
        render(<AccountNavLink />, { wrapper: MemoryRouter })
        expect(screen.queryByRole("link")).not.toBeInTheDocument()
    })

    it("renders the link for any authenticated user", () => {
        sessionStateRef.current = { status: "authenticated" } as never
        render(<AccountNavLink />, { wrapper: MemoryRouter })
        expect(screen.getByRole("link", { name: "Your account" })).toHaveAttribute(
            "href",
            "/account",
        )
    })
})
