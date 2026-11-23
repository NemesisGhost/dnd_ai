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
import type { MockResponse, MockServer } from "./test/authoringHarness"
import { ThemeProvider } from "./themes/ThemeProvider"
import type { SessionBootstrap } from "./types/bootstrap"

// The creation route and the list through the real route table: the gate, the per-account key, and the rule that
// a one-time link cannot outlive or cross an account change.

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./hooks/useInvitationOnboardingStatus", () => ({
    useInvitationOnboardingStatus: () => ({ state: { status: "unavailable" }, retry: vi.fn() }),
}))
vi.mock("./api/userPreferences", () => ({
    recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const TOKEN = "activation-token-A"
const RESET_TOKEN = "reset-token-A"
const ADMIN_CAPS = ["accounts.manage", "system_roles.manage"]
const CREATED = {
    user_id: "user-9",
    login_name: "new.gm",
    raw_activation_token: TOKEN,
    expires_at: "2026-12-01T00:00:00Z",
}
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
        global_capabilities: ADMIN_CAPS,
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

function deferred() {
    let resolve: (value: MockResponse) => void = () => {}
    const promise = new Promise<MockResponse>((r) => (resolve = r))
    return { promise, resolve }
}

const adminCalls = () => server.calls.filter((call) => call.path.startsWith("/admin/accounts"))

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
})

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("/platform/accounts/new through the route table", () => {
    it("A1 mounts the creation page for an administrator and reads no account list", async () => {
        renderAt("/platform/accounts/new")
        expect(await screen.findByRole("form", { name: "Create account" })).toBeInTheDocument()
        expect(screen.getByRole("heading", { level: 1, name: "Create account" })).toBeInTheDocument()
        expect(adminCalls()).toEqual([])
    })

    it("A2 shows the denial and requests nothing without accounts.manage", async () => {
        setSession(authenticated({ global_capabilities: [] }))
        renderAt("/platform/accounts/new")
        expect(await screen.findByRole("heading", { name: "Access denied" })).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Create account" })).toBeNull()
        expect(adminCalls()).toEqual([])
    })

    it("A2 keeps the list route's gate and the legacy redirect", async () => {
        setSession(authenticated({ global_capabilities: [] }))
        const view = renderAt("/platform/accounts")
        expect(await screen.findByRole("heading", { name: "Access denied" })).toBeInTheDocument()
        view.unmount()

        setSession(authenticated())
        renderAt("/admin/accounts")
        expect(await screen.findByRole("heading", { name: "Platform accounts" })).toBeInTheDocument()
    })
})

describe("account changes (A19)", () => {
    it("A19 remounts the creation page for another account: no values, status or link carry over", async () => {
        server.on("POST", "/admin/accounts", { status: 422, body: {} })
        renderAt("/platform/accounts/new")
        fireEvent.change(await screen.findByLabelText("Login name"), { target: { value: "typed.by.a" } })
        fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Typed By A" } })
        fireEvent.click(screen.getByRole("button", { name: "Create account" }))
        await waitFor(() =>
            expect(screen.getByRole("status")).toHaveTextContent("The account could not be created."),
        )

        act(() => {
            setSession(
                authenticated({
                    user: { user_id: "user-B", display_name: "Account B" },
                    csrf_token: "csrf-B",
                }),
            )
        })
        await waitFor(() => expect(screen.getByLabelText("Login name")).toHaveValue(""))
        expect(screen.getByLabelText("Display name")).toHaveValue("")
        expect(screen.getByRole("status")).toHaveTextContent("")
    })

    it("A19 removes a shown activation link when the account changes", async () => {
        server.on("POST", "/admin/accounts", { status: 201, body: CREATED })
        renderAt("/platform/accounts/new")
        fireEvent.change(await screen.findByLabelText("Login name"), { target: { value: "new.gm" } })
        fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "New GM" } })
        fireEvent.click(screen.getByRole("button", { name: "Create account" }))
        await screen.findByLabelText("Activation link")

        act(() => {
            setSession(authenticated({ user: { user_id: "user-B", display_name: "Account B" } }))
        })
        await waitFor(() => expect(screen.queryByLabelText("Activation link")).toBeNull())
        expect(document.body.textContent).not.toContain(TOKEN)
        expect(await screen.findByRole("form", { name: "Create account" })).toBeInTheDocument()
    })

    it("A19 removes a shown activation link and shows the denial when accounts.manage is lost", async () => {
        server.on("POST", "/admin/accounts", { status: 201, body: CREATED })
        renderAt("/platform/accounts/new")
        fireEvent.change(await screen.findByLabelText("Login name"), { target: { value: "new.gm" } })
        fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "New GM" } })
        fireEvent.click(screen.getByRole("button", { name: "Create account" }))
        await screen.findByLabelText("Activation link")

        act(() => {
            setSession(authenticated({ global_capabilities: [] }))
        })
        expect(await screen.findByRole("heading", { name: "Access denied" })).toBeInTheDocument()
        expect(document.body.textContent).not.toContain(TOKEN)
    })

    it("A19 never shows a late create answer in another account's page", async () => {
        const gate = deferred()
        server.on("POST", "/admin/accounts", () => gate.promise)
        renderAt("/platform/accounts/new")
        fireEvent.change(await screen.findByLabelText("Login name"), { target: { value: "new.gm" } })
        fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "New GM" } })
        fireEvent.click(screen.getByRole("button", { name: "Create account" }))
        await waitFor(() => expect(server.callsTo("POST", "/admin/accounts")).toHaveLength(1))

        act(() => {
            setSession(authenticated({ user: { user_id: "user-B", display_name: "Account B" } }))
        })
        await waitFor(() => expect(screen.getByLabelText("Login name")).toHaveValue(""))
        await act(async () => gate.resolve({ status: 201, body: CREATED }))
        await act(async () => {
            await new Promise((resolve) => setTimeout(resolve, 25))
        })

        expect(screen.queryByLabelText("Activation link")).toBeNull()
        expect(document.body.textContent).not.toContain(TOKEN)
        expect(screen.getByRole("form", { name: "Create account" })).toBeInTheDocument()
        expect(server.callsTo("POST", "/admin/accounts")).toHaveLength(1)
    })

    it("A19 removes a shown reset link when the account changes, and ignores a late reset answer", async () => {
        server.on("POST", "/admin/accounts/user-1/password-reset", {
            status: 200,
            body: { user_id: "user-1", raw_reset_token: RESET_TOKEN, expires_at: "2026-12-01T00:00:00Z" },
        })
        renderAt("/platform/accounts")
        await screen.findByText("Alice Example")
        fireEvent.click(screen.getByRole("button", { name: "Issue password reset" }))
        await screen.findByLabelText("Password-reset link")

        act(() => {
            setSession(authenticated({ user: { user_id: "user-B", display_name: "Account B" } }))
        })
        await screen.findByText("Alice Example")
        expect(screen.queryByLabelText("Password-reset link")).toBeNull()
        expect(document.body.textContent).not.toContain(RESET_TOKEN)

        // A reset still in flight when the account changes is dropped.
        const gate = deferred()
        server.on("POST", "/admin/accounts/user-1/password-reset", () => gate.promise)
        fireEvent.click(screen.getByRole("button", { name: "Issue password reset" }))
        await waitFor(() =>
            expect(server.callsTo("POST", "/admin/accounts/user-1/password-reset")).toHaveLength(2),
        )
        act(() => {
            setSession(authenticated({ user: { user_id: "user-C", display_name: "Account C" } }))
        })
        await screen.findByText("Alice Example")
        await act(async () =>
            gate.resolve({
                status: 200,
                body: { user_id: "user-1", raw_reset_token: "late-reset", expires_at: "2026-12-01T00:00:00Z" },
            }),
        )
        await act(async () => {
            await new Promise((resolve) => setTimeout(resolve, 25))
        })
        expect(screen.queryByLabelText("Password-reset link")).toBeNull()
        expect(document.body.textContent).not.toContain("late-reset")
    })
})
