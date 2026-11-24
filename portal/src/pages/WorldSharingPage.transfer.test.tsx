import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { useEffect, useState } from "react"
import type { ReactNode } from "react"
import { Link, RouterProvider, createMemoryRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { AnnouncerContext } from "../components/authoring/announcer"
import { SessionContext } from "../context/SessionContext"
import { WorkspaceHierarchyContext } from "../context/WorkspaceHierarchyContext"
import type { WorkspaceHierarchy } from "../context/WorkspaceHierarchyContext"
import type { SessionBootstrapState } from "../hooks/useSessionBootstrap"
import { bootstrapWith, installMockServer } from "../test/authoringHarness"
import type { FetchCall, MockResponse, MockServer } from "../test/authoringHarness"
import type { SessionBootstrap } from "../types/bootstrap"
import { WorldSharingPage } from "./WorldSharingPage"

// P15-C05-S02: the ownership transfer through the real page, the real mutation and resource hooks, with the network (a
// stubbed fetch), the session and the workspace hierarchy's world read faked. The session is a custom SessionContext
// provider holding a bootstrap state that a test changes (an account switch, an ended session), with mocked refresh and
// reload; the sidebar's refetchWorld is a mock supplied through a test WorkspaceHierarchyContext.Provider. These are page
// tests of how the receipt reacts to those changes, not production session-boundary tests: the real session hook, the
// route session provider, the authenticated layout and the hierarchy provider's own reads are not exercised.
// Announcements are counted exactly through a spy.

const SELF = bootstrapWith().user.user_id
const ACCESS = "/worlds/w1/access"
const TRANSFER = "/worlds/w1/ownership-transfer"
const OTHER_USER = bootstrapWith({ user: { user_id: "user-B", display_name: "Account B" }, csrf_token: "csrf-B" })

const world = (id: string, name: string) => ({
    world_id: id,
    name,
    description: null,
    lifecycle_status: "active",
    row_version: 1,
    primary_timeline_id: "t1",
    capabilities: ["world.view", "world.share", "world.transfer"],
    default_ruleset_id: null,
    allowed_rulesets: [],
    timelines: [],
    managed_campaigns: [],
    available_actions: [],
    blocked_actions: [],
})

function row(id: string, userId: string, name: string, role: string, roleName: string) {
    return {
        world_membership_id: id,
        user_id: userId,
        display_name: name,
        role_code: role,
        role_display_name: roleName,
        granted_at: "2026-10-06T10:00:00Z",
        granted_by_display_name: null,
        account_active: true,
    }
}

function access(overrides: object = {}) {
    return {
        assignments: [
            row("m1", SELF, "Alice Owner", "world_owner", "World owner"),
            row("m2", "u2", "Bob Editor", "world_editor", "World editor"),
        ],
        use_grants: [],
        may_transfer: true,
        ...overrides,
    }
}

const transferred = (retained: string | null = "world_editor") => ({
    world_id: "w1",
    previous_owner_user_id: SELF,
    new_owner_user_id: "u-erin",
    retained_role_code: retained,
})

type Reply = MockResponse | ((call: FetchCall) => MockResponse | Promise<MockResponse>)

let server: MockServer
let current: object
let accessReply: Reply | null
let transferReply: Reply
const announce = vi.fn<(message: string) => void>()
const refetchWorld = vi.fn<() => Promise<unknown>>()
const refresh = vi.fn<() => Promise<boolean>>()
const reload = vi.fn()
let setSession: (state: SessionBootstrapState) => void = () => {}

function authenticated(bootstrap: SessionBootstrap): SessionBootstrapState {
    return { status: "authenticated", bootstrap }
}

function Providers({ children }: { children: ReactNode }) {
    const [state, setState] = useState<SessionBootstrapState>(authenticated(bootstrapWith()))
    useEffect(() => {
        setSession = setState
    }, [])
    return (
        <SessionContext.Provider value={{ state, reload, refresh }}>
            <AnnouncerContext.Provider value={{ announce }}>
                <WorkspaceHierarchyContext.Provider value={{ refetchWorld } as unknown as WorkspaceHierarchy}>
                    {children}
                </WorkspaceHierarchyContext.Provider>
            </AnnouncerContext.Provider>
        </SessionContext.Provider>
    )
}

function Shell({ children }: { children: ReactNode }) {
    return (
        <>
            <nav>
                <Link to="/home">Sidebar home</Link>
                <Link to="/worlds/w2/sharing">Other world</Link>
            </nav>
            {children}
        </>
    )
}

function setup(options: { initialEntry?: string; access?: object } = {}) {
    server = installMockServer()
    current = options.access ?? access()
    accessReply = null
    transferReply = { body: transferred() }
    announce.mockReset()
    refetchWorld.mockReset().mockResolvedValue(undefined)
    refresh.mockReset().mockResolvedValue(true)
    reload.mockReset()
    server.on("GET", "/worlds/w1", { body: world("w1", "Eberron") })
    server.on("GET", "/worlds/w2", { body: world("w2", "Sharn") })
    server.on("GET", "/worlds/w2/access", () => ({
        body: access({ assignments: [row("n1", SELF, "Nia Owner", "world_owner", "World owner")] }),
    }))
    server.on("GET", ACCESS, (call) => {
        if (accessReply !== null) return typeof accessReply === "function" ? accessReply(call) : accessReply
        return { body: current }
    })
    server.on("POST", TRANSFER, (call) => (typeof transferReply === "function" ? transferReply(call) : transferReply))
    const router = createMemoryRouter(
        [
            {
                path: "/worlds/:worldId/sharing",
                element: (
                    <Shell>
                        <WorldSharingPage />
                    </Shell>
                ),
            },
            { path: "/home", element: <p>Home page</p> },
            { path: "/worlds/:worldId", element: <p>World page</p> },
            { path: "/worlds", element: <p>Worlds page</p> },
        ],
        { initialEntries: [options.initialEntry ?? "/worlds/w1/sharing"] },
    )
    const view = render(
        <Providers>
            <RouterProvider router={router} />
        </Providers>,
    )
    return { router, ...view }
}

const posts = () => server.callsTo("POST", TRANSFER)
const reads = () => server.callsTo("GET", ACCESS)
const keyOf = (call: FetchCall) => call.headers["Idempotency-Key"]
const announced = () => announce.mock.calls.map((call) => call[0])
const dialogHeading = (name: string) => screen.findByRole("heading", { name, hidden: true })
const receiptHeading = (name: string) => screen.findByRole("heading", { level: 2, name })

function deferred() {
    let resolve: (value: MockResponse) => void = () => {}
    const promise = new Promise<MockResponse>((r) => (resolve = r))
    return { promise, resolve }
}

const settle = (ms = 25) =>
    act(async () => {
        await new Promise((resolve) => setTimeout(resolve, ms))
    })

async function ready() {
    await screen.findByText("Bob Editor")
}

// Fills the transfer form and opens its confirmation dialog.
async function openTransfer(login = "erin", retain = "world_editor") {
    fireEvent.change(screen.getByRole("textbox", { name: /New owner/ }), { target: { value: login } })
    fireEvent.change(screen.getByRole("combobox", { name: /Keep me on the world as/ }), { target: { value: retain } })
    fireEvent.click(screen.getByRole("button", { name: /Transfer ownership…/ }))
    return screen.findByRole("dialog")
}

async function confirmTransfer(dialog?: HTMLElement) {
    const target = dialog ?? (await screen.findByRole("dialog"))
    fireEvent.click(within(target).getByRole("button", { name: "Transfer ownership" }))
}

async function transferTo(login = "erin", retain = "world_editor") {
    const dialog = await openTransfer(login, retain)
    await confirmTransfer(dialog)
    return dialog
}

const denied = { status: 403, body: { error: { code: "forbidden" } } }

beforeEach(() => {
    current = access()
})

afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
})

describe("D1: what the dialog says the person keeps", () => {
    it("D1 says nothing is kept, and the sharing page is lost, with No role and no other role", async () => {
        setup()
        await ready()
        const dialog = await openTransfer("erin", "")
        expect(
            within(dialog).getByText(/You will have no role on this world and will lose access to its sharing page\./),
        ).toBeInTheDocument()
    })

    it("D1 says the chosen role is kept", async () => {
        setup()
        await ready()
        const dialog = await openTransfer("erin", "world_editor")
        expect(within(dialog).getByText(/You keep the Editor role on this world\./)).toBeInTheDocument()
    })

    it("D1 names the other roles the person already holds when No role is chosen", async () => {
        setup({
            access: access({
                assignments: [
                    row("m1", SELF, "Alice Owner", "world_owner", "World owner"),
                    row("m4", SELF, "Alice Owner", "world_reader", "World reader"),
                    row("m2", "u2", "Bob Editor", "world_editor", "World editor"),
                ],
            }),
        })
        await ready()
        const dialog = await openTransfer("erin", "")
        expect(within(dialog).getByText(/You keep your Reader role on this world\./)).toBeInTheDocument()
        expect(within(dialog).queryByText(/no role on this world/)).toBeNull()
    })
})

describe("S02-1: the confirmation names every role the person will have left", () => {
    const withOwnAndReader = () =>
        access({
            assignments: [
                row("m1", SELF, "Alice Owner", "world_owner", "World owner"),
                row("m4", SELF, "Alice Owner", "world_reader", "World reader"),
                row("m2", "u2", "Bob Editor", "world_editor", "World editor"),
            ],
        })

    it("S02-1 describes both the existing Reader role and the selected Editor role", async () => {
        setup({ access: withOwnAndReader() })
        await ready()
        const dialog = await openTransfer("erin", "world_editor")
        expect(within(dialog).getByText(/You keep your Reader and Editor roles on this world\./)).toBeInTheDocument()
        expect(within(dialog).queryByText(/You will have no role/)).toBeNull()
    })

    it("S02-1 describes a selected role the person already holds only once", async () => {
        setup({
            access: access({
                assignments: [
                    row("m1", SELF, "Alice Owner", "world_owner", "World owner"),
                    row("m4", SELF, "Alice Owner", "world_editor", "World editor"),
                    row("m5", SELF, "Alice Owner", "world_reader", "World reader"),
                    row("m2", "u2", "Bob Editor", "world_editor", "World editor"),
                ],
            }),
        })
        await ready()
        const dialog = await openTransfer("erin", "world_editor")
        const text = within(dialog).getByText(/You keep your .* on this world\./).textContent ?? ""
        expect(text).toContain("You keep your Editor and Reader roles on this world.")
        expect(text.match(/Editor/g)).toHaveLength(1)
        expect(text.match(/Reader/g)).toHaveLength(1)
    })

    it("S02-1 a selected role that is the only role held is described once, as the retained role", async () => {
        setup({
            access: access({
                assignments: [
                    row("m1", SELF, "Alice Owner", "world_owner", "World owner"),
                    row("m4", SELF, "Alice Owner", "world_editor", "World editor"),
                    row("m2", "u2", "Bob Editor", "world_editor", "World editor"),
                ],
            }),
        })
        await ready()
        const dialog = await openTransfer("erin", "world_editor")
        const text = within(dialog).getByText(/You keep the .* on this world\./).textContent ?? ""
        expect(text).toContain("You keep the Editor role on this world.")
        expect(text.match(/Editor/g)).toHaveLength(1)
    })

    it("S02-1 with No role selected still describes the existing Reader role", async () => {
        setup({ access: withOwnAndReader() })
        await ready()
        const dialog = await openTransfer("erin", "")
        expect(within(dialog).getByText(/You keep your Reader role on this world\./)).toBeInTheDocument()
        expect(within(dialog).queryByText(/You will have no role/)).toBeNull()
    })

    it("S02-1 says the person keeps nothing only when no role would remain", async () => {
        setup()
        await ready()
        const dialog = await openTransfer("erin", "")
        expect(
            within(dialog).getByText(/You will have no role on this world and will lose access to its sharing page\./),
        ).toBeInTheDocument()
    })
})

describe("D2-D5: the receipt after a confirmed transfer", () => {
    it("D2 keeps a receipt naming the typed login and the role the server kept, above the access explanation", async () => {
        setup()
        await ready()
        const dialog = await openTransfer("erin", "world_editor")
        accessReply = denied
        await confirmTransfer(dialog)

        const heading = await receiptHeading("Ownership transferred")
        expect(screen.getByText("erin is now an owner of Eberron.")).toBeInTheDocument()
        expect(screen.getByText("You keep the Editor role on this world.")).toBeInTheDocument()
        const receipt = within(heading.closest("section")!)
        expect(receipt.getByRole("link", { name: "Back to the world" })).toHaveAttribute("href", "/worlds/w1")
        expect(receipt.getByRole("link", { name: "Worlds" })).toHaveAttribute("href", "/worlds")
        expect(await screen.findByText(/You do not have access to the sharing list/)).toBeInTheDocument()
        // The receipt comes first, the explanation after it.
        const explanation = screen.getByText(/You do not have access to the sharing list/)
        expect(heading.compareDocumentPosition(explanation) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
        expect(screen.queryByRole("button", { name: /Give role/ })).toBeNull()
    })

    it("D3 takes the kept role from the server's answer, never from the form", async () => {
        setup()
        await ready()
        transferReply = { body: transferred(null) }
        accessReply = { status: 404, body: { error: { code: "not_found" } } }
        await transferTo("erin", "world_reader")
        await receiptHeading("Ownership transferred")
        expect(screen.getByText("No role was kept for you.")).toBeInTheDocument()
        expect(screen.queryByText(/You keep the Reader role/)).toBeNull()
        expect(posts()[0]!.body).toEqual({ login_name: "erin", retain_previous_owner_as: "world_reader" })
    })

    it("D4 refreshes the person's access elsewhere once, as reads only, and never repeats the POST", async () => {
        setup()
        await ready()
        accessReply = denied
        await transferTo()
        await receiptHeading("Ownership transferred")
        await settle()
        expect(refresh).toHaveBeenCalledTimes(1)
        expect(refetchWorld).toHaveBeenCalledTimes(1)
        expect(posts()).toHaveLength(1)
        expect(reload).not.toHaveBeenCalled()
    })

    it("D4 keeps the receipt, announces once and repeats nothing when both refreshes fail", async () => {
        setup()
        await ready()
        refresh.mockRejectedValue(new Error("offline"))
        refetchWorld.mockRejectedValue(new Error("offline"))
        accessReply = denied
        await transferTo()
        await receiptHeading("Ownership transferred")
        await settle()
        expect(screen.getByText("erin is now an owner of Eberron.")).toBeInTheDocument()
        expect(posts()).toHaveLength(1)
        expect(announced().filter((message) => /Ownership transferred/.test(message))).toHaveLength(1)
        expect(reload).not.toHaveBeenCalled()
    })

    it("D5 still shows the receipt, and no sharing control, when the access read fails", async () => {
        setup()
        await ready()
        accessReply = { status: 500, body: {} }
        await transferTo()
        await receiptHeading("Ownership transferred")
        await settle()
        expect(screen.getByText("erin is now an owner of Eberron.")).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /Give role|Allow hosting|Transfer ownership…/ })).toBeNull()
        expect(screen.queryByRole("textbox")).toBeNull()
    })
})

describe("D6-D11: an unknown outcome and a refused retry", () => {
    it("D6 re-reads the access list once after an unknown transfer", async () => {
        setup()
        await ready()
        transferReply = { status: 500, body: {} }
        const before = reads().length
        await transferTo()
        await screen.findByText(/cannot tell whether this was saved/)
        await waitFor(() => expect(reads()).toHaveLength(before + 1))
        await settle()
        expect(reads()).toHaveLength(before + 1)
        expect(posts()).toHaveLength(1)
    })

    it("D7 says the person is still an owner (without claiming failure) and retries with the same body and key once per press", async () => {
        setup()
        await ready()
        transferReply = { status: 500, body: {} }
        await transferTo()
        const dialog = await screen.findByRole("dialog")
        expect(
            await within(dialog).findByText(/You are still an owner of this world, so the transfer does not appear to have been completed\./),
        ).toBeInTheDocument()
        expect(within(dialog).getByText(/does not rule out a transfer still in progress/)).toBeInTheDocument()

        transferReply = { body: transferred() }
        accessReply = denied
        fireEvent.click(within(dialog).getByRole("button", { name: "Retry" }))
        await receiptHeading("Ownership transferred")
        await settle()
        expect(posts()).toHaveLength(2)
        expect(posts()[1]!.body).toEqual(posts()[0]!.body)
        expect(keyOf(posts()[1]!)).toBe(keyOf(posts()[0]!))
    })

    it("D8 says the transfer is not confirmed, with no Retry, when the read is denied, and refreshes access once", async () => {
        setup()
        await ready()
        transferReply = { status: 500, body: {} }
        accessReply = denied
        await transferTo()
        await receiptHeading("Transfer not confirmed")
        expect(
            screen.getByText(
                /We could not confirm that ownership was transferred to erin\. You no longer have owner access to this world, which is what a completed transfer does\./,
            ),
        ).toBeInTheDocument()
        // Losing ownership does not show who received it.
        expect(screen.getByText(/does not show whether erin received ownership/)).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Retry" })).toBeNull()
        expect(screen.queryByText(/Ownership transferred to/)).toBeNull()
        await settle()
        expect(refresh).toHaveBeenCalledTimes(1)
        expect(refetchWorld).toHaveBeenCalledTimes(1)
        expect(announced().filter((message) => message === "Transfer not confirmed.")).toHaveLength(1)
        expect(posts()).toHaveLength(1)
    })

    it("D9 offers Retry and Check again when the read fails, and Check again sends one GET and no POST", async () => {
        setup()
        await ready()
        transferReply = { status: 500, body: {} }
        accessReply = { status: 500, body: {} }
        await transferTo()
        const dialog = await screen.findByRole("dialog")
        const check = await within(dialog).findByRole("button", { name: "Check again" })
        expect(within(dialog).getByRole("button", { name: "Retry" })).toBeInTheDocument()
        const readsBefore = reads().length
        accessReply = null
        fireEvent.click(check)
        await within(dialog).findByText(/You are still an owner of this world/)
        expect(reads()).toHaveLength(readsBefore + 1)
        expect(posts()).toHaveLength(1)
    })

    it("D10 does not report a refused retry as a permission problem: it re-reads and, when denied, says not confirmed", async () => {
        setup()
        await ready()
        transferReply = { status: 500, body: {} }
        await transferTo()
        const dialog = await screen.findByRole("dialog")
        await within(dialog).findByText(/You are still an owner of this world/)

        // The committed transfer's retry is refused (authority first), and the person can no longer read the list.
        transferReply = { status: 403, body: { error: { code: "forbidden" } } }
        // The re-read that follows is held, so what the dialog says while it is pending can be seen.
        const gate = deferred()
        accessReply = () => gate.promise
        fireEvent.click(within(dialog).getByRole("button", { name: "Retry" }))
        expect(await within(dialog).findByText("Checking whether the transfer went through…")).toBeInTheDocument()
        expect(within(dialog).queryByText(/You do not have permission to do this/)).toBeNull()
        expect(within(dialog).queryByRole("button", { name: "Check my session" })).toBeNull()
        await act(async () => gate.resolve(denied))
        await receiptHeading("Transfer not confirmed")
        expect(screen.queryByText(/You do not have permission to do this/)).toBeNull()
        expect(posts()).toHaveLength(2)
        expect(keyOf(posts()[1]!)).toBe(keyOf(posts()[0]!))
    })

    it("D11 re-reads once after a refused first attempt; a denied read shows the terminal, no receipt, and closes the dialog", async () => {
        setup()
        await ready()
        transferReply = { status: 403, body: { error: { code: "forbidden" } } }
        accessReply = denied
        const before = reads().length
        await transferTo()
        expect(await screen.findByText(/You do not have access to the sharing list/)).toBeInTheDocument()
        await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
        expect(screen.queryByRole("heading", { name: /Ownership transferred|Transfer not confirmed/ })).toBeNull()
        expect(reads()).toHaveLength(before + 1)
        expect(posts()).toHaveLength(1)
        expect(announced().filter((message) => /transfer/i.test(message))).toEqual([])
    })

    it.each([
        ["target_requires_system_gm", "A world owner must hold the game master system role."],
        ["invalid_ownership_transfer", "Ownership cannot be transferred to the current owner."],
        ["world_role_target_ineligible", "That account cannot be given this access."],
    ])("D12 keeps the %s sentence and the input, and re-reads nothing", async (code, sentence) => {
        setup()
        await ready()
        transferReply = { status: 409, body: { error: { code } } }
        const before = reads().length
        const dialog = await openTransfer("erin", "world_viewer")
        await confirmTransfer(dialog)
        expect(await within(await screen.findByRole("dialog")).findByText(sentence)).toBeInTheDocument()
        await settle()
        expect(reads()).toHaveLength(before)
        expect(screen.getByRole("textbox", { name: /New owner/ })).toHaveValue("erin")
        expect(screen.getByRole("combobox", { name: /Keep me on the world as/ })).toHaveValue("world_viewer")
        expect(screen.queryByRole("heading", { name: /Ownership transferred|Transfer not confirmed/ })).toBeNull()
        expect(screen.getByRole("heading", { name: "Transfer ownership" })).toBeInTheDocument()
    })
})

describe("D13-D16: no repeat and leaving", () => {
    it("D13 offers no transfer control after a receipt, and a second press while pending sends nothing", async () => {
        setup()
        await ready()
        const gate = deferred()
        transferReply = () => gate.promise
        const dialog = await openTransfer()
        await confirmTransfer(dialog)
        fireEvent.click(within(dialog).getByRole("button", { name: /Transfer ownership|Working/ }))
        await waitFor(() => expect(posts()).toHaveLength(1))
        accessReply = denied
        await act(async () => gate.resolve({ body: transferred() }))
        await receiptHeading("Ownership transferred")
        expect(screen.queryByRole("form", { name: "Transfer ownership" })).toBeNull()
        expect(screen.queryByRole("dialog")).toBeNull()
        expect(screen.queryByRole("button", { name: "Retry" })).toBeNull()
        await settle()
        expect(posts()).toHaveLength(1)
    })

    it("D14 asks before leaving after an unknown, unreconciled transfer; Stay keeps the page and Leave sends nothing", async () => {
        setup()
        await ready()
        transferReply = { status: 500, body: {} }
        await transferTo()
        await screen.findByText(/You are still an owner of this world/)
        const sent = server.calls.length
        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        expect(await dialogHeading("Leave without knowing whether ownership was transferred?")).toBeInTheDocument()
        expect(
            screen.getByText("We could not confirm the transfer to erin. Come back to this page to check."),
        ).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Stay", hidden: true }))
        expect(screen.queryByText("Home page")).toBeNull()
        expect(server.calls).toHaveLength(sent)

        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        await dialogHeading("Leave without knowing whether ownership was transferred?")
        fireEvent.click(screen.getByRole("button", { name: "Leave", hidden: true }))
        expect(await screen.findByText("Home page")).toBeInTheDocument()
        expect(server.calls).toHaveLength(sent)
    })

    it("D15 asks while a transfer is pending, immediately, with exactly one question", async () => {
        const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
        setup()
        await ready()
        const gate = deferred()
        transferReply = () => gate.promise
        await transferTo()
        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        expect(await dialogHeading("Leave while ownership is being transferred?")).toBeInTheDocument()
        expect(screen.getByText("It may still be completed. You will not see the result here.")).toBeInTheDocument()
        expect(document.querySelectorAll("dialog[open]").length).toBeGreaterThanOrEqual(1)
        expect(screen.getAllByRole("heading", { name: /Leave /, hidden: true })).toHaveLength(1)
        expect(warn.mock.calls.filter((call) => String(call[0]).includes("one blocker"))).toEqual([])
        fireEvent.click(screen.getByRole("button", { name: "Stay", hidden: true }))
        accessReply = denied
        await act(async () => gate.resolve({ body: transferred() }))
        await receiptHeading("Ownership transferred")
    })

    it("D16 does not guard a receipt: leaving asks nothing", async () => {
        setup()
        await ready()
        accessReply = denied
        await transferTo()
        await receiptHeading("Ownership transferred")
        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        expect(await screen.findByText("Home page")).toBeInTheDocument()
    })
})

describe("D17-D18: focus and announcements", () => {
    it("D17 moves focus to the receipt heading when the content unmounts with focus lost", async () => {
        setup()
        await ready()
        accessReply = denied
        const dialog = await openTransfer()
        within(dialog).getByRole("button", { name: "Transfer ownership" }).focus()
        await confirmTransfer(dialog)
        const heading = await receiptHeading("Ownership transferred")
        await waitFor(() => expect(heading).toHaveFocus())
        await screen.findByText(/You do not have access to the sharing list/)
        // The access explanation arriving later does not take focus back to the page heading.
        await settle()
        expect(heading).toHaveFocus()
    })

    it("D17 leaves focus alone when the person moved it elsewhere while the request was pending", async () => {
        setup()
        await ready()
        const gate = deferred()
        transferReply = () => gate.promise
        const dialog = await openTransfer()
        await confirmTransfer(dialog)
        await waitFor(() => expect(posts()).toHaveLength(1))
        const sidebar = screen.getByRole("link", { name: "Sidebar home" })
        sidebar.focus()
        accessReply = denied
        await act(async () => gate.resolve({ body: transferred() }))
        await receiptHeading("Ownership transferred")
        await settle()
        expect(sidebar).toHaveFocus()
    })

    it("D17 still focuses the page heading for a denial without a receipt", async () => {
        setup()
        await ready()
        transferReply = { status: 403, body: { error: { code: "forbidden" } } }
        accessReply = denied
        await transferTo()
        await screen.findByText(/You do not have access to the sharing list/)
        await waitFor(() => expect(screen.getByRole("heading", { level: 1, name: "Sharing" })).toHaveFocus())
    })

    it("D18 announces each outcome once, and never the old fixed text as a second announcement", async () => {
        setup()
        await ready()
        accessReply = denied
        await transferTo()
        await receiptHeading("Ownership transferred")
        await settle()
        expect(announced()).toEqual(["Ownership transferred to erin. You keep the Editor role on this world."])
    })

    it("D18 announces once when the read-back shows the list again instead of a denial", async () => {
        setup()
        await ready()
        await transferTo()
        await receiptHeading("Ownership transferred")
        await settle()
        expect(announced()).toEqual(["Ownership transferred to erin. You keep the Editor role on this world."])
    })
})

describe("D19: scope of the receipt (real session and access transitions)", () => {
    async function receipt() {
        setup()
        await ready()
        accessReply = denied
        await transferTo()
        await receiptHeading("Ownership transferred")
    }

    it("D19 survives losing sharing authority alone (more access reads, a refresh) and keeps its words", async () => {
        await receipt()
        // The read now answers 404 instead of 403, and the session is refreshed in place with the same account.
        accessReply = { status: 404, body: { error: { code: "not_found" } } }
        act(() => setSession(authenticated(bootstrapWith({ csrf_token: "csrf-new" }))))
        await settle()
        expect(screen.getByText("erin is now an owner of Eberron.")).toBeInTheDocument()
        expect(screen.getByText("You keep the Editor role on this world.")).toBeInTheDocument()
    })

    it("D19 is removed when the signed-in account changes, and does not come back for the first account", async () => {
        await receipt()
        act(() => setSession(authenticated(OTHER_USER)))
        await waitFor(() => expect(screen.queryByRole("heading", { name: "Ownership transferred" })).toBeNull())
        expect(screen.queryByText("erin is now an owner of Eberron.")).toBeNull()
        act(() => setSession(authenticated(bootstrapWith())))
        await settle()
        expect(screen.queryByRole("heading", { name: "Ownership transferred" })).toBeNull()
        expect(screen.queryByText("erin is now an owner of Eberron.")).toBeNull()
    })

    it("D19 is removed when the session ends", async () => {
        await receipt()
        act(() => setSession({ status: "unauthenticated" }))
        await waitFor(() => expect(screen.queryByRole("heading", { name: "Ownership transferred" })).toBeNull())
        act(() => setSession(authenticated(bootstrapWith())))
        await settle()
        expect(screen.queryByRole("heading", { name: "Ownership transferred" })).toBeNull()
    })

    it("D19 is not shown on another world's Sharing page, and not when returning to the first world", async () => {
        setup()
        await ready()
        accessReply = denied
        await transferTo()
        await receiptHeading("Ownership transferred")
        fireEvent.click(screen.getByRole("link", { name: "Other world" }))
        expect(await screen.findByText("Nia Owner")).toBeInTheDocument()
        expect(screen.queryByRole("heading", { name: "Ownership transferred" })).toBeNull()
        expect(screen.queryByText("erin is now an owner of Eberron.")).toBeNull()
    })

    it("D19 records nothing for a late transfer answer after the world changed", async () => {
        setup()
        await ready()
        const gate = deferred()
        transferReply = () => gate.promise
        await transferTo()
        await waitFor(() => expect(posts()).toHaveLength(1))
        fireEvent.click(screen.getByRole("link", { name: "Other world" }))
        fireEvent.click(await screen.findByRole("button", { name: "Leave", hidden: true }))
        expect(await screen.findByText("Nia Owner")).toBeInTheDocument()
        await act(async () => gate.resolve({ body: transferred() }))
        await settle()
        expect(screen.queryByRole("heading", { name: /Ownership transferred|Transfer not confirmed/ })).toBeNull()
        expect(announced()).toEqual([])
        expect(refresh).not.toHaveBeenCalled()
        expect(posts()).toHaveLength(1)
    })
})

describe("D20: the last-owner invariant", () => {
    it("D20 never shows a world without an owner after a refused transfer, and still explains world_owner_required", async () => {
        setup()
        await ready()
        transferReply = { status: 409, body: { error: { code: "target_requires_system_gm" } } }
        const dialog = await openTransfer()
        await confirmTransfer(dialog)
        await within(await screen.findByRole("dialog")).findByText("A world owner must hold the game master system role.")
        expect(screen.getAllByText("Alice Owner").length).toBeGreaterThan(0)
        server.on("POST", "/worlds/w1/roles/m1/end", { status: 409, body: { error: { code: "world_owner_required" } } })
        fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
        await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
        fireEvent.click(screen.getByRole("button", { name: /End role for Alice Owner/ }))
        const endDialog = await screen.findByRole("dialog")
        fireEvent.click(within(endDialog).getByRole("button", { name: "End role" }))
        expect(await within(await screen.findByRole("dialog")).findByText(/A world must keep at least one owner/)).toBeInTheDocument()
    })
})
