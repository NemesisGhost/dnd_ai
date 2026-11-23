import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { useSyncExternalStore } from "react"
import { RouterProvider, createMemoryRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import App from "./App"
import { RouteSessionProvider } from "./context/RouteSessionProvider"
import { sessionBootstrapFixture } from "./fixtures/sessionBootstrap"
import { useSessionBootstrap } from "./hooks/useSessionBootstrap"
import type { SessionBootstrapState } from "./hooks/useSessionBootstrap"
import { installMockServer } from "./test/authoringHarness"
import type { MockServer } from "./test/authoringHarness"
import { ThemeProvider } from "./themes/ThemeProvider"
import type { SessionBootstrap } from "./types/bootstrap"

// The staged roles panel through the real route table: it cannot outlive or cross an account change, and a
// loss of capability removes it and its draft, including while changes are staged and a reset link is shown.

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./hooks/useInvitationOnboardingStatus", () => ({
    useInvitationOnboardingStatus: () => ({ state: { status: "unavailable" }, retry: vi.fn() }),
}))
vi.mock("./api/userPreferences", () => ({
    recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const RESET_TOKEN = "reset-token-roles"
const MANAGE = ["accounts.manage", "system_roles.manage"]
const LIST = {
    items: [
        {
            user_id: "user-1",
            display_name: "Alice Example",
            login_name: "user-1",
            lifecycle_status_code: "active",
            is_platform_administrator: false,
            system_roles: ["player"],
            has_local_credential: true,
            has_outstanding_activation: false,
            last_login_at: null,
            active_session_count: 1,
        },
    ],
    next_cursor: null,
}

const authenticated = (overrides: Partial<SessionBootstrap> = {}): SessionBootstrapState => ({
    status: "authenticated",
    bootstrap: {
        ...sessionBootstrapFixture,
        csrf_token: "csrf-A",
        global_capabilities: MANAGE,
        ...overrides,
    },
})

const listeners = new Set<() => void>()
let sessionState: SessionBootstrapState
let server: MockServer

function setSession(state: SessionBootstrapState) {
    sessionState = state
    listeners.forEach((listener) => listener())
}

function renderAt(entry: string) {
    const router = createMemoryRouter(
        [
            {
                path: "*",
                element: (
                    <ThemeProvider>
                        <RouteSessionProvider>
                            <App />
                        </RouteSessionProvider>
                    </ThemeProvider>
                ),
            },
        ],
        { initialEntries: [entry] },
    )
    return { router, ...render(<RouterProvider router={router} />) }
}

const writes = () => server.calls.filter((call) => call.method !== "GET")

// Opens Alice's roles, stages Game master, and shows a reset link, so a draft and a one-time link both exist.
async function stageWithResetLink() {
    renderAt("/platform/accounts")
    await screen.findByText("Alice Example")
    fireEvent.click(screen.getByRole("button", { name: "Edit roles for Alice Example" }))
    fireEvent.click(await screen.findByRole("checkbox", { name: "Game master" }))
    fireEvent.click(screen.getByRole("button", { name: "Issue password reset" }))
    await screen.findByLabelText("Password-reset link")
    await screen.findByText("Alice Example")
}

beforeEach(() => {
    listeners.clear()
    setSession(authenticated())
    vi.mocked(useSessionBootstrap).mockImplementation(() => ({
        state: useSyncExternalStore(
            (listener) => {
                listeners.add(listener)
                return () => listeners.delete(listener)
            },
            () => sessionState,
        ),
        reload: vi.fn(),
        refresh: vi.fn(),
    }))
    server = installMockServer()
    server.on("GET", /^\/admin\/accounts(\?|$)/, { body: LIST })
    server.on("POST", "/admin/accounts/user-1/password-reset", {
        status: 200,
        body: { user_id: "user-1", raw_reset_token: RESET_TOKEN, expires_at: "2026-12-01T00:00:00Z" },
    })
})

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("roles panel isolation (B9)", () => {
    it("drops the panel, the draft and the reset link when the signed-in account changes", async () => {
        await stageWithResetLink()
        expect(screen.getByRole("checkbox", { name: "Game master" })).toBeChecked()

        act(() => {
            setSession(authenticated({ user: { user_id: "user-B", display_name: "Account B" }, csrf_token: "csrf-B" }))
        })

        await waitFor(() => expect(screen.queryByRole("heading", { name: /System roles for/ })).toBeNull())
        expect(screen.queryByLabelText("Password-reset link")).toBeNull()
        expect(document.body.textContent).not.toContain(RESET_TOKEN)
        expect(screen.queryByText("Changes not saved yet")).toBeNull()
        // The new account's page starts clean: opening Alice's roles shows no earlier draft.
        await screen.findByText("Alice Example")
        fireEvent.click(screen.getByRole("button", { name: "Edit roles for Alice Example" }))
        await screen.findByRole("heading", { name: "System roles for Alice Example" })
        expect(screen.getByRole("checkbox", { name: "Game master" })).not.toBeChecked()
        expect(writes().map((call) => call.path)).toEqual(["/admin/accounts/user-1/password-reset"])
    })

    it("removes the panel and its draft when system_roles.manage is lost, and does not restore it", async () => {
        await stageWithResetLink()

        act(() => {
            setSession(authenticated({ global_capabilities: ["accounts.manage"] }))
        })
        await waitFor(() => expect(screen.queryByRole("heading", { name: /System roles for/ })).toBeNull())
        expect(screen.queryByRole("button", { name: /Edit roles/ })).toBeNull()
        expect(screen.queryByText("Changes not saved yet")).toBeNull()
        // S01's reset link is a separate reason and stays while the page does.
        expect(screen.getByLabelText("Password-reset link")).toBeInTheDocument()

        act(() => {
            setSession(authenticated())
        })
        await screen.findByRole("button", { name: "Edit roles for Alice Example" })
        expect(screen.queryByRole("heading", { name: /System roles for/ })).toBeNull()
        expect(screen.queryByText("Changes not saved yet")).toBeNull()
    })

    it("no longer asks about unsaved role changes once the capability is lost, but still asks about the reset link", async () => {
        const { router } = renderAt("/platform/accounts")
        await screen.findByText("Alice Example")
        fireEvent.click(screen.getByRole("button", { name: "Edit roles for Alice Example" }))
        fireEvent.click(await screen.findByRole("checkbox", { name: "Game master" }))

        act(() => {
            setSession(authenticated({ global_capabilities: ["accounts.manage"] }))
        })
        await waitFor(() => expect(screen.queryByRole("heading", { name: /System roles for/ })).toBeNull())

        await act(async () => {
            await router.navigate("/home")
        })
        expect(screen.queryByRole("heading", { name: "Discard unsaved role changes?", hidden: true })).toBeNull()
        expect(router.state.location.pathname).not.toBe("/platform/accounts")
    })

    it("shows the denial and removes everything when accounts.manage is lost while changes are staged", async () => {
        await stageWithResetLink()

        act(() => {
            setSession(authenticated({ global_capabilities: [] }))
        })
        expect(await screen.findByRole("heading", { name: "Access denied" })).toBeInTheDocument()
        expect(screen.queryByRole("checkbox", { name: "Game master" })).toBeNull()
        expect(document.body.textContent).not.toContain(RESET_TOKEN)
        expect(writes().map((call) => call.path)).toEqual(["/admin/accounts/user-1/password-reset"])
    })
})
