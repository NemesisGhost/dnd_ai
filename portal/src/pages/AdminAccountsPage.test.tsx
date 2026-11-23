import { render, screen } from "@testing-library/react"
import { RouterProvider, createMemoryRouter } from "react-router"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { AdminAccountsPage } from "./AdminAccountsPage"
import type { PlatformAccountsState } from "../hooks/usePlatformAccounts"

const { stateRef } = vi.hoisted(() => ({
    stateRef: { current: { status: "loading" } as PlatformAccountsState },
}))

vi.mock("../hooks/usePlatformAccounts", () => ({
    usePlatformAccounts: () => ({
        state: stateRef.current,
        retry: vi.fn(),
        loadMore: vi.fn(),
    }),
}))

// The page reads the session for saving role changes (T02); nothing here saves.
vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: { status: "loading" }, reload: vi.fn(), refresh: vi.fn() }),
}))

vi.mock("../components/AccountLifecycleActions", () => ({
    AccountLifecycleActions: ({ account }: { account: { user_id: string } }) => (
        <div>lifecycle-actions-{account.user_id}</div>
    ),
}))

// A data router, because the page guards a shown reset link with useBlocker.
function renderInRouter(element: ReactNode) {
    const router = createMemoryRouter([{ path: "*", element }], { initialEntries: ["/platform/accounts"] })
    return render(<RouterProvider router={router} />)
}

describe("AdminAccountsPage", () => {
    it("renders an explicit denial for a non-administrator bootstrap, presentation only", () => {
        renderInRouter(
            <AdminAccountsPage bootstrap={{ ...sessionBootstrapFixture, global_capabilities: [] }} />,
        )
        expect(screen.getByRole("heading", { name: "Access denied" })).toBeInTheDocument()
        expect(screen.queryByRole("link", { name: "Create account" })).not.toBeInTheDocument()
    })

    it("renders the account table for an administrator", () => {
        stateRef.current = {
            status: "success",
            items: [
                {
                    user_id: "user-1",
                    display_name: "GM Two",
                    login_name: "gm2",
                    lifecycle_status_code: "active",
                    is_platform_administrator: true,
                    system_roles: ["admin", "gm"],
                    has_local_credential: true,
                    has_outstanding_activation: false,
                    last_login_at: null,
                    active_session_count: 2,
                },
            ],
            nextCursor: null,
        }

        renderInRouter(
            <AdminAccountsPage
                bootstrap={{ ...sessionBootstrapFixture, global_capabilities: ["accounts.manage", "system_roles.manage"] }}
            />,
        )

        expect(screen.getByRole("heading", { name: "Platform accounts" })).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Create account" })).toHaveAttribute(
            "href",
            "/platform/accounts/new",
        )
        expect(screen.queryByRole("form", { name: "Create account" })).not.toBeInTheDocument()
        expect(screen.getByText("GM Two")).toBeInTheDocument()
        expect(screen.getByLabelText("Platform administrator")).toBeInTheDocument()
        expect(screen.getByText("lifecycle-actions-user-1")).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Edit roles for GM Two" })).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument()
    })

    it("shows a badge only on administrator rows, with no dedicated column", () => {
        stateRef.current = {
            status: "success",
            items: [
                {
                    user_id: "user-1",
                    display_name: "Admin Row",
                    login_name: "admin.row",
                    lifecycle_status_code: "active",
                    is_platform_administrator: true,
                    system_roles: ["admin", "gm"],
                    has_local_credential: true,
                    has_outstanding_activation: false,
                    last_login_at: null,
                    active_session_count: 0,
                },
                {
                    user_id: "user-2",
                    display_name: "Plain Row",
                    login_name: "plain.row",
                    lifecycle_status_code: "active",
                    is_platform_administrator: false,
                    system_roles: ["player"],
                    has_local_credential: true,
                    has_outstanding_activation: false,
                    last_login_at: null,
                    active_session_count: 0,
                },
            ],
            nextCursor: "cursor-1",
        }

        renderInRouter(
            <AdminAccountsPage
                bootstrap={{ ...sessionBootstrapFixture, global_capabilities: ["accounts.manage", "system_roles.manage"] }}
            />,
        )

        expect(screen.getAllByLabelText("Platform administrator")).toHaveLength(1)
        expect(screen.queryByRole("columnheader", { name: /admin/i })).not.toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Load more" })).toBeInTheDocument()
    })
})
