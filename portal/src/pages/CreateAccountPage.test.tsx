import { act, fireEvent, screen, waitFor } from "@testing-library/react"
import { Link } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
    TEST_CSRF,
    bootstrapWith,
    installMockServer,
    renderAuthoringRoutes,
} from "../test/authoringHarness"
import type { FetchCall, MockResponse } from "../test/authoringHarness"
import { useAuthenticatedSession } from "../layouts/useAuthenticatedSession"
import { AdminAccountsPage } from "./AdminAccountsPage"
import { CreateAccountPage } from "./CreateAccountPage"
import type { PlatformAccount } from "../types/platformAccounts"

// Real list page, real creation page, real hooks; only the network (a stubbed fetch) and the session are
// faked. The routes sit beside a sidebar link so a departure by something other than the page's own controls
// is covered.

const ADMIN = bootstrapWith({ global_capabilities: ["accounts.manage", "system_roles.manage"] })
const GET_ACCOUNTS = /^\/admin\/accounts(\?|$)/
const TOKEN = "raw-token-42"

function account(id: string, name: string): PlatformAccount {
    return {
        user_id: id,
        display_name: name,
        login_name: id,
        lifecycle_status_code: "active",
        is_platform_administrator: false,
        system_roles: ["player"],
        has_local_credential: true,
        has_outstanding_activation: false,
        last_login_at: null,
        active_session_count: 1,
    }
}

const LIST = { items: [account("user-1", "Alice Example")], next_cursor: null }
const CREATED = {
    user_id: "user-9",
    login_name: "new.gm",
    raw_activation_token: TOKEN,
    expires_at: "2026-12-01T00:00:00Z",
}

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

function CreateRoute() {
    const { bootstrap } = useAuthenticatedSession()
    return (
        <>
            <nav>
                <Link to="/home">Sidebar home</Link>
            </nav>
            <CreateAccountPage bootstrap={bootstrap} />
        </>
    )
}

type Entry = string | { pathname: string; search?: string; state?: unknown }

function setup(
    options: {
        entry?: Entry
        bootstrap?: ReturnType<typeof bootstrapWith>
        post?: MockResponse | ((call: FetchCall) => MockResponse | Promise<MockResponse>)
    } = {},
) {
    const server = installMockServer()
    server.on("GET", GET_ACCOUNTS, { body: LIST })
    server.on("POST", "/admin/accounts", options.post ?? { status: 201, body: CREATED })
    const rendered = renderAuthoringRoutes({
        initialEntry: options.entry ?? "/platform/accounts",
        bootstrap: options.bootstrap ?? ADMIN,
        routes: [
            { path: "/platform/accounts", element: <ListRoute /> },
            { path: "/platform/accounts/new", element: <CreateRoute /> },
            { path: "/home", element: <p>Home page</p> },
        ],
    })
    return { server, ...rendered }
}

const h1 = (name: string) => screen.getByRole("heading", { level: 1, name })
const postCalls = (server: ReturnType<typeof installMockServer>) =>
    server.callsTo("POST", "/admin/accounts")
const listCalls = (server: ReturnType<typeof installMockServer>) =>
    server.callsTo("GET", GET_ACCOUNTS)

// A PUSH arrival through the list's own link, waiting for the heading to take focus before anything is typed.
async function openCreation() {
    await screen.findByText("Alice Example")
    fireEvent.click(screen.getByRole("link", { name: "Create account" }))
    await screen.findByRole("form", { name: "Create account" })
    await waitFor(() => expect(h1("Create account")).toHaveFocus())
}

function fill(login: string, display: string) {
    fireEvent.change(screen.getByLabelText("Login name"), { target: { value: login } })
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: display } })
}

const submitButton = () => screen.getByRole("button", { name: /^(Create account|Creating…)$/ })

function press() {
    fireEvent.click(submitButton())
}

function deferred() {
    let resolve: (value: MockResponse) => void = () => {}
    const promise = new Promise<MockResponse>((r) => (resolve = r))
    return { promise, resolve }
}

function statusTexts(): string[] {
    return screen.queryAllByRole("status").map((node) => node.textContent ?? "")
}

async function settle() {
    await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 25))
    })
}

let setItem: ReturnType<typeof vi.spyOn>

beforeEach(() => {
    setItem = vi.spyOn(Storage.prototype, "setItem")
})

afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
})

describe("the creation route and the list (A1–A3)", () => {
    it("A1 shows the creation form with Player chosen and reads no list", async () => {
        const { server } = setup({ entry: "/platform/accounts/new" })
        expect(await screen.findByRole("form", { name: "Create account" })).toBeInTheDocument()
        expect(h1("Create account")).toBeInTheDocument()
        expect(screen.getByRole("checkbox", { name: "Player" })).toBeChecked()
        expect(screen.getByRole("checkbox", { name: "Game master" })).not.toBeChecked()
        expect(listCalls(server)).toHaveLength(0)
    })

    it("A2 shows the denial and sends nothing without accounts.manage", async () => {
        const { server } = setup({
            entry: "/platform/accounts/new",
            bootstrap: bootstrapWith({ global_capabilities: [] }),
        })
        expect(await screen.findByRole("heading", { name: "Access denied" })).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Create account" })).toBeNull()
        expect(server.calls).toEqual([])
    })

    it("A3 has no inline form on the list and links to the creation route", async () => {
        setup()
        await screen.findByText("Alice Example")
        expect(screen.queryByRole("form", { name: "Create account" })).toBeNull()
        expect(screen.getByRole("link", { name: "Create account" })).toHaveAttribute(
            "href",
            "/platform/accounts/new",
        )
    })
})

describe("the list search lives in the address (A4–A7)", () => {
    it("A4 writes q by REPLACE, removes it when cleared, and requests it", async () => {
        const { server, router } = setup()
        await screen.findByText("Alice Example")
        const search = screen.getByLabelText(/Search by display name/)

        fireEvent.change(search, { target: { value: "a" } })
        expect(router.state.historyAction).toBe("REPLACE")
        fireEvent.change(search, { target: { value: "ali" } })
        expect(router.state.historyAction).toBe("REPLACE")
        expect(router.state.location.pathname).toBe("/platform/accounts")
        expect(router.state.location.search).toBe("?q=ali")
        expect(search).toHaveValue("ali")
        await waitFor(() =>
            expect(listCalls(server).map((call) => call.path)).toContain("/admin/accounts?q=ali"),
        )

        fireEvent.change(search, { target: { value: "" } })
        expect(router.state.location.search).toBe("")
        expect(router.state.historyAction).toBe("REPLACE")
    })

    it("A4 leaves no history entry per keystroke", async () => {
        const { router } = setup()
        await screen.findByText("Alice Example")
        const search = screen.getByLabelText(/Search by display name/)
        fireEvent.change(search, { target: { value: "a" } })
        fireEvent.change(search, { target: { value: "al" } })
        fireEvent.change(search, { target: { value: "ali" } })
        // One entry only: there is nothing to go back to.
        const before = router.state.location.key
        await act(async () => {
            await router.navigate(-1)
        })
        expect(router.state.location.key).toBe(before)
    })

    it("A5 reads q from the address and requests it", async () => {
        const { server } = setup({ entry: "/platform/accounts?q=ali" })
        await screen.findByText("Alice Example")
        expect(screen.getByLabelText(/Search by display name/)).toHaveValue("ali")
        expect(listCalls(server).map((call) => call.path)).toEqual(["/admin/accounts?q=ali"])
    })

    it.each([
        ["an over-length q", `/platform/accounts?q=${"a".repeat(201)}`],
        ["a control character", "/platform/accounts?q=a%01b"],
    ])("A5 starts empty and requests no q for %s", async (_label, entry) => {
        const { server } = setup({ entry })
        await screen.findByText("Alice Example")
        expect(screen.getByLabelText(/Search by display name/)).toHaveValue("")
        expect(listCalls(server).map((call) => call.path)).toEqual(["/admin/accounts"])
    })

    it("A6 returns to the list as it was left: Cancel, the back link and browser Back", async () => {
        const { router } = setup({ entry: "/platform/accounts?q=ali" })
        await openCreation()
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        await screen.findByText("Alice Example")
        expect(router.state.location.pathname).toBe("/platform/accounts")
        expect(router.state.location.search).toBe("?q=ali")
        expect(screen.getByLabelText(/Search by display name/)).toHaveValue("ali")

        fireEvent.click(screen.getByRole("link", { name: "Create account" }))
        await screen.findByRole("form", { name: "Create account" })
        fireEvent.click(screen.getByRole("link", { name: "Platform accounts" }))
        await screen.findByText("Alice Example")
        expect(router.state.location.search).toBe("?q=ali")
        expect(screen.getByLabelText(/Search by display name/)).toHaveValue("ali")

        fireEvent.click(screen.getByRole("link", { name: "Create account" }))
        await screen.findByRole("form", { name: "Create account" })
        await act(async () => {
            await router.navigate(-1)
        })
        await screen.findByText("Alice Example")
        expect(router.state.location.search).toBe("?q=ali")
        expect(screen.getByLabelText(/Search by display name/)).toHaveValue("ali")
    })

    it("A7 returns a direct entry to /platform/accounts", async () => {
        const { router } = setup({ entry: "/platform/accounts/new" })
        await screen.findByRole("form", { name: "Create account" })
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        await screen.findByText("Alice Example")
        expect(router.state.location.pathname).toBe("/platform/accounts")
        expect(router.state.location.search).toBe("")
    })

    it.each([
        ["a number", 7],
        ["extra keys", "?q=a&x=1"],
        ["a protocol-relative address", "//evil.example"],
        ["an absolute address", "https://evil.example/"],
        ["another path", "/campaigns"],
        ["an over-length value", "?q=" + "a".repeat(2000)],
        ["a control character", "?q=a%00b"],
    ])("A7 ignores a tampered accountsReturn (%s)", async (_label, value) => {
        const { router } = setup({
            entry: { pathname: "/platform/accounts/new", state: { accountsReturn: value } },
        })
        await screen.findByRole("form", { name: "Create account" })
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        await screen.findByText("Alice Example")
        expect(router.state.location.pathname).toBe("/platform/accounts")
        expect(router.state.location.search).toBe("")
        expect(router.state.location.hash).toBe("")
    })
})

describe("outcomes (A8–A14)", () => {
    it("A8 creates once with trimmed values and shows the activation panel with focus on its heading", async () => {
        const { server } = setup()
        await openCreation()
        fill("  new.gm ", " New GM ")
        fireEvent.click(screen.getByRole("checkbox", { name: "Game master" }))
        // The person presses the button, so it holds focus when the answer arrives.
        submitButton().focus()
        press()

        const heading = await screen.findByRole("heading", {
            name: "Copy the activation link for New GM now",
        })
        expect(postCalls(server)).toHaveLength(1)
        expect(postCalls(server)[0]!.body).toEqual({
            login_name: "new.gm",
            display_name: "New GM",
            email: null,
            system_role_codes: ["player", "gm"],
        })
        expect(postCalls(server)[0]!.headers["X-CSRF-Token"]).toBe(TEST_CSRF)
        await waitFor(() => expect(heading).toHaveFocus())
        expect(screen.getByLabelText("Activation link")).toHaveValue(
            `${window.location.origin}/activate#token=${TOKEN}`,
        )
        expect(screen.queryByRole("form", { name: "Create account" })).toBeNull()
        // One meaningful announcement: the focused heading. No status region repeats it.
        expect(statusTexts().every((text) => text === "")).toBe(true)
    })

    it("A9 keeps the token out of the address, router state and storage, and out of the document afterwards", async () => {
        const { router } = setup({ entry: "/platform/accounts?q=ali" })
        const seen: string[] = []
        const snapshot = () =>
            seen.push(JSON.stringify(router.state.location) + JSON.stringify(window.history.state))
        await openCreation()
        snapshot()
        fill("new.gm", "New GM")
        press()
        await screen.findByLabelText("Activation link")
        snapshot()

        fireEvent.click(screen.getByRole("button", { name: "Back to accounts" }))
        await screen.findByText("Alice Example")
        snapshot()
        expect(document.body.textContent).not.toContain(TOKEN)
        expect(screen.queryByDisplayValue(new RegExp(TOKEN))).toBeNull()

        await act(async () => {
            await router.navigate(-1)
        })
        await screen.findByRole("form", { name: "Create account" })
        snapshot()
        expect(screen.getByLabelText("Login name")).toHaveValue("")
        expect(screen.queryByLabelText("Activation link")).toBeNull()
        expect(document.body.textContent).not.toContain(TOKEN)

        // Create another also drops it.
        fill("second", "Second")
        press()
        await screen.findByLabelText("Activation link")
        snapshot()
        fireEvent.click(screen.getByRole("button", { name: "Create another account" }))
        await screen.findByRole("form", { name: "Create account" })
        snapshot()
        expect(document.body.textContent).not.toContain(TOKEN)

        for (const text of seen) {
            expect(text).not.toContain(TOKEN)
        }
        expect(window.location.href).not.toContain(TOKEN)
        for (const call of setItem.mock.calls) {
            expect(String(call[1])).not.toContain(TOKEN)
        }
        expect(setItem).not.toHaveBeenCalledWith(expect.anything(), expect.stringContaining(TOKEN))
        expect(Object.values(window.localStorage).join("")).not.toContain(TOKEN)
        expect(Object.values(window.sessionStorage).join("")).not.toContain(TOKEN)
    })

    it("A10 Back to accounts returns to the carried query with focus on Create account and a fresh read", async () => {
        const { server, router } = setup({ entry: "/platform/accounts?q=ali" })
        await openCreation()
        const readsBefore = listCalls(server).length
        fill("new.gm", "New GM")
        press()
        await screen.findByLabelText("Activation link")

        fireEvent.click(screen.getByRole("button", { name: "Back to accounts" }))
        await screen.findByText("Alice Example")
        expect(router.state.location.pathname).toBe("/platform/accounts")
        expect(router.state.location.search).toBe("?q=ali")
        await waitFor(() =>
            expect(screen.getByRole("link", { name: "Create account" })).toHaveFocus(),
        )
        expect(listCalls(server).length).toBeGreaterThan(readsBefore)
        expect(screen.queryByRole("dialog", { hidden: false })).toBeNull()
    })

    it("A10 Create another account shows the empty form with Player only and focus on Login name", async () => {
        setup()
        await openCreation()
        fill("new.gm", "New GM")
        fireEvent.click(screen.getByRole("checkbox", { name: "Game master" }))
        fireEvent.change(screen.getByLabelText("Optional email label"), {
            target: { value: "x@example.test" },
        })
        press()
        await screen.findByLabelText("Activation link")

        fireEvent.click(screen.getByRole("button", { name: "Create another account" }))
        await screen.findByRole("form", { name: "Create account" })
        expect(screen.getByLabelText("Login name")).toHaveValue("")
        expect(screen.getByLabelText("Display name")).toHaveValue("")
        expect(screen.getByLabelText("Optional email label")).toHaveValue("")
        expect(screen.getByRole("checkbox", { name: "Player" })).toBeChecked()
        expect(screen.getByRole("checkbox", { name: "Game master" })).not.toBeChecked()
        await waitFor(() => expect(screen.getByLabelText("Login name")).toHaveFocus())
    })

    it("A11 shows a refusal, keeps the values, and clears the message on an edit", async () => {
        const { server } = setup({ post: { status: 422, body: { detail: "nope" } } })
        await openCreation()
        fill("new.gm", "New GM")
        submitButton().focus()
        press()
        await waitFor(() =>
            expect(screen.getByRole("status")).toHaveTextContent(
                "The account could not be created. Try again.",
            ),
        )
        expect(document.body.textContent).not.toContain("nope")
        expect(screen.getByLabelText("Login name")).toHaveValue("new.gm")
        expect(submitButton()).toBeEnabled()
        expect(submitButton()).toHaveFocus()
        expect(postCalls(server)).toHaveLength(1)

        fireEvent.change(screen.getByLabelText("Login name"), { target: { value: "new.gm2" } })
        expect(screen.getByRole("status")).toHaveTextContent("")
    })

    it.each([403, 404])("A12 keeps a %i answer to the denial text", async (status) => {
        setup({ post: { status, body: { detail: "secret detail" } } })
        await openCreation()
        fill("new.gm", "New GM")
        press()
        await waitFor(() =>
            expect(screen.getByRole("status")).toHaveTextContent(
                "You do not have permission to create accounts.",
            ),
        )
        expect(document.body.textContent).not.toContain("secret detail")
    })

    it("A12 reloads the session once on 401 and shows no message", async () => {
        const { reload } = setup({ post: { status: 401, body: {} } })
        await openCreation()
        fill("new.gm", "New GM")
        press()
        await waitFor(() => expect(reload).toHaveBeenCalledTimes(1))
        expect(screen.getByRole("status")).toHaveTextContent("")
    })

    it.each([
        ["a transport failure", { networkError: true } as MockResponse],
        ["a 503 answer", { status: 503, body: {} } as MockResponse],
    ])("A13 reports an unknown outcome for %s and sends nothing more on its own", async (_label, post) => {
        const { server } = setup({ post })
        await openCreation()
        fill("new.gm", "New GM")
        submitButton().focus()
        press()

        const unknown =
            "We could not confirm whether the account was created. Check the account list before trying again: creating it again would add a second account."
        await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(unknown))
        expect(document.body.textContent).not.toContain("could not be created")
        expect(submitButton()).toBeEnabled()
        expect(submitButton()).toHaveFocus()
        await settle()
        expect(postCalls(server)).toHaveLength(1)

        // Edits keep it, and still send nothing.
        fireEvent.change(screen.getByLabelText("Login name"), { target: { value: "new.gm2" } })
        fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "New GM 2" } })
        fireEvent.change(screen.getByLabelText("Optional email label"), { target: { value: "e" } })
        fireEvent.click(screen.getByRole("checkbox", { name: "Observer" }))
        expect(screen.getByRole("status")).toHaveTextContent(unknown)
        await settle()
        expect(postCalls(server)).toHaveLength(1)

        // One press, one more request, whose outcome replaces the message.
        server.on("POST", "/admin/accounts", { status: 201, body: CREATED })
        press()
        await screen.findByLabelText("Activation link")
        expect(postCalls(server)).toHaveLength(2)
        expect(document.body.textContent).not.toContain("could not confirm")
    })

    it("A14 sends one request however often it is submitted while pending", async () => {
        const gate = deferred()
        const { server } = setup({ post: () => gate.promise })
        await openCreation()
        fill("new.gm", "New GM")
        press()
        await waitFor(() => expect(submitButton()).toBeDisabled())
        fireEvent.submit(screen.getByRole("form", { name: "Create account" }))
        fireEvent.click(submitButton())
        expect(postCalls(server)).toHaveLength(1)
        await act(async () => gate.resolve({ status: 201, body: CREATED }))
        await screen.findByLabelText("Activation link")
        expect(postCalls(server)).toHaveLength(1)
    })
})

describe("focus after an outcome keeps what the person chose", () => {
    it("restores the submit button when focus was lost during the wait, for a refusal", async () => {
        const gate = deferred()
        setup({ post: () => gate.promise })
        await openCreation()
        fill("new.gm", "New GM")
        submitButton().focus()
        press()
        await waitFor(() => expect(submitButton()).toBeDisabled())
        ;(document.activeElement as HTMLElement).blur()
        await act(async () => gate.resolve({ status: 422, body: {} }))
        await waitFor(() => expect(submitButton()).toBeEnabled())
        await waitFor(() => expect(submitButton()).toHaveFocus())
    })

    it.each([
        ["a refusal", { status: 422, body: {} } as MockResponse],
        ["an unknown outcome", { networkError: true } as MockResponse],
    ])("does not take focus from a control the person moved to, for %s", async (_label, outcome) => {
        const gate = deferred()
        setup({ post: () => gate.promise })
        await openCreation()
        fill("new.gm", "New GM")
        press()
        await waitFor(() => expect(submitButton()).toBeDisabled())
        const sidebar = screen.getByRole("link", { name: "Sidebar home" })
        sidebar.focus()
        await act(async () => gate.resolve(outcome))
        await waitFor(() => expect(submitButton()).toBeEnabled())
        expect(sidebar).toHaveFocus()
    })

    it("does not take focus for the activation heading when the person moved elsewhere", async () => {
        const gate = deferred()
        setup({ post: () => gate.promise })
        await openCreation()
        fill("new.gm", "New GM")
        press()
        await waitFor(() => expect(submitButton()).toBeDisabled())
        const sidebar = screen.getByRole("link", { name: "Sidebar home" })
        sidebar.focus()
        await act(async () => gate.resolve({ status: 201, body: CREATED }))
        const heading = await screen.findByRole("heading", {
            name: "Copy the activation link for New GM now",
        })
        await settle()
        expect(sidebar).toHaveFocus()
        expect(heading).not.toHaveFocus()
        expect(screen.getByLabelText("Activation link")).toBeInTheDocument()
    })

    it("does not take focus for the list's Create account link when the person moved elsewhere", async () => {
        setup({ entry: "/platform/accounts" })
        await openCreation()
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        await screen.findByText("Alice Example")
        await waitFor(() =>
            expect(screen.getByRole("link", { name: "Create account" })).toHaveFocus(),
        )
        // The marker is spent by the first arrival: typing replaces the entry, and focus stays where it is.
        const search = screen.getByLabelText(/Search by display name/)
        search.focus()
        fireEvent.change(search, { target: { value: "a" } })
        await settle()
        expect(search).toHaveFocus()
    })
})

describe("departure guards (A15–A18)", () => {
    it("A15 asks about a dirty form on the back link and a sidebar link; Keep editing keeps it; Discard leaves once", async () => {
        const { server, router } = setup()
        await openCreation()
        fill("half", "Half Written")

        fireEvent.click(screen.getByRole("link", { name: "Platform accounts" }))
        expect(await screen.findByRole("dialog", { name: "Discard unsaved changes?", hidden: true })).toBeInTheDocument()
        expect(router.state.location.pathname).toBe("/platform/accounts/new")
        fireEvent.click(screen.getByRole("button", { name: "Keep editing" }))
        expect(router.state.location.pathname).toBe("/platform/accounts/new")
        expect(screen.getByLabelText("Login name")).toHaveValue("half")

        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        await screen.findByRole("dialog", { name: "Discard unsaved changes?", hidden: true })
        fireEvent.click(screen.getByRole("button", { name: "Keep editing" }))

        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        fireEvent.click(await screen.findByRole("button", { name: "Discard changes" }))
        await screen.findByText("Alice Example")
        expect(router.state.location.pathname).toBe("/platform/accounts")
        expect(postCalls(server)).toHaveLength(0)
    })

    it("A15 leaves a clean form without a question", async () => {
        const { router } = setup()
        await openCreation()
        fireEvent.click(screen.getByRole("link", { name: "Platform accounts" }))
        await screen.findByText("Alice Example")
        expect(router.state.location.pathname).toBe("/platform/accounts")
        expect(screen.queryByRole("button", { name: "Discard changes" })).toBeNull()
    })

    it("A15 counts a changed role as unsaved input", async () => {
        setup()
        await openCreation()
        fireEvent.click(screen.getByRole("checkbox", { name: "Game master" }))
        fireEvent.click(screen.getByRole("link", { name: "Platform accounts" }))
        expect(await screen.findByRole("dialog", { name: "Discard unsaved changes?", hidden: true })).toBeInTheDocument()
    })

    it("A16 asks while the request is pending; Leave aborts the wait and shows nothing afterwards", async () => {
        const gate = deferred()
        const { server, router } = setup({ post: () => gate.promise })
        await openCreation()
        fill("new.gm", "New GM")
        press()
        await waitFor(() => expect(submitButton()).toBeDisabled())

        fireEvent.click(screen.getByRole("link", { name: "Platform accounts" }))
        expect(
            await screen.findByRole("dialog", { name: "Leave while the account is being created?", hidden: true }),
        ).toBeInTheDocument()
        expect(screen.getByText("The account may still be created, but its activation link will not be shown.")).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Stay" }))
        expect(router.state.location.pathname).toBe("/platform/accounts/new")

        fireEvent.click(screen.getByRole("link", { name: "Platform accounts" }))
        fireEvent.click(await screen.findByRole("button", { name: "Leave" }))
        await screen.findByText("Alice Example")
        await act(async () => gate.resolve({ status: 201, body: CREATED }))
        await settle()
        expect(document.body.textContent).not.toContain(TOKEN)
        expect(screen.queryByLabelText("Activation link")).toBeNull()
        expect(postCalls(server)).toHaveLength(1)
        expect(router.state.location.pathname).toBe("/platform/accounts")
    })

    it("A17 asks before the shown activation link is lost; Back to accounts and Create another do not", async () => {
        const { router } = setup()
        await openCreation()
        fill("new.gm", "New GM")
        press()
        await screen.findByLabelText("Activation link")

        fireEvent.click(screen.getByRole("link", { name: "Platform accounts" }))
        expect(
            await screen.findByRole("dialog", { name: "Leave without the activation link?", hidden: true }),
        ).toBeInTheDocument()
        expect(screen.getByText("It is shown once and cannot be shown again.")).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Stay" }))
        expect(screen.getByLabelText("Activation link")).toBeInTheDocument()
        expect(router.state.location.pathname).toBe("/platform/accounts/new")

        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        fireEvent.click(await screen.findByRole("button", { name: "Leave" }))
        await screen.findByText("Home page")
        expect(document.body.textContent).not.toContain(TOKEN)

        await act(async () => {
            await router.navigate(-1)
        })
        await screen.findByRole("form", { name: "Create account" })
        expect(screen.queryByLabelText("Activation link")).toBeNull()
    })

    it("A17 lets Back to accounts and Create another go without asking", async () => {
        const { router } = setup()
        await openCreation()
        fill("a.one", "A One")
        press()
        await screen.findByLabelText("Activation link")
        fireEvent.click(screen.getByRole("button", { name: "Create another account" }))
        await screen.findByRole("form", { name: "Create account" })
        expect(screen.queryByRole("button", { name: "Leave" })).toBeNull()

        fill("a.two", "A Two")
        press()
        await screen.findByLabelText("Activation link")
        fireEvent.click(screen.getByRole("button", { name: "Back to accounts" }))
        await screen.findByText("Alice Example")
        expect(router.state.location.pathname).toBe("/platform/accounts")
        expect(screen.queryByRole("button", { name: "Leave" })).toBeNull()
    })

    it("A18 asks before leaving the list with a reset link shown; the search does not", async () => {
        const server = installMockServer()
        server.on("GET", GET_ACCOUNTS, { body: LIST })
        server.on("POST", "/admin/accounts/user-1/password-reset", {
            status: 200,
            body: { user_id: "user-1", raw_reset_token: "reset-token-7", expires_at: "2026-12-01T00:00:00Z" },
        })
        const { router } = renderAuthoringRoutes({
            initialEntry: "/platform/accounts",
            bootstrap: ADMIN,
            routes: [
                { path: "/platform/accounts", element: <ListRoute /> },
                { path: "/platform/accounts/new", element: <CreateRoute /> },
            ],
        })
        await screen.findByText("Alice Example")
        fireEvent.click(screen.getByRole("button", { name: "Issue password reset" }))
        await screen.findByLabelText("Password-reset link")

        // Typing in the search is not a departure.
        fireEvent.change(screen.getByLabelText(/Search by display name/), { target: { value: "al" } })
        expect(screen.queryByRole("button", { name: "Leave" })).toBeNull()
        await screen.findByText("Alice Example")
        expect(screen.getByLabelText("Password-reset link")).toBeInTheDocument()

        fireEvent.click(screen.getByRole("link", { name: "Create account" }))
        expect(
            await screen.findByRole("dialog", { name: "Leave without the password-reset link?", hidden: true }),
        ).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Stay" }))
        expect(router.state.location.pathname).toBe("/platform/accounts")
        expect(screen.getByLabelText("Password-reset link")).toBeInTheDocument()

        fireEvent.click(screen.getByRole("link", { name: "Create account" }))
        fireEvent.click(await screen.findByRole("button", { name: "Leave" }))
        await screen.findByRole("form", { name: "Create account" })
        expect(document.body.textContent).not.toContain("reset-token-7")

        await act(async () => {
            await router.navigate(-1)
        })
        await screen.findByText("Alice Example")
        expect(screen.queryByLabelText("Password-reset link")).toBeNull()
    })

    it("A18 lets Dismiss release the reset-link guard", async () => {
        const server = installMockServer()
        server.on("GET", GET_ACCOUNTS, { body: LIST })
        server.on("POST", "/admin/accounts/user-1/password-reset", {
            status: 200,
            body: { user_id: "user-1", raw_reset_token: "reset-token-7", expires_at: "2026-12-01T00:00:00Z" },
        })
        const { router } = renderAuthoringRoutes({
            initialEntry: "/platform/accounts",
            bootstrap: ADMIN,
            routes: [
                { path: "/platform/accounts", element: <ListRoute /> },
                { path: "/platform/accounts/new", element: <CreateRoute /> },
            ],
        })
        await screen.findByText("Alice Example")
        fireEvent.click(screen.getByRole("button", { name: "Issue password reset" }))
        await screen.findByLabelText("Password-reset link")
        fireEvent.click(screen.getByRole("button", { name: "Dismiss" }))
        fireEvent.click(screen.getByRole("link", { name: "Create account" }))
        await screen.findByRole("form", { name: "Create account" })
        expect(router.state.location.pathname).toBe("/platform/accounts/new")
    })
})

describe("arrival focus (A20)", () => {
    it("focuses the heading on a PUSH arrival but not on Back, Forward or a direct entry", async () => {
        const { router } = setup()
        await openCreation()
        expect(h1("Create account")).toHaveFocus()

        await act(async () => {
            await router.navigate(-1)
        })
        await screen.findByText("Alice Example")
        // The list takes no focus on a POP arrival, and none on a plain arrival.
        expect(screen.getByRole("link", { name: "Create account" })).not.toHaveFocus()

        await act(async () => {
            await router.navigate(1)
        })
        await screen.findByRole("form", { name: "Create account" })
        await settle()
        expect(h1("Create account")).not.toHaveFocus()
    })

    it("does not move focus for a direct entry", async () => {
        setup({ entry: "/platform/accounts/new" })
        await screen.findByRole("form", { name: "Create account" })
        await settle()
        expect(h1("Create account")).not.toHaveFocus()
    })

    it("focuses the list's Create account link on the PUSH return only", async () => {
        const { router } = setup()
        await openCreation()
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        await screen.findByText("Alice Example")
        await waitFor(() =>
            expect(screen.getByRole("link", { name: "Create account" })).toHaveFocus(),
        )

        // The same entry reached again by Back/Forward does not repeat it.
        fireEvent.click(screen.getByRole("link", { name: "Create account" }))
        await screen.findByRole("form", { name: "Create account" })
        await act(async () => {
            await router.navigate(-1)
        })
        await screen.findByText("Alice Example")
        await settle()
        expect(screen.getByRole("link", { name: "Create account" })).not.toHaveFocus()
        expect(document.activeElement).not.toBe(screen.getByRole("link", { name: "Create account" }))
    })
})
