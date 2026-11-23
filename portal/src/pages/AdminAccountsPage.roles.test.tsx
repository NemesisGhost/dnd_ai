import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { Link } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { MockServer } from "../test/authoringHarness"
import { useAuthenticatedSession } from "../layouts/useAuthenticatedSession"
import { AdminAccountsPage } from "./AdminAccountsPage"
import type { PlatformAccount } from "../types/platformAccounts"

// Real list page, real roles panel and real hooks; only the network (a stubbed fetch) and the session are
// faked. A sidebar link sits beside the page so a departure by something other than its own controls is covered.

const MANAGE = ["accounts.manage", "system_roles.manage"]
const ADMIN = bootstrapWith({ global_capabilities: MANAGE })
const GET_ACCOUNTS = /^\/admin\/accounts(\?|$)/

function account(id: string, name: string, roles: string[] = ["player"]): PlatformAccount {
    return {
        user_id: id,
        display_name: name,
        login_name: id,
        lifecycle_status_code: "active",
        is_platform_administrator: roles.includes("admin"),
        system_roles: roles,
        has_local_credential: true,
        has_outstanding_activation: false,
        last_login_at: null,
        active_session_count: 1,
    }
}

let items: PlatformAccount[]
let server: MockServer

function ListRoute() {
    const { bootstrap } = useAuthenticatedSession()
    return (
        <>
            <nav>
                <Link to="/home">Sidebar home</Link>
            </nav>
            <AdminAccountsPage bootstrap={bootstrap} />
        </>
    )
}

function setup(bootstrap = ADMIN) {
    server = installMockServer()
    server.on("GET", GET_ACCOUNTS, () => ({ body: { items, next_cursor: null } }))
    return renderAuthoringRoutes({
        initialEntry: "/platform/accounts",
        bootstrap,
        routes: [
            { path: "/platform/accounts", element: <ListRoute /> },
            { path: "/home", element: <p>Home page</p> },
        ],
    })
}

const writes = () => server.calls.filter((call) => call.method !== "GET")
const editButton = (name: string) => screen.getByRole("button", { name: `Edit roles for ${name}` })
const heading = (name: string) => screen.getByRole("heading", { level: 2, name })
const box = (name: string) => screen.getByRole("checkbox", { name })
const dialogHeading = (name: string) => screen.findByRole("heading", { name, hidden: true })

async function openRoles(name: string) {
    await screen.findByText(name)
    fireEvent.click(editButton(name))
    await screen.findByRole("heading", { level: 2, name: `System roles for ${name}` })
}

beforeEach(() => {
    items = [account("user-1", "Alice Example"), account("user-2", "Bob Example")]
})

afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
})

describe("B1-B3 staging, local cancel and the panel's place", () => {
    it("B1 stages changes locally and lists them without sending anything", async () => {
        setup()
        await openRoles("Alice Example")

        fireEvent.click(box("Game master"))
        fireEvent.click(box("Player"))

        expect(screen.getByText("Changes not saved yet")).toBeInTheDocument()
        const list = screen.getByRole("list", { name: "Changes not saved yet" })
        expect(within(list).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
            "Add Game master",
            "Remove Player",
        ])
        expect(writes()).toEqual([])
        // T02 adds the explicit Save (T01 had none); ticking alone still sends nothing.
        expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled()
    })

    it("B2 Cancel restores the draft, closes the panel, sends nothing and returns focus to the row button", async () => {
        setup()
        await openRoles("Alice Example")
        fireEvent.click(box("Game master"))
        fireEvent.click(box("Player"))

        const cancel = screen.getByRole("button", { name: "Cancel" })
        cancel.focus()
        fireEvent.click(cancel)

        expect(screen.queryByRole("heading", { level: 2, name: "System roles for Alice Example" })).toBeNull()
        expect(writes()).toEqual([])
        const row = screen.getByRole("row", { name: /Alice Example/ })
        expect(within(row).getByText("player")).toBeInTheDocument()
        await waitFor(() => expect(editButton("Alice Example")).toHaveFocus())

        // Reopening starts from the baseline, not the abandoned draft.
        fireEvent.click(editButton("Alice Example"))
        await screen.findByRole("heading", { level: 2, name: "System roles for Alice Example" })
        expect(box("Player")).toBeChecked()
        expect(box("Game master")).not.toBeChecked()
        expect(screen.getByText("No changes")).toBeInTheDocument()
    })

    it("B3 focuses the heading, renders the panel outside the table and keeps it across reloads", async () => {
        setup()
        await openRoles("Alice Example")
        await waitFor(() => expect(heading("System roles for Alice Example")).toHaveFocus())
        expect(screen.getByRole("table").contains(heading("System roles for Alice Example"))).toBe(false)

        fireEvent.click(box("Game master"))

        // A search change reloads the list.
        const before = server.callsTo("GET", GET_ACCOUNTS).length
        fireEvent.change(screen.getByLabelText(/Search by display name/), { target: { value: "ali" } })
        await waitFor(() => expect(server.callsTo("GET", GET_ACCOUNTS).length).toBeGreaterThan(before))
        await screen.findByText("Alice Example")
        expect(heading("System roles for Alice Example")).toBeInTheDocument()
        expect(box("Game master")).toBeChecked()

        // A lifecycle action's reload.
        server.on("POST", "/admin/accounts/user-1/password-reset", {
            status: 200,
            body: { user_id: "user-1", raw_reset_token: "tok", expires_at: "2026-10-01T00:00:00Z" },
        })
        const afterSearch = server.callsTo("GET", GET_ACCOUNTS).length
        fireEvent.click(screen.getAllByRole("button", { name: "Issue password reset" })[0]!)
        await screen.findByLabelText("Password-reset link")
        await waitFor(() => expect(server.callsTo("GET", GET_ACCOUNTS).length).toBeGreaterThan(afterSearch))
        await screen.findByText("Alice Example")
        expect(heading("System roles for Alice Example")).toBeInTheDocument()
        expect(box("Game master")).toBeChecked()
        expect(writes().map((call) => call.path)).toEqual(["/admin/accounts/user-1/password-reset"])
    })
})

describe("B4-B7 panel content and gating", () => {
    it("B4 gates a new Administrator grant but never the removal of a held one", async () => {
        items = [account("user-1", "Alice Example"), account("user-3", "Carol Admin", ["admin"])]
        const view = setup()
        await openRoles("Alice Example")
        expect(box("Administrator")).toBeDisabled()
        expect(
            screen.getByText(/Granting Administrator is done by the operator script on this deployment\./),
        ).toBeInTheDocument()
        expect(screen.getByText(/A system role never grants access to any campaign or world\./)).toBeInTheDocument()

        fireEvent.click(screen.getByRole("button", { name: "Close" }))
        await openRoles("Carol Admin")
        expect(box("Administrator")).toBeEnabled()
        fireEvent.click(box("Administrator"))
        expect(screen.getByRole("list", { name: "Changes not saved yet" })).toHaveTextContent("Remove Administrator")
        view.unmount()

        setup(bootstrapWith({ global_capabilities: [...MANAGE, "system_roles.grant_admin"] }))
        await openRoles("Alice Example")
        expect(box("Administrator")).toBeEnabled()
        fireEvent.click(box("Administrator"))
        expect(screen.getByRole("list", { name: "Changes not saved yet" })).toHaveTextContent("Add Administrator")
        expect(screen.queryByText(/operator script/)).toBeNull()
    })

    it("B5 offers no Edit roles button and no panel without system_roles.manage", async () => {
        setup(bootstrapWith({ global_capabilities: ["accounts.manage"] }))
        await screen.findByText("Alice Example")
        expect(screen.queryByRole("button", { name: /Edit roles/ })).toBeNull()
        expect(screen.queryByRole("heading", { name: /System roles for/ })).toBeNull()
    })

    it("B6 disables other rows while dirty, with the reason, and replaces a clean panel", async () => {
        setup()
        await openRoles("Alice Example")
        fireEvent.click(box("Game master"))

        const bob = editButton("Bob Example")
        expect(bob).toBeDisabled()
        const reason = "Save or cancel these changes before editing another account."
        expect(screen.getByText(reason)).toBeInTheDocument()
        expect(bob).toHaveAccessibleDescription(reason)
        expect(editButton("Alice Example")).toBeEnabled()

        fireEvent.click(box("Game master"))
        expect(bob).toBeEnabled()
        fireEvent.click(bob)
        await screen.findByRole("heading", { level: 2, name: "System roles for Bob Example" })
        expect(screen.queryByRole("heading", { name: "System roles for Alice Example" })).toBeNull()
        await waitFor(() => expect(heading("System roles for Bob Example")).toHaveFocus())
    })

    it("B7 unticking back to the baseline shows No changes and releases the guard", async () => {
        setup()
        await openRoles("Alice Example")
        fireEvent.click(box("Game master"))
        expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument()
        fireEvent.click(box("Game master"))

        expect(screen.getByText("No changes")).toBeInTheDocument()
        expect(screen.queryByText("Changes not saved yet")).toBeNull()
        expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull()

        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        expect(await screen.findByText("Home page")).toBeInTheDocument()
    })
})

describe("B8 one page guard", () => {
    it("asks about unsaved role changes; Stay keeps the draft, Leave departs, typing asks nothing", async () => {
        setup()
        await openRoles("Alice Example")
        fireEvent.click(box("Game master"))

        fireEvent.change(screen.getByLabelText(/Search by display name/), { target: { value: "a" } })
        expect(screen.queryByRole("heading", { name: "Discard unsaved role changes?", hidden: true })).toBeNull()

        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        expect(await dialogHeading("Discard unsaved role changes?")).toBeInTheDocument()
        expect(screen.getByText("Your changes to Alice Example's system roles have not been saved.")).toBeInTheDocument()

        fireEvent.click(screen.getByRole("button", { name: "Stay", hidden: true }))
        expect(screen.queryByText("Home page")).toBeNull()
        expect(box("Game master")).toBeChecked()

        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        fireEvent.click(screen.getByRole("button", { name: "Leave", hidden: true }))
        expect(await screen.findByText("Home page")).toBeInTheDocument()
        expect(writes()).toEqual([])
    })

    it("shows one dialog naming both reasons, with no router warning, when a reset link is also shown", async () => {
        const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
        const error = vi.spyOn(console, "error").mockImplementation(() => {})
        setup()
        server.on("POST", "/admin/accounts/user-2/password-reset", {
            status: 200,
            body: { user_id: "user-2", raw_reset_token: "tok", expires_at: "2026-10-01T00:00:00Z" },
        })
        await openRoles("Alice Example")
        fireEvent.click(box("Game master"))
        fireEvent.click(screen.getAllByRole("button", { name: "Issue password reset" })[1]!)
        await screen.findByLabelText("Password-reset link")
        await screen.findByText("Bob Example")

        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        expect(await dialogHeading("Discard unsaved role changes?")).toBeInTheDocument()
        expect(
            screen.getByText(
                "Your changes to Alice Example's system roles have not been saved. The password-reset link shown on this page will also be lost.",
            ),
        ).toBeInTheDocument()
        expect(screen.getAllByRole("dialog", { hidden: true }).filter((d) => d.hasAttribute("open"))).toHaveLength(1)
        expect(warn).not.toHaveBeenCalled()
        expect(error).not.toHaveBeenCalled()
    })

    it("keeps S01's reset-link-only dialog unchanged", async () => {
        setup()
        server.on("POST", "/admin/accounts/user-1/password-reset", {
            status: 200,
            body: { user_id: "user-1", raw_reset_token: "tok", expires_at: "2026-10-01T00:00:00Z" },
        })
        await screen.findByText("Alice Example")
        fireEvent.click(screen.getAllByRole("button", { name: "Issue password reset" })[0]!)
        await screen.findByLabelText("Password-reset link")
        await screen.findByText("Alice Example")

        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        expect(await dialogHeading("Leave without the password-reset link?")).toBeInTheDocument()
        expect(screen.getByText("It is shown once and cannot be shown again.")).toBeInTheDocument()
    })
})

describe("B10 baseline while open", () => {
    it("follows the latest list roles while clean and keeps its baseline while dirty", async () => {
        setup()
        await openRoles("Alice Example")
        expect(box("Player")).toBeChecked()

        // A reload (a search change and back) returns Alice with a new role: the clean panel follows it.
        items = [account("user-1", "Alice Example", ["player", "gm"]), account("user-2", "Bob Example")]
        fireEvent.change(screen.getByLabelText(/Search by display name/), { target: { value: "x" } })
        await screen.findByText("player, gm")
        expect(box("Game master")).toBeChecked()

        // Dirty: later list changes do not move the baseline.
        fireEvent.click(box("Observer"))
        items = [account("user-1", "Alice Example", ["observer"]), account("user-2", "Bob Example")]
        fireEvent.change(screen.getByLabelText(/Search by display name/), { target: { value: "y" } })
        await screen.findByText("observer", { selector: "td" })
        expect(box("Game master")).toBeChecked()
        expect(box("Player")).toBeChecked()
        expect(screen.getByRole("list", { name: "Changes not saved yet" })).toHaveTextContent("Add Observer")
    })
})

describe("focus on close", () => {
    it("falls back to the search field when the row's button is gone", async () => {
        setup()
        await openRoles("Alice Example")
        items = [account("user-2", "Bob Example")]
        fireEvent.change(screen.getByLabelText(/Search by display name/), { target: { value: "bob" } })
        await waitFor(() => expect(screen.queryByText("Alice Example", { selector: ".admin-accounts__name" })).toBeNull())
        await screen.findByText("Bob Example")

        fireEvent.click(screen.getByRole("button", { name: "Close" }))
        await waitFor(() => expect(screen.getByLabelText(/Search by display name/)).toHaveFocus())
    })

    it("does not take focus back from a control the person moved to", async () => {
        setup()
        await openRoles("Alice Example")
        const close = screen.getByRole("button", { name: "Close" })
        const search = screen.getByLabelText(/Search by display name/)
        close.focus()
        search.focus()
        await act(async () => {
            fireEvent.click(close)
        })
        expect(screen.queryByRole("heading", { name: "System roles for Alice Example" })).toBeNull()
        expect(search).toHaveFocus()
    })

    it("a list reload after opening does not steal focus the person moved elsewhere", async () => {
        setup()
        await openRoles("Alice Example")
        const search = screen.getByLabelText(/Search by display name/)
        search.focus()
        fireEvent.change(search, { target: { value: "a" } })
        await screen.findByText("Alice Example")
        expect(search).toHaveFocus()
    })
})
