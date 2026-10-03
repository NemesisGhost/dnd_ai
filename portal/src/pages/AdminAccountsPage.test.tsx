import { render, screen } from "@testing-library/react"
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
        query: "",
        setQuery: vi.fn(),
        retry: vi.fn(),
        loadMore: vi.fn(),
    }),
}))

vi.mock("../components/CreateAccountPanel", () => ({
    CreateAccountPanel: () => <div>create-account-panel</div>,
}))

vi.mock("../components/AccountLifecycleActions", () => ({
    AccountLifecycleActions: ({ account }: { account: { user_id: string } }) => (
        <div>lifecycle-actions-{account.user_id}</div>
    ),
}))

describe("AdminAccountsPage", () => {
    it("renders a not-found placeholder for a non-administrator bootstrap, presentation only", () => {
        render(
            <AdminAccountsPage
                bootstrap={{ ...sessionBootstrapFixture, is_platform_administrator: false }}
            />,
        )
        expect(screen.getByRole("heading", { name: "Page not found" })).toBeInTheDocument()
        expect(screen.queryByText("create-account-panel")).not.toBeInTheDocument()
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
                    has_local_credential: true,
                    has_outstanding_activation: false,
                    last_login_at: null,
                    active_session_count: 2,
                },
            ],
            nextCursor: null,
        }

        render(
            <AdminAccountsPage
                bootstrap={{ ...sessionBootstrapFixture, is_platform_administrator: true }}
            />,
        )

        expect(screen.getByRole("heading", { name: "Platform accounts" })).toBeInTheDocument()
        expect(screen.getByText("create-account-panel")).toBeInTheDocument()
        expect(screen.getByText("GM Two")).toBeInTheDocument()
        expect(screen.getByLabelText("Platform administrator")).toBeInTheDocument()
        expect(screen.getByText("lifecycle-actions-user-1")).toBeInTheDocument()
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
                    has_local_credential: true,
                    has_outstanding_activation: false,
                    last_login_at: null,
                    active_session_count: 0,
                },
            ],
            nextCursor: "cursor-1",
        }

        render(
            <AdminAccountsPage
                bootstrap={{ ...sessionBootstrapFixture, is_platform_administrator: true }}
            />,
        )

        expect(screen.getAllByLabelText("Platform administrator")).toHaveLength(1)
        expect(screen.queryByRole("columnheader", { name: /admin/i })).not.toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Load more" })).toBeInTheDocument()
    })
})
