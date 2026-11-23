import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { Link } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { FetchCall, MockResponse, MockServer } from "../test/authoringHarness"
import { useAuthenticatedSession } from "../layouts/useAuthenticatedSession"
import { AdminAccountsPage } from "./AdminAccountsPage"
import type { PlatformAccount } from "../types/platformAccounts"
import type { SessionBootstrap } from "../types/bootstrap"

// T02 (P15-C04-S02): saving staged system-role changes. Real list page, panel and hooks; only the network (a
// stubbed fetch) and the session are faked. Every case states what was sent, in what order, and what the person
// is told: the changes are separate requests, not one atomic write.

const MANAGE = ["accounts.manage", "system_roles.manage"]
const ADMIN = bootstrapWith({ global_capabilities: MANAGE })
const SELF_ID = "user-fixture-001"
const GET_ACCOUNTS = /^\/admin\/accounts(\?|$)/
const ROLE_POST = /^\/admin\/accounts\/[^/]+\/system-roles(\/[a-z]+\/revoke)?$/
const LAST_ADMIN = "This is the platform's only active administrator and cannot lose the Administrator role."
const OPERATOR_SCRIPT = "Granting Administrator is done by the operator script on this deployment."
const PERMISSION = "You do not have permission to make this change."

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

type Reply = MockResponse | ((call: FetchCall) => MockResponse | Promise<MockResponse>)

let items: PlatformAccount[]
// What the reconciliation read (limit=100) answers when it is not the list: the same list unless replaced.
let reconcileReply: Reply | null
let server: MockServer
let replies: Record<string, Reply>
const refreshMock = vi.fn<() => Promise<SessionBootstrap | null>>()

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

const keyOf = (call: FetchCall): string => {
    const match = /system-roles(?:\/([a-z]+)\/revoke)?$/.exec(call.path)
    if (match === null) return call.path
    return match[1] !== undefined
        ? `revoke:${match[1]}`
        : `assign:${(call.body as { system_role_code: string }).system_role_code}`
}

function setup(bootstrap = ADMIN) {
    server = installMockServer()
    server.on("GET", GET_ACCOUNTS, (call) => {
        if (call.path.includes("limit=100") && reconcileReply !== null) {
            return typeof reconcileReply === "function" ? reconcileReply(call) : reconcileReply
        }
        return { body: { items, next_cursor: null } }
    })
    server.on("POST", ROLE_POST, (call) => {
        const key = keyOf(call)
        const reply = replies[key]
        if (reply !== undefined) {
            return typeof reply === "function" ? reply(call) : reply
        }
        const code = key.split(":")[1]
        const userId = /accounts\/([^/]+)\//.exec(call.path)![1]
        return { body: { user_id: userId, system_role_code: code, changed: true } }
    })
    return renderAuthoringRoutes({
        initialEntry: "/platform/accounts",
        bootstrap,
        onRefresh: refreshMock,
        routes: [
            { path: "/platform/accounts", element: <ListRoute /> },
            { path: "/home", element: <p>Home page</p> },
        ],
    })
}

const roleCalls = () => server.calls.filter((call) => call.method === "POST" && ROLE_POST.test(call.path))
const roleKeys = () => roleCalls().map(keyOf)
const reconcileCalls = () => server.calls.filter((call) => call.method === "GET" && call.path.includes("limit=100"))
const listCalls = () => server.calls.filter((call) => call.method === "GET" && !call.path.includes("limit=100"))
const editButton = (name: string) => screen.getByRole("button", { name: `Edit roles for ${name}` })
const box = (name: string) => screen.getByRole("checkbox", { name })
const saveButton = () => screen.getByRole("button", { name: "Save changes" })
const panel = (name: string) => screen.getByRole("region", { name: `System roles for ${name}` })
const ledger = (name: string) =>
    within(within(panel(name)).getByRole("list", { name: "Result" }))
        .getAllByRole("listitem")
        .map((item) => item.textContent)
const statusOf = (name: string) => within(panel(name)).getByRole("status")
const dialogHeading = (name: string) => screen.findByRole("heading", { name, hidden: true })
const resultHeading = () => screen.getByRole("heading", { level: 3, name: "Result" })

function deferred() {
    let resolve: (value: MockResponse) => void = () => {}
    const promise = new Promise<MockResponse>((r) => (resolve = r))
    return { promise, resolve }
}

const settle = (ms = 25) =>
    act(async () => {
        await new Promise((resolve) => setTimeout(resolve, ms))
    })

async function openRoles(name: string) {
    await screen.findByText(name)
    fireEvent.click(editButton(name))
    await screen.findByRole("heading", { level: 2, name: `System roles for ${name}` })
}

// Stage "Add Game master" and "Remove Player" for Alice, then press Save (focus on it first, as a person would).
async function stageAndSave(name = "Alice Example") {
    await openRoles(name)
    fireEvent.click(box("Game master"))
    fireEvent.click(box("Player"))
    saveButton().focus()
    fireEvent.click(saveButton())
}

beforeEach(() => {
    items = [account("user-1", "Alice Example"), account("user-2", "Bob Example")]
    reconcileReply = null
    replies = {}
    refreshMock.mockReset()
    refreshMock.mockResolvedValue(null)
})

afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
})

describe("B11-B12 saving in order, and what is shown", () => {
    it("B11 sends the changes one after the other, grants first, and nothing for unchanged roles", async () => {
        setup()
        const first = deferred()
        replies["assign:gm"] = () => first.promise
        items = [account("user-1", "Alice Example", ["gm"]), account("user-2", "Bob Example")]
        await stageAndSave()

        await waitFor(() => expect(roleKeys()).toEqual(["assign:gm"]))
        expect(screen.getByText("Saving changes…")).toBeInTheDocument()
        await settle()
        expect(roleKeys()).toEqual(["assign:gm"])

        await act(async () => first.resolve({ body: { user_id: "user-1", system_role_code: "gm", changed: true } }))
        await waitFor(() => expect(roleKeys()).toEqual(["assign:gm", "revoke:player"]))
        await screen.findByRole("heading", { level: 3, name: "Result" })
        expect(roleKeys()).toEqual(["assign:gm", "revoke:player"])
    })

    it("B12 shows each result, reconciles by user id without reloading the list, and focuses Result when focus was lost", async () => {
        setup()
        const sawLoading: string[] = []
        const observer = new MutationObserver(() => {
            if (document.body.textContent?.includes("Loading accounts…")) sawLoading.push("seen")
        })
        replies["revoke:player"] = { body: { user_id: "user-1", system_role_code: "player", changed: false } }
        items = [account("user-1", "Alice Example", ["gm"]), account("user-2", "Bob Example")]
        await screen.findByText("Alice Example")
        const listBefore = listCalls().length
        observer.observe(document.body, { subtree: true, childList: true, characterData: true })
        await stageAndSave()

        await screen.findByRole("heading", { level: 3, name: "Result" })
        expect(ledger("Alice Example")).toEqual(["Game master added", "Already did not have Player"])
        expect(statusOf("Alice Example")).toHaveTextContent("2 of 2 changes saved.")
        expect(reconcileCalls()).toHaveLength(1)
        expect(reconcileCalls()[0]!.path).toBe("/admin/accounts?q=user-1&limit=100")
        expect(listCalls().length).toBe(listBefore)
        const row = screen.getByRole("row", { name: /Alice Example/ })
        expect(within(row).getByText("gm")).toBeInTheDocument()
        expect(screen.queryByText("Loading accounts…")).toBeNull()
        await settle()
        observer.disconnect()
        expect(sawLoading).toEqual([])
        expect(resultHeading()).toHaveFocus()
        expect(refreshMock).not.toHaveBeenCalled()
        // Nothing is left to save: the draft equals the reconciled roles.
        expect(screen.getByText("No changes")).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument()
    })

    it("keeps focus where the person moved it while saving", async () => {
        setup()
        const first = deferred()
        replies["assign:gm"] = () => first.promise
        items = [account("user-1", "Alice Example", ["gm"]), account("user-2", "Bob Example")]
        await stageAndSave()
        await waitFor(() => expect(roleKeys()).toEqual(["assign:gm"]))
        const search = screen.getByLabelText(/Search by display name/)
        search.focus()
        await act(async () => first.resolve({ body: { user_id: "user-1", system_role_code: "gm", changed: true } }))
        await screen.findByRole("heading", { level: 3, name: "Result" })
        expect(search).toHaveFocus()
    })

    it("disables the checkboxes, Save and Cancel while saving", async () => {
        setup()
        const first = deferred()
        replies["assign:gm"] = () => first.promise
        await stageAndSave()
        await waitFor(() => expect(roleKeys()).toEqual(["assign:gm"]))
        expect(box("Game master")).toBeDisabled()
        expect(box("Player")).toBeDisabled()
        expect(saveButton()).toBeDisabled()
        expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled()
        expect(editButton("Bob Example")).toBeDisabled()
        await act(async () => first.resolve({ body: { user_id: "user-1", system_role_code: "gm", changed: true } }))
    })
})

describe("B13-B15 refusals and the stop rules", () => {
    it("B13 reports a last-administrator refusal beside a saved step and drops the refused change", async () => {
        items = [account("user-1", "Alice Example"), account("user-3", "Carol Admin", ["admin"])]
        setup()
        replies["revoke:admin"] = { status: 409, body: { error: { code: "last_active_platform_administrator" } } }
        items = [account("user-1", "Alice Example"), account("user-3", "Carol Admin", ["admin", "gm"])]
        await openRoles("Carol Admin")
        fireEvent.click(box("Game master"))
        fireEvent.click(box("Administrator"))
        fireEvent.click(saveButton())

        await screen.findByRole("heading", { level: 3, name: "Result" })
        expect(roleKeys()).toEqual(["assign:gm", "revoke:admin"])
        expect(ledger("Carol Admin")).toEqual(["Game master added", `Remove Administrator: refused. ${LAST_ADMIN}`])
        expect(statusOf("Carol Admin")).toHaveTextContent("1 of 2 changes saved. 1 refused.")
        expect(box("Administrator")).toBeChecked()
        expect(screen.getByText("No changes")).toBeInTheDocument()
    })

    it("B14 refuses only the Administrator grant when the deployment setting is off and continues", async () => {
        setup(bootstrapWith({ global_capabilities: [...MANAGE, "system_roles.grant_admin"] }))
        replies["assign:admin"] = { status: 403, body: { error: { code: "admin_grant_disabled" } } }
        items = [account("user-1", "Alice Example", ["player", "gm"]), account("user-2", "Bob Example")]
        await openRoles("Alice Example")
        fireEvent.click(box("Administrator"))
        fireEvent.click(box("Game master"))
        fireEvent.click(saveButton())

        await screen.findByRole("heading", { level: 3, name: "Result" })
        expect(roleKeys()).toEqual(["assign:admin", "assign:gm"])
        expect(ledger("Alice Example")).toEqual([`Add Administrator: refused. ${OPERATOR_SCRIPT}`, "Game master added"])
        expect(statusOf("Alice Example")).toHaveTextContent("1 of 2 changes saved. 1 refused.")
    })

    it.each([
        ["a 403 with another code", { status: 403, body: { error: { code: "forbidden" } } }],
        ["a 404", { status: 404, body: {} }],
    ])("B14 stops after %s: the step is refused with the permission text and later steps are not sent", async (_n, reply) => {
        setup()
        replies["assign:gm"] = reply
        await stageAndSave()

        await screen.findByRole("heading", { level: 3, name: "Result" })
        expect(roleKeys()).toEqual(["assign:gm"])
        expect(ledger("Alice Example")).toEqual([
            `Add Game master: refused. ${PERMISSION}`,
            "Remove Player: not sent.",
        ])
        expect(statusOf("Alice Example")).toHaveTextContent("0 of 2 changes saved. 1 refused. 1 not sent.")
    })

    it("B15 stops at a 401, marks the rest not sent, reloads the session once and sends nothing more", async () => {
        const view = setup()
        replies["assign:gm"] = { status: 401, body: {} }
        await stageAndSave()

        await waitFor(() => expect(view.reload).toHaveBeenCalledTimes(1))
        await settle()
        expect(roleKeys()).toEqual(["assign:gm"])
        expect(view.reload).toHaveBeenCalledTimes(1)
        expect(reconcileCalls()).toHaveLength(0)
    })
})

describe("B16-B18 uncertain outcomes, reconciliation and retry", () => {
    it.each([
        ["a transport failure", { networkError: true }],
        ["a 503", { status: 503, body: {} }],
    ])("B16 stops at %s on step 1 and does not send step 2", async (_n, reply) => {
        setup()
        replies["assign:gm"] = reply
        await stageAndSave()

        await screen.findByRole("heading", { level: 3, name: "Result" })
        expect(roleKeys()).toEqual(["assign:gm"])
        expect(ledger("Alice Example")[0]).toContain("Add Game master: not confirmed.")
        expect(ledger("Alice Example")[1]).toBe("Remove Player: not sent.")
        expect(statusOf("Alice Example")).toHaveTextContent("0 of 2 changes saved. 1 could not be confirmed. 1 not sent.")
        // Reconciliation found nothing applied: both changes stay staged for a deliberate second Save.
        expect(screen.getByRole("list", { name: "Changes not saved yet" })).toHaveTextContent("Add Game masterRemove Player")
    })

    it("B16 marks an unknown step confirmed when the current roles already show it, and keeps the rest staged", async () => {
        setup()
        replies["assign:gm"] = { networkError: true }
        items = [account("user-1", "Alice Example", ["player", "gm"]), account("user-2", "Bob Example")]
        await stageAndSave()

        await screen.findByRole("heading", { level: 3, name: "Result" })
        expect(ledger("Alice Example")[0]).toBe("Add Game master: confirmed from current roles.")
        expect(ledger("Alice Example")[1]).toBe("Remove Player: not sent.")
        expect(statusOf("Alice Example")).toHaveTextContent("1 of 2 changes saved. 1 not sent.")
        expect(screen.getByRole("list", { name: "Changes not saved yet" })).toHaveTextContent("Remove Player")
        expect(screen.getByRole("list", { name: "Changes not saved yet" })).not.toHaveTextContent("Add Game master")
    })

    it("B18 the next Save sends only what still differs, and never replays a confirmed step", async () => {
        setup()
        replies["assign:gm"] = { networkError: true }
        items = [account("user-1", "Alice Example", ["player", "gm"]), account("user-2", "Bob Example")]
        await stageAndSave()
        await screen.findByRole("heading", { level: 3, name: "Result" })
        expect(roleKeys()).toEqual(["assign:gm"])

        replies["assign:gm"] = { body: { user_id: "user-1", system_role_code: "gm", changed: true } }
        items = [account("user-1", "Alice Example", ["gm"]), account("user-2", "Bob Example")]
        fireEvent.click(saveButton())
        fireEvent.click(saveButton())
        await waitFor(() => expect(roleKeys()).toEqual(["assign:gm", "revoke:player"]))
        await settle()
        expect(roleKeys()).toEqual(["assign:gm", "revoke:player"])
        await waitFor(() => expect(screen.getByText("No changes")).toBeInTheDocument())
        expect(ledger("Alice Example")).toEqual(["Player removed"])
    })

    it("B17 offers Check current roles when the read fails: Save is disabled and only GETs are sent", async () => {
        setup()
        replies["assign:gm"] = { networkError: true }
        reconcileReply = { networkError: true }
        await stageAndSave()

        await screen.findByRole("button", { name: "Check current roles" })
        expect(statusOf("Alice Example")).toHaveTextContent("We could not check this account's current roles.")
        expect(saveButton()).toBeDisabled()
        const postsBefore = roleCalls().length
        const check = screen.getByRole("button", { name: "Check current roles" })
        check.focus()
        fireEvent.click(check)
        await waitFor(() => expect(reconcileCalls()).toHaveLength(2))
        await settle()
        expect(roleCalls()).toHaveLength(postsBefore)
        expect(screen.getByRole("button", { name: "Check current roles" })).toHaveFocus()
        expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled()

        // A later successful read ends the uncertainty and confirms what the roles show.
        reconcileReply = null
        items = [account("user-1", "Alice Example", ["player", "gm"]), account("user-2", "Bob Example")]
        fireEvent.click(screen.getByRole("button", { name: "Check current roles" }))
        await waitFor(() => expect(screen.queryByRole("button", { name: "Check current roles" })).toBeNull())
        expect(ledger("Alice Example")[0]).toBe("Add Game master: confirmed from current roles.")
        expect(roleCalls()).toHaveLength(postsBefore)
        expect(saveButton()).toBeEnabled()
    })

    it("B17 treats an account missing from the read as not checked", async () => {
        setup()
        replies["assign:gm"] = { status: 503, body: {} }
        reconcileReply = { body: { items: [account("user-9", "Someone Else")], next_cursor: null } }
        await stageAndSave()

        await screen.findByRole("button", { name: "Check current roles" })
        expect(statusOf("Alice Example")).toHaveTextContent("We could not check this account's current roles.")
        expect(saveButton()).toBeDisabled()
    })
})

describe("B19-B22 changes to one's own roles", () => {
    const own = () => account(SELF_ID, "Casey Admin", ["admin", "player"])

    beforeEach(() => {
        items = [own(), account("user-2", "Bob Example")]
    })

    async function stageOwn() {
        await openRoles("Casey Admin")
        fireEvent.click(box("Observer"))
        fireEvent.click(box("Player"))
        fireEvent.click(box("Administrator"))
    }

    it("B19 asks first, sends the removal last and ends in a receipt; access is refreshed only on Continue", async () => {
        setup()
        await stageOwn()
        fireEvent.click(saveButton())

        expect(await dialogHeading("Remove your own Administrator role?")).toBeInTheDocument()
        expect(
            screen.getByText(
                "You will lose Platform accounts and system-role management as soon as it is saved. Another administrator would have to give it back.",
            ),
        ).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Keep editing", hidden: true }))
        expect(roleCalls()).toHaveLength(0)
        expect(box("Observer")).toBeChecked()

        fireEvent.click(saveButton())
        await screen.findByRole("heading", { name: "Remove your own Administrator role?", hidden: true })
        fireEvent.click(screen.getByRole("button", { name: "Remove my role", hidden: true }))

        const receipt = await screen.findByRole("heading", { level: 2, name: "Your Administrator role was removed" })
        expect(roleKeys()).toEqual(["assign:observer", "revoke:player", "revoke:admin"])
        await waitFor(() => expect(receipt).toHaveFocus())
        expect(screen.getByText("Platform accounts will close when you continue.")).toBeInTheDocument()
        expect(screen.getByRole("list", { name: "Result" })).toHaveTextContent("Observer added")
        expect(screen.getByRole("list", { name: "Result" })).toHaveTextContent("Player removed")
        expect(screen.getByRole("list", { name: "Result" })).toHaveTextContent("Administrator removed")
        expect(screen.queryByRole("link", { name: "Create account" })).toBeNull()
        expect(screen.queryByRole("table")).toBeNull()
        expect(screen.queryByRole("button", { name: /Edit roles/ })).toBeNull()
        expect(screen.queryByRole("button", { name: "Issue password reset" })).toBeNull()
        expect(screen.getByRole("heading", { level: 1, name: "Platform accounts" })).toBeInTheDocument()
        expect(refreshMock).not.toHaveBeenCalled()

        fireEvent.click(screen.getByRole("button", { name: "Continue" }))
        await waitFor(() => expect(refreshMock).toHaveBeenCalledTimes(1))
    })

    it("B19 falls back to a session reload when the refresh fails", async () => {
        const view = setup()
        refreshMock.mockRejectedValue(new Error("offline"))
        await stageOwn()
        fireEvent.click(saveButton())
        await screen.findByRole("heading", { name: "Remove your own Administrator role?", hidden: true })
        fireEvent.click(screen.getByRole("button", { name: "Remove my role", hidden: true }))
        await screen.findByRole("heading", { level: 2, name: "Your Administrator role was removed" })
        fireEvent.click(screen.getByRole("button", { name: "Continue" }))
        await waitFor(() => expect(view.reload).toHaveBeenCalledTimes(1))
        expect(refreshMock).toHaveBeenCalledTimes(1)
    })

    it("B20 treats a last-administrator refusal on one's own removal as ordinary: no receipt, no refresh", async () => {
        setup()
        replies["revoke:admin"] = { status: 409, body: { error: { code: "last_active_platform_administrator" } } }
        await openRoles("Casey Admin")
        fireEvent.click(box("Administrator"))
        fireEvent.click(saveButton())
        await screen.findByRole("heading", { name: "Remove your own Administrator role?", hidden: true })
        fireEvent.click(screen.getByRole("button", { name: "Remove my role", hidden: true }))

        await screen.findByRole("heading", { level: 3, name: "Result" })
        expect(screen.queryByRole("heading", { name: "Your Administrator role was removed" })).toBeNull()
        expect(ledger("Casey Admin")).toEqual([`Remove Administrator: refused. ${LAST_ADMIN}`])
        expect(screen.getByRole("link", { name: "Create account" })).toBeInTheDocument()
        await settle()
        expect(refreshMock).not.toHaveBeenCalled()
    })

    it("B21 refreshes once after reconciliation for another confirmed change to one's own roles, and the panel stays", async () => {
        items = [account(SELF_ID, "Casey Admin", ["admin", "gm"]), account("user-2", "Bob Example")]
        setup()
        items = [account(SELF_ID, "Casey Admin", ["admin"]), account("user-2", "Bob Example")]
        await openRoles("Casey Admin")
        fireEvent.click(box("Game master"))
        fireEvent.click(saveButton())

        await screen.findByRole("heading", { level: 3, name: "Result" })
        await waitFor(() => expect(refreshMock).toHaveBeenCalledTimes(1))
        expect(reconcileCalls()).toHaveLength(1)
        expect(ledger("Casey Admin")).toEqual(["Game master removed"])
        expect(panel("Casey Admin")).toBeInTheDocument()
        await settle()
        expect(refreshMock).toHaveBeenCalledTimes(1)
    })

    it("B22 shows the access receipt when the reconciliation read is answered 404", async () => {
        items = [account("user-1", "Alice Example"), account("user-2", "Bob Example")]
        setup()
        reconcileReply = { status: 404, body: {} }
        await stageAndSave()

        const receipt = await screen.findByRole("heading", {
            level: 2,
            name: "Your access to platform accounts may have changed",
        })
        await waitFor(() => expect(receipt).toHaveFocus())
        expect(screen.getByText("We could not check the result. Continue to update your access.")).toBeInTheDocument()
        expect(screen.getByRole("list", { name: "Result" })).toHaveTextContent("Game master added")
        expect(screen.queryByRole("table")).toBeNull()
        expect(refreshMock).not.toHaveBeenCalled()
        fireEvent.click(screen.getByRole("button", { name: "Continue" }))
        await waitFor(() => expect(refreshMock).toHaveBeenCalledTimes(1))
    })
})

describe("B23 leaving while saving, and departure feedback after a partial or uncertain save", () => {
    it("asks before a path change while saving: Stay continues the batch, Leave stops it", async () => {
        setup()
        const first = deferred()
        replies["assign:gm"] = () => first.promise
        await stageAndSave()
        await waitFor(() => expect(roleKeys()).toEqual(["assign:gm"]))

        // Typing in the search is not a departure and does not stop the batch.
        fireEvent.change(screen.getByLabelText(/Search by display name/), { target: { value: "ali" } })
        expect(screen.queryByRole("heading", { name: "Leave while role changes are being saved?", hidden: true })).toBeNull()

        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        expect(await dialogHeading("Leave while role changes are being saved?")).toBeInTheDocument()
        expect(screen.getByText("Changes already sent may still be saved. You will not see their result.")).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Stay", hidden: true }))
        await act(async () => first.resolve({ body: { user_id: "user-1", system_role_code: "gm", changed: true } }))
        await waitFor(() => expect(roleKeys()).toEqual(["assign:gm", "revoke:player"]))
    })

    it("Leave while saving aborts the wait and no later step is sent", async () => {
        setup()
        const first = deferred()
        replies["assign:gm"] = () => first.promise
        await stageAndSave()
        await waitFor(() => expect(roleKeys()).toEqual(["assign:gm"]))

        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        await dialogHeading("Leave while role changes are being saved?")
        fireEvent.click(screen.getByRole("button", { name: "Leave", hidden: true }))
        expect(await screen.findByText("Home page")).toBeInTheDocument()
        await act(async () => first.resolve({ body: { user_id: "user-1", system_role_code: "gm", changed: true } }))
        await settle()
        expect(roleKeys()).toEqual(["assign:gm"])
        expect(reconcileCalls()).toHaveLength(0)
    })

    it("adds the reset-link sentence to the saving question when a link is also shown", async () => {
        setup()
        server.on("POST", "/admin/accounts/user-2/password-reset", {
            body: { user_id: "user-2", raw_reset_token: "tok", expires_at: "2026-10-01T00:00:00Z" },
        })
        const first = deferred()
        replies["assign:gm"] = () => first.promise
        await screen.findByText("Bob Example")
        fireEvent.click(screen.getAllByRole("button", { name: "Issue password reset" })[1]!)
        await screen.findByLabelText("Password-reset link")
        await screen.findByText("Bob Example")
        await stageAndSave()
        await waitFor(() => expect(roleKeys()).toEqual(["assign:gm"]))
        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        await dialogHeading("Leave while role changes are being saved?")
        expect(
            screen.getByText(
                "Changes already sent may still be saved. You will not see their result. The password-reset link shown on this page will also be lost.",
            ),
        ).toBeInTheDocument()
    })

    it("does not say changes were not saved after an uncertain outcome, and Stay and Leave send nothing more", async () => {
        setup()
        replies["assign:gm"] = { networkError: true }
        await stageAndSave()
        await screen.findByRole("heading", { level: 3, name: "Result" })
        const sent = server.calls.length

        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        expect(await dialogHeading("Leave with role changes not fully saved?")).toBeInTheDocument()
        expect(screen.queryByText(/have not been saved/)).toBeNull()
        expect(
            screen.getByText(
                "Some changes to Alice Example's system roles may already be saved. Leaving discards the changes still staged here and the record of what happened. Check the account's roles in the list afterwards.",
            ),
        ).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Stay", hidden: true }))
        expect(server.calls).toHaveLength(sent)
        expect(roleKeys()).toEqual(["assign:gm"])

        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        await dialogHeading("Leave with role changes not fully saved?")
        fireEvent.click(screen.getByRole("button", { name: "Leave", hidden: true }))
        expect(await screen.findByText("Home page")).toBeInTheDocument()
        expect(server.calls).toHaveLength(sent)
    })

    it("uses the same truthful question after a partly saved batch, but the ordinary one when nothing was sent", async () => {
        setup()
        replies["revoke:player"] = { status: 503, body: {} }
        await stageAndSave()
        await screen.findByRole("heading", { level: 3, name: "Result" })
        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        expect(await dialogHeading("Leave with role changes not fully saved?")).toBeInTheDocument()
    })
})

describe("B25-B26 wording", () => {
    it("B25 reports stranded worlds as a count only", async () => {
        items = [account("user-1", "Alice Example", ["gm"]), account("user-2", "Bob Example")]
        setup()
        replies["revoke:gm"] = {
            body: { user_id: "user-1", system_role_code: "gm", changed: true, stranded_world_ids: ["w-secret-1", "w-secret-2"] },
        }
        items = [account("user-1", "Alice Example", []), account("user-2", "Bob Example")]
        await openRoles("Alice Example")
        fireEvent.click(box("Game master"))
        fireEvent.click(saveButton())

        await screen.findByRole("heading", { level: 3, name: "Result" })
        expect(ledger("Alice Example")).toEqual([
            "Game master removed. 2 world(s) this account owns now have no manageable Owner.",
        ])
        expect(document.body.textContent).not.toContain("w-secret")
    })

    it("B26 says changes are separate, and never that they were saved together unless every step is saved", async () => {
        setup()
        replies["revoke:player"] = { status: 503, body: {} }
        await openRoles("Alice Example")
        expect(
            screen.getByText("Changes are saved one at a time; some can be saved while others are not."),
        ).toBeInTheDocument()
        fireEvent.click(box("Game master"))
        fireEvent.click(box("Player"))
        fireEvent.click(saveButton())
        await screen.findByRole("heading", { level: 3, name: "Result" })
        const text = within(panel("Alice Example")).getByRole("status").textContent ?? ""
        expect(text).toContain("1 of 2 changes saved.")
        expect(text.toLowerCase()).not.toContain("together")
        expect(text).not.toContain("2 of 2")
    })
})

describe("S01 reset-link departure while the list reload is held", () => {
    // Deterministic: the list GET that follows the issuance is held unresolved, the loading state is asserted, and
    // only then is a departure attempted. (An earlier `it.fails` case here did not hold that GET, so it raced a
    // reload that could already have settled; it was a test defect, not a demonstrated product gap.)
    it("asks before a shell departure while the post-issuance list read is pending, and a departure never repeats the reset POST", async () => {
        setup()
        const gate = deferred()
        let hold = false
        server.on("GET", GET_ACCOUNTS, () => (hold ? gate.promise : { body: { items, next_cursor: null } }))
        server.on("POST", "/admin/accounts/user-1/password-reset", () => {
            hold = true
            return { body: { user_id: "user-1", raw_reset_token: "held-token", expires_at: "2026-10-01T00:00:00Z" } }
        })
        await screen.findByText("Alice Example")
        const resetPosts = () => server.callsTo("POST", "/admin/accounts/user-1/password-reset")

        fireEvent.click(screen.getAllByRole("button", { name: "Issue password reset" })[0]!)
        await screen.findByLabelText("Password-reset link")
        // The list read that follows the issuance is pending: the table is replaced by the loading state.
        await screen.findByText("Loading accounts…")
        expect(listCalls()).toHaveLength(2)
        expect(resetPosts()).toHaveLength(1)
        // react-router's useBlocker registers a guard's blocker in effects after the guard first renders, so a
        // navigation attempted in that first moment is not held (a framework window, not this page's logic; it
        // made this test fail intermittently in a cold process before it waited). Let the registration settle.
        await settle()

        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        expect(await dialogHeading("Leave without the password-reset link?")).toBeInTheDocument()
        expect(screen.getByText("It is shown once and cannot be shown again.")).toBeInTheDocument()
        expect(screen.queryByText("Home page")).toBeNull()

        // Stay keeps the link and the pending read, and sends nothing.
        fireEvent.click(screen.getByRole("button", { name: "Stay", hidden: true }))
        expect(screen.getByLabelText("Password-reset link")).toBeInTheDocument()
        expect(screen.getByText("Loading accounts…")).toBeInTheDocument()
        expect(screen.queryByText("Home page")).toBeNull()
        expect(resetPosts()).toHaveLength(1)

        // Leave departs; the reset request is not repeated.
        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        await dialogHeading("Leave without the password-reset link?")
        fireEvent.click(screen.getByRole("button", { name: "Leave", hidden: true }))
        expect(await screen.findByText("Home page")).toBeInTheDocument()
        expect(document.body.textContent).not.toContain("held-token")
        await act(async () => gate.resolve({ body: { items, next_cursor: null } }))
        await settle()
        expect(resetPosts()).toHaveLength(1)
        expect(listCalls()).toHaveLength(2)
    })
})
