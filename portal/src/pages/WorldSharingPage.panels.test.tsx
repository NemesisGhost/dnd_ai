import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { Link } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { useSession } from "../context/SessionContext"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { FetchCall, MockResponse, MockServer } from "../test/authoringHarness"
import { WorldSharingPage } from "./WorldSharingPage"

// P15-C05-S01: the role and hosting panels through the real page, the real mutation, resource and feedback
// components, with only the network (a stubbed fetch) and the session faked. A sidebar link sits beside the page so a
// departure by something other than the page's own controls is covered.

const OTHER_USER = bootstrapWith({ user: { user_id: "user-B", display_name: "Account B" }, csrf_token: "csrf-B" })

function world(id: string, name: string) {
    return {
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
    }
}

function member(id: string, name: string, role = "world_editor", roleName = "World editor") {
    return {
        world_membership_id: id,
        user_id: `u-${id}`,
        display_name: name,
        role_code: role,
        role_display_name: roleName,
        granted_at: "2026-10-06T10:00:00Z",
        granted_by_display_name: null,
        account_active: true,
    }
}

function grant(id: string, name: string) {
    return {
        world_use_grant_id: id,
        user_id: `u-${id}`,
        display_name: name,
        granted_at: "2026-10-06T10:10:00Z",
        granted_by_display_name: "Alice Owner",
        account_active: true,
    }
}

function access(overrides: object = {}) {
    return {
        assignments: [
            member("m1", "Alice Owner", "world_owner", "World owner"),
            member("m2", "Bob Editor"),
            member("m3", "Dan Editor"),
        ],
        use_grants: [grant("g1", "Cara Host"), grant("g2", "Dev Host")],
        may_transfer: true,
        ...overrides,
    }
}

const change = (overrides: object = {}) => ({
    world_id: "w1",
    user_id: "u9",
    record_id: "r9",
    role_code: "world_editor",
    changed: true,
    ...overrides,
})

type Reply = MockResponse | ((call: FetchCall) => MockResponse | Promise<MockResponse>)

let server: MockServer
let current: object
let replies: Record<string, Reply>
const ROLES = "/worlds/w1/roles"
const USE = "/worlds/w1/use-grants"
const ACCESS = "/worlds/w1/access"

function Shell({ children }: { children: React.ReactNode }) {
    const { refresh } = useSession()
    return (
        <>
            <nav>
                <Link to="/home">Sidebar home</Link>
                <Link to="/worlds/w2/sharing">Other world</Link>
                <button type="button" onClick={() => void refresh()}>
                    Switch account
                </button>
            </nav>
            {children}
        </>
    )
}

function setup(options: { access?: object; bootstrapAfterSwitch?: ReturnType<typeof bootstrapWith> } = {}) {
    server = installMockServer()
    current = options.access ?? access()
    replies = {}
    server.on("GET", "/worlds/w1", { body: world("w1", "Eberron") })
    server.on("GET", "/worlds/w2", { body: world("w2", "Sharn") })
    server.on("GET", "/worlds/w2/access", () => ({ body: access({ assignments: [member("n1", "Nia Owner", "world_owner")], use_grants: [] }) }))
    server.on("GET", ACCESS, () => ({ body: current }))
    // Every write answers from `replies`, keyed by its path; the default is a confirmed change.
    server.on("POST", /^\/worlds\/w[12]\/(roles|use-grants|ownership-transfer)/, (call) => {
        const reply = replies[call.path]
        if (reply !== undefined) return typeof reply === "function" ? reply(call) : reply
        return { status: 201, body: change() }
    })
    return renderAuthoringRoutes({
        initialEntry: "/worlds/w1/sharing",
        routes: [
            {
                path: "/worlds/:worldId/sharing",
                element: (
                    <Shell>
                        <WorldSharingPage />
                    </Shell>
                ),
            },
            { path: "/home", element: <p>Home page</p> },
        ],
        onRefresh: options.bootstrapAfterSwitch === undefined ? undefined : async () => options.bootstrapAfterSwitch!,
    })
}

const posts = (path: string) => server.callsTo("POST", path)
const reads = () => server.callsTo("GET", ACCESS)
const loginField = () => within(screen.getByRole("form", { name: "Give someone a role" })).getByRole("textbox", { name: "Login name" })
const roleField = () => screen.getByRole("combobox", { name: "Role" })
// The hosting field's label is asserted exactly in C17; elsewhere it is found by its stable first words.
const hostField = () => within(screen.getByRole("form", { name: "Allow someone to host campaigns" })).getByRole("textbox", { name: /^Login name/ })
const announcer = () => screen.getByTestId("authoring-announcer")
const dialogHeading = (name: string) => screen.findByRole("heading", { name, hidden: true })
const keyOf = (call: FetchCall) => call.headers["Idempotency-Key"]

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

function giveRole(login: string, role?: string) {
    fireEvent.change(loginField(), { target: { value: login } })
    if (role !== undefined) fireEvent.change(roleField(), { target: { value: role } })
    fireEvent.click(screen.getByRole("button", { name: "Give role" }))
}

function allowHosting(login: string) {
    fireEvent.change(hostField(), { target: { value: login } })
    fireEvent.click(screen.getByRole("button", { name: "Allow hosting" }))
}

async function endRole(name: string) {
    fireEvent.click(screen.getByRole("button", { name: new RegExp(`End role for ${name}`) }))
    const dialog = await screen.findByRole("dialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "End role" }))
    return dialog
}

async function revoke(name: string) {
    fireEvent.click(screen.getByRole("button", { name: `Revoke permission for ${name}` }))
    const dialog = await screen.findByRole("dialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "Revoke permission" }))
    return dialog
}

beforeEach(() => {
    current = access()
})

afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
})

describe("C1-C4: an operation is its target, and the typed input survives", () => {
    it("C1 sends a different login as a new request with a new key and never re-sends the earlier one", async () => {
        setup()
        replies[ROLES] = { status: 500, body: {} }
        await ready()
        giveRole("dana")
        await screen.findByText(/cannot tell whether this was saved/)
        expect(posts(ROLES)).toHaveLength(1)

        replies[ROLES] = { status: 201, body: change() }
        giveRole("erin")
        await waitFor(() => expect(posts(ROLES)).toHaveLength(2))
        const [first, second] = posts(ROLES)
        expect(first!.body).toEqual({ login_name: "dana", role_code: "world_editor" })
        expect(second!.body).toEqual({ login_name: "erin", role_code: "world_editor" })
        expect(keyOf(second!)).not.toBe(keyOf(first!))
        await settle()
        expect(posts(ROLES)).toHaveLength(2)
    })

    it("C1 treats a different role for the same login as a new request too", async () => {
        setup()
        replies[ROLES] = { status: 500, body: {} }
        await ready()
        giveRole("dana", "world_editor")
        await screen.findByText(/cannot tell whether this was saved/)
        replies[ROLES] = { status: 201, body: change() }
        giveRole("dana", "world_reader")
        await waitFor(() => expect(posts(ROLES)).toHaveLength(2))
        expect(posts(ROLES)[1]!.body).toEqual({ login_name: "dana", role_code: "world_reader" })
        expect(keyOf(posts(ROLES)[1]!)).not.toBe(keyOf(posts(ROLES)[0]!))
    })

    it("C2 sends the chosen row's own request after an unknown end-role for another row", async () => {
        setup()
        replies["/worlds/w1/roles/m2/end"] = { status: 500, body: {} }
        replies["/worlds/w1/roles/m3/end"] = { status: 200, body: change({ record_id: "m3" }) }
        await ready()
        const dialog = await endRole("Bob Editor")
        await within(dialog).findByText(/cannot tell whether this was saved/)
        fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
        await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())

        await endRole("Dan Editor")
        await waitFor(() => expect(posts("/worlds/w1/roles/m3/end")).toHaveLength(1))
        expect(posts("/worlds/w1/roles/m2/end")).toHaveLength(1)
        // A different row is a new request: its key is not the unresolved attempt's.
        expect(keyOf(posts("/worlds/w1/roles/m3/end")[0]!)).not.toBe(keyOf(posts("/worlds/w1/roles/m2/end")[0]!))
    })

    it("C2 does the same for two hosting revokes", async () => {
        setup()
        replies["/worlds/w1/use-grants/g1/revoke"] = { status: 500, body: {} }
        replies["/worlds/w1/use-grants/g2/revoke"] = { status: 200, body: change({ record_id: "g2" }) }
        await ready()
        const dialog = await revoke("Cara Host")
        await within(dialog).findByText(/cannot tell whether this was saved/)
        fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
        await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())

        await revoke("Dev Host")
        await waitFor(() => expect(posts("/worlds/w1/use-grants/g2/revoke")).toHaveLength(1))
        expect(posts("/worlds/w1/use-grants/g1/revoke")).toHaveLength(1)
        expect(keyOf(posts("/worlds/w1/use-grants/g2/revoke")[0]!)).not.toBe(keyOf(posts("/worlds/w1/use-grants/g1/revoke")[0]!))
    })

    it("C3a (passes at baseline) retries with the Retry button using the same body and key, once per press", async () => {
        setup()
        replies[ROLES] = { status: 500, body: {} }
        await ready()
        giveRole("dana", "world_reviewer")
        await screen.findByText(/cannot tell whether this was saved/)

        replies[ROLES] = { status: 201, body: change() }
        fireEvent.click(screen.getByRole("button", { name: "Retry" }))
        await waitFor(() => expect(posts(ROLES)).toHaveLength(2))
        await settle()
        expect(posts(ROLES)).toHaveLength(2)
        expect(posts(ROLES)[1]!.body).toEqual(posts(ROLES)[0]!.body)
        expect(keyOf(posts(ROLES)[1]!)).toBe(keyOf(posts(ROLES)[0]!))
    })

    it("C3b (fails at baseline: the login was cleared) pressing Give role again with the unchanged login and role replays the same key", async () => {
        setup()
        replies[ROLES] = { status: 500, body: {} }
        await ready()
        giveRole("dana")
        await screen.findByText(/cannot tell whether this was saved/)
        replies[ROLES] = { status: 201, body: change() }
        fireEvent.click(screen.getByRole("button", { name: "Give role" }))
        await waitFor(() => expect(posts(ROLES)).toHaveLength(2))
        expect(keyOf(posts(ROLES)[1]!)).toBe(keyOf(posts(ROLES)[0]!))
    })

    it("C4 keeps the login and the role after an unknown outcome and after a refusal", async () => {
        setup()
        replies[ROLES] = { status: 500, body: {} }
        await ready()
        giveRole("dana", "world_reviewer")
        await screen.findByText(/cannot tell whether this was saved/)
        expect(loginField()).toHaveValue("dana")
        expect(roleField()).toHaveValue("world_reviewer")

        replies[ROLES] = { status: 409, body: { error: { code: "world_role_target_ineligible" } } }
        giveRole("erin", "world_reader")
        await screen.findByText("That account cannot be given this access.")
        expect(loginField()).toHaveValue("erin")
        expect(roleField()).toHaveValue("world_reader")
    })

    it("C4 keeps the hosting login after an unknown outcome", async () => {
        setup()
        replies[USE] = { status: 500, body: {} }
        await ready()
        allowHosting("dana")
        await screen.findByText(/cannot tell whether this was saved/)
        expect(hostField()).toHaveValue("dana")
    })
})

describe("C5-C8: what a confirmed change says", () => {
    it("C5 clears the login after a confirmed give-role, but keeps what the person typed meanwhile", async () => {
        setup()
        const gate = deferred()
        replies[ROLES] = () => gate.promise
        await ready()
        giveRole("dana")
        await waitFor(() => expect(posts(ROLES)).toHaveLength(1))
        fireEvent.change(loginField(), { target: { value: "erin" } })
        await act(async () => gate.resolve({ status: 201, body: change() }))
        await waitFor(() => expect(announcer()).toHaveTextContent("dana now has the Editor role on this world."))
        expect(loginField()).toHaveValue("erin")
    })

    it("C5-1 keeps a newer edit whose trimmed login equals the submitted one (dana, then dana plus a space)", async () => {
        setup()
        const gate = deferred()
        replies[ROLES] = () => gate.promise
        await ready()
        giveRole("dana")
        await waitFor(() => expect(posts(ROLES)).toHaveLength(1))
        fireEvent.change(loginField(), { target: { value: "dana " } })
        await act(async () => gate.resolve({ status: 201, body: change() }))
        await waitFor(() => expect(announcer()).toHaveTextContent("dana now has the Editor role on this world."))
        expect(loginField()).toHaveValue("dana ")
        // The request that was confirmed is the one that was submitted, unchanged.
        expect(posts(ROLES)[0]!.body).toEqual({ login_name: "dana", role_code: "world_editor" })
    })

    it("C5-1 keeps the hosting field for the same whitespace edit", async () => {
        setup()
        const gate = deferred()
        replies[USE] = () => gate.promise
        await ready()
        allowHosting("dana")
        await waitFor(() => expect(posts(USE)).toHaveLength(1))
        fireEvent.change(hostField(), { target: { value: "dana " } })
        await act(async () => gate.resolve({ status: 201, body: change() }))
        await waitFor(() => expect(announcer()).toHaveTextContent("dana may now host campaigns on this world."))
        expect(hostField()).toHaveValue("dana ")
        expect(posts(USE)[0]!.body).toEqual({ login_name: "dana" })
    })

    it("C5-1 keeps the field when it was edited away and back to the submitted text while the request was pending", async () => {
        setup()
        const gate = deferred()
        replies[ROLES] = () => gate.promise
        await ready()
        giveRole("dana")
        await waitFor(() => expect(posts(ROLES)).toHaveLength(1))
        fireEvent.change(loginField(), { target: { value: "danaX" } })
        fireEvent.change(loginField(), { target: { value: "dana" } })
        await act(async () => gate.resolve({ status: 201, body: change() }))
        await waitFor(() => expect(announcer()).toHaveTextContent("dana now has the Editor role on this world."))
        expect(loginField()).toHaveValue("dana")
    })

    it("C5-1 edit away and back is kept for the hosting field too", async () => {
        setup()
        const gate = deferred()
        replies[USE] = () => gate.promise
        await ready()
        allowHosting("dana")
        await waitFor(() => expect(posts(USE)).toHaveLength(1))
        fireEvent.change(hostField(), { target: { value: "danaX" } })
        fireEvent.change(hostField(), { target: { value: "dana" } })
        await act(async () => gate.resolve({ status: 201, body: change() }))
        await waitFor(() => expect(announcer()).toHaveTextContent("dana may now host campaigns on this world."))
        expect(hostField()).toHaveValue("dana")
    })

    it("C5-1 an untouched confirmed hosting field still clears", async () => {
        setup()
        await ready()
        allowHosting("dana")
        await waitFor(() => expect(announcer()).toHaveTextContent("dana may now host campaigns on this world."))
        expect(hostField()).toHaveValue("")
    })

    it("C5-1 a Retry after an edit sends the exact body and key, and the edit is still kept", async () => {
        setup()
        replies[ROLES] = { status: 500, body: {} }
        await ready()
        giveRole("dana")
        await screen.findByText(/cannot tell whether this was saved/)
        fireEvent.change(loginField(), { target: { value: "dana " } })
        replies[ROLES] = { status: 201, body: change() }
        fireEvent.click(screen.getByRole("button", { name: "Retry" }))
        await waitFor(() => expect(announcer()).toHaveTextContent("dana now has the Editor role on this world."))
        expect(posts(ROLES)).toHaveLength(2)
        expect(posts(ROLES)[1]!.body).toEqual(posts(ROLES)[0]!.body)
        expect(keyOf(posts(ROLES)[1]!)).toBe(keyOf(posts(ROLES)[0]!))
        expect(loginField()).toHaveValue("dana ")
    })

    it("C5 clears the login when it still holds the confirmed one", async () => {
        setup()
        await ready()
        giveRole("dana")
        await waitFor(() => expect(announcer()).toHaveTextContent("dana now has the Editor role on this world."))
        expect(loginField()).toHaveValue("")
    })

    it("C6 says nothing changed when the server answers changed:false", async () => {
        setup()
        replies[ROLES] = { status: 200, body: change({ changed: false }) }
        await ready()
        giveRole("dana")
        await waitFor(() =>
            expect(announcer()).toHaveTextContent("dana already had the Editor role on this world. Nothing changed."),
        )
        expect(announcer()).not.toHaveTextContent("now has")
    })

    it("C6 says the role was given when the server answers changed:true", async () => {
        setup()
        await ready()
        giveRole("dana")
        await waitFor(() => expect(announcer()).toHaveTextContent("dana now has the Editor role on this world."))
    })

    it("C7 says what hosting did, for changed:true and changed:false", async () => {
        setup()
        await ready()
        allowHosting("dana")
        await waitFor(() => expect(announcer()).toHaveTextContent("dana may now host campaigns on this world."))
        replies[USE] = { status: 200, body: change({ changed: false }) }
        allowHosting("erin")
        await waitFor(() =>
            expect(announcer()).toHaveTextContent("erin could already host campaigns on this world. Nothing changed."),
        )
    })

    it("C8 names the row's person and role when a role ends or hosting is revoked", async () => {
        setup()
        replies["/worlds/w1/roles/m2/end"] = { status: 200, body: change({ record_id: "m2" }) }
        replies["/worlds/w1/use-grants/g1/revoke"] = { status: 200, body: change({ record_id: "g1" }) }
        await ready()
        await endRole("Bob Editor")
        await waitFor(() => expect(announcer()).toHaveTextContent("Bob Editor's Editor role on this world has ended."))
        await revoke("Cara Host")
        await waitFor(() =>
            expect(announcer()).toHaveTextContent("Cara Host can no longer start new campaigns on this world."),
        )
    })
})

describe("C9-C16: refusals, unknown outcomes and their read-backs", () => {
    it.each([
        [ROLES, "world_role_target_ineligible", "That account cannot be given this access.", "give"],
        [ROLES, "target_requires_system_gm", "A world owner must hold the game master system role.", "owner"],
    ])("C9 shows the server's sentence for %s %s without re-reading or offering Retry", async (path, code, sentence, how) => {
        setup()
        replies[path] = { status: 409, body: { error: { code } } }
        await ready()
        giveRole("dana", how === "owner" ? "world_owner" : undefined)
        await screen.findByText(sentence)
        expect(screen.queryByRole("button", { name: "Retry" })).toBeNull()
        expect(reads()).toHaveLength(1)
    })

    it("C9 shows the last-owner sentence for world_owner_required with no re-read and no Retry", async () => {
        setup()
        replies["/worlds/w1/roles/m1/end"] = { status: 409, body: { error: { code: "world_owner_required" } } }
        await ready()
        const dialog = await endRole("Alice Owner")
        await within(dialog).findByText(/A world must keep at least one owner/)
        expect(within(dialog).queryByRole("button", { name: "Retry" })).toBeNull()
        expect(reads()).toHaveLength(1)
    })

    it("C10 re-reads the list once after a 403 on revoke; a denied read drops the controls and moves focus to the heading", async () => {
        setup()
        replies["/worlds/w1/use-grants/g1/revoke"] = { status: 403, body: { error: { code: "forbidden" } } }
        await ready()
        fireEvent.click(screen.getByRole("button", { name: "Revoke permission for Cara Host" }))
        const dialog = await screen.findByRole("dialog")
        server.on("GET", ACCESS, { status: 403, body: { error: { code: "forbidden" } } })
        fireEvent.click(within(dialog).getByRole("button", { name: "Revoke permission" }))

        expect(await screen.findByText(/You do not have access to the sharing list/)).toBeInTheDocument()
        await waitFor(() => expect(screen.getByRole("heading", { level: 1, name: "Sharing" })).toHaveFocus())
        expect(screen.queryByRole("button", { name: "Give role" })).toBeNull()
        expect(posts("/worlds/w1/use-grants/g1/revoke")).toHaveLength(1)
        expect(reads()).toHaveLength(2)
    })

    it("C11 re-reads once after a 404 on end-role and reports a row that had already ended", async () => {
        setup()
        replies["/worlds/w1/roles/m2/end"] = { status: 404, body: { error: { code: "not_found" } } }
        await ready()
        fireEvent.click(screen.getByRole("button", { name: /End role for Bob Editor/ }))
        const dialog = await screen.findByRole("dialog")
        current = access({ assignments: [member("m1", "Alice Owner", "world_owner", "World owner"), member("m3", "Dan Editor")] })
        fireEvent.click(within(dialog).getByRole("button", { name: "End role" }))

        // Shown on the page and announced.
        expect(
            (await screen.findAllByText("Bob Editor's Editor role had already ended. The list has been updated.")).length,
        ).toBeGreaterThanOrEqual(1)
        await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
        expect(screen.queryByText("Bob Editor")).toBeNull()
        expect(posts("/worlds/w1/roles/m2/end")).toHaveLength(1)
        expect(reads()).toHaveLength(2)
    })

    it("C12 keeps the unavailable message with the current list when the re-read still lists the row", async () => {
        setup()
        replies["/worlds/w1/roles/m2/end"] = { status: 404, body: { error: { code: "not_found" } } }
        await ready()
        const dialog = await endRole("Bob Editor")
        await within(dialog).findByText("This record no longer exists, or you can no longer access it.")
        expect(reads()).toHaveLength(2)
        expect(screen.getByText("Bob Editor")).toBeInTheDocument()
        expect(posts("/worlds/w1/roles/m2/end")).toHaveLength(1)
    })

    it("C13 reports an unknown end-role whose row is gone on the re-read: announced once, no Retry, one POST", async () => {
        setup()
        replies["/worlds/w1/roles/m2/end"] = { status: 500, body: {} }
        await ready()
        fireEvent.click(screen.getByRole("button", { name: /End role for Bob Editor/ }))
        const dialog = await screen.findByRole("dialog")
        current = access({ assignments: [member("m1", "Alice Owner", "world_owner", "World owner"), member("m3", "Dan Editor")] })
        fireEvent.click(within(dialog).getByRole("button", { name: "End role" }))

        expect((await screen.findAllByText("Bob Editor's Editor role has ended.")).length).toBeGreaterThanOrEqual(1)
        await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
        expect(screen.queryByRole("button", { name: "Retry" })).toBeNull()
        expect(announcer().textContent!.match(/Bob Editor's Editor role has ended\./g)).toHaveLength(1)
        expect(posts("/worlds/w1/roles/m2/end")).toHaveLength(1)
        expect(reads()).toHaveLength(2)
    })

    it("C14 keeps the unknown message, says the row is still listed and retries with the same key", async () => {
        setup()
        replies["/worlds/w1/roles/m2/end"] = { status: 500, body: {} }
        await ready()
        const dialog = await endRole("Bob Editor")
        await within(dialog).findByText(/cannot tell whether this was saved/)
        expect(await within(dialog).findByText("It is still listed.")).toBeInTheDocument()
        expect(reads()).toHaveLength(2)

        replies["/worlds/w1/roles/m2/end"] = { status: 200, body: change({ record_id: "m2" }) }
        fireEvent.click(within(dialog).getByRole("button", { name: "Retry" }))
        await waitFor(() => expect(posts("/worlds/w1/roles/m2/end")).toHaveLength(2))
        const [first, second] = posts("/worlds/w1/roles/m2/end")
        expect(keyOf(second!)).toBe(keyOf(first!))
    })

    it("C14 a superseded re-read of an earlier unknown end-role establishes nothing and cannot replace newer feedback", async () => {
        setup()
        replies["/worlds/w1/roles/m2/end"] = { status: 500, body: {} }
        replies["/worlds/w1/roles/m3/end"] = { status: 200, body: change({ record_id: "m3" }) }
        await ready()
        // The re-read that follows the unknown outcome is held, and would say Bob is gone if it were ever applied.
        const held = deferred()
        let readsSeen = 0
        server.on("GET", ACCESS, () => {
            readsSeen += 1
            return readsSeen === 1
                ? held.promise
                : { body: current }
        })
        const dialog = await endRole("Bob Editor")
        await within(dialog).findByText(/cannot tell whether this was saved/)
        await waitFor(() => expect(readsSeen).toBe(1))
        fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
        await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())

        // A newer operation on another row is confirmed meanwhile.
        current = access({ assignments: [member("m1", "Alice Owner", "world_owner", "World owner"), member("m2", "Bob Editor")] })
        await endRole("Dan Editor")
        await waitFor(() => expect(announcer()).toHaveTextContent("Dan Editor's Editor role on this world has ended."))

        // The held, earlier read now answers with a list without Bob: it was superseded and says nothing.
        await act(async () =>
            held.resolve({ body: access({ assignments: [member("m1", "Alice Owner", "world_owner", "World owner")] }) }),
        )
        await settle()
        expect(announcer()).not.toHaveTextContent(/Bob Editor's Editor role has ended/)
        expect(screen.queryByText("Bob Editor's Editor role has ended.")).toBeNull()
        expect(screen.getByText("Bob Editor")).toBeInTheDocument()
        expect(screen.queryByText("Dan Editor")).toBeNull()
        expect(posts("/worlds/w1/roles/m2/end")).toHaveLength(1)
    })

    it("C15 re-reads the list once after an unknown give-role and keeps the unknown message and the login", async () => {
        setup()
        replies[ROLES] = { status: 500, body: {} }
        await ready()
        giveRole("dana")
        await screen.findByText(/cannot tell whether this was saved/)
        await waitFor(() => expect(reads()).toHaveLength(2))
        await settle()
        expect(reads()).toHaveLength(2)
        expect(loginField()).toHaveValue("dana")
        expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument()
        expect(announcer()).not.toHaveTextContent(/now has|already had/)
    })

    it("C15 does not treat a failed re-read after an unknown end-role as proof of anything", async () => {
        setup()
        replies["/worlds/w1/roles/m2/end"] = { status: 500, body: {} }
        await ready()
        fireEvent.click(screen.getByRole("button", { name: /End role for Bob Editor/ }))
        const dialog = await screen.findByRole("dialog")
        server.on("GET", ACCESS, { status: 500, body: {} })
        fireEvent.click(within(dialog).getByRole("button", { name: "End role" }))
        await within(dialog).findByText(/cannot tell whether this was saved/)
        await waitFor(() => expect(reads()).toHaveLength(2))
        await settle()
        // The row is still on the page (the last list stays), nothing claims it ended, and Retry is still safe.
        expect(screen.getByText("Bob Editor")).toBeInTheDocument()
        expect(screen.queryByText(/has ended|had already ended/)).toBeNull()
        expect(within(dialog).getByRole("button", { name: "Retry" })).toBeInTheDocument()
        expect(within(dialog).queryByText("It is still listed.")).toBeNull()
    })

    it("C16 reports a saved change whose list re-read fails, with the truthful sentence and a read-only recovery", async () => {
        setup()
        await ready()
        fireEvent.change(loginField(), { target: { value: "dana" } })
        server.on("GET", ACCESS, { status: 500, body: {} })
        fireEvent.click(screen.getByRole("button", { name: "Give role" }))
        expect(
            await screen.findByText(/dana now has the Editor role on this world\. The latest sharing list could not be loaded/),
        ).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Give role" })).toBeDisabled()
        server.on("GET", ACCESS, () => ({ body: current }))
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        await waitFor(() => expect(screen.getByRole("button", { name: "Give role" })).toBeEnabled())
        expect(posts(ROLES)).toHaveLength(1)
    })
})

describe("C17: hosting copy and no lookup", () => {
    it("C17 labels the field Login name, says only a game master can use it, and sends nothing on typing", async () => {
        setup()
        await ready()
        const before = server.calls.length
        fireEvent.change(hostField(), { target: { value: "dana" } })
        expect(server.calls).toHaveLength(before)
        expect(
            screen.getByText("Only an account with the game master system role can use it to start a campaign."),
        ).toBeInTheDocument()
        expect(
            within(screen.getByRole("form", { name: "Allow someone to host campaigns" })).getByRole("textbox", { name: "Login name" }),
        ).toBe(hostField())
        expect(screen.queryByText("Login name of a game master")).toBeNull()
        expect(screen.getByText(/Lets a game master start a campaign on this world and nothing else/)).toBeInTheDocument()
    })
})

describe("C18-C20: leaving", () => {
    it("C18 asks before a departure while a write is pending, immediately and without a wait; Stay keeps the outcome, Leave sends nothing more", async () => {
        setup()
        const gate = deferred()
        replies[ROLES] = () => gate.promise
        await ready()
        giveRole("dana")
        // No wait: the guard protects the very commit in which the write became pending.
        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        expect(await dialogHeading("Leave while this change is being saved?")).toBeInTheDocument()
        expect(screen.getByText("It may still be applied. You will not see the result here.")).toBeInTheDocument()
        expect(screen.queryByText("Home page")).toBeNull()

        fireEvent.click(screen.getByRole("button", { name: "Stay", hidden: true }))
        await act(async () => gate.resolve({ status: 201, body: change() }))
        await waitFor(() => expect(announcer()).toHaveTextContent("dana now has the Editor role on this world."))
        expect(posts(ROLES)).toHaveLength(1)
    })

    it("C18 Leave navigates and sends nothing more", async () => {
        setup()
        const gate = deferred()
        replies[ROLES] = () => gate.promise
        await ready()
        giveRole("dana")
        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        await dialogHeading("Leave while this change is being saved?")
        fireEvent.click(screen.getByRole("button", { name: "Leave", hidden: true }))
        expect(await screen.findByText("Home page")).toBeInTheDocument()
        await act(async () => gate.resolve({ status: 201, body: change() }))
        await settle()
        expect(posts(ROLES)).toHaveLength(1)
        expect(reads()).toHaveLength(1)
    })

    it("C19 asks before leaving with an unresolved unknown give-role, but not for typed unsent text", async () => {
        setup()
        replies[ROLES] = { status: 500, body: {} }
        await ready()
        giveRole("dana")
        await screen.findByText(/cannot tell whether this was saved/)
        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        expect(await dialogHeading("Leave without knowing whether the change was saved?")).toBeInTheDocument()
        expect(
            screen.getByText("We could not confirm whether dana was given access. Check the list on this page later."),
        ).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Stay", hidden: true }))
        expect(posts(ROLES)).toHaveLength(1)
        expect(screen.queryByText("Home page")).toBeNull()
    })

    it("C19 does not ask for typed but unsent text", async () => {
        setup()
        await ready()
        fireEvent.change(loginField(), { target: { value: "dana" } })
        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        expect(await screen.findByText("Home page")).toBeInTheDocument()
        expect(posts(ROLES)).toHaveLength(0)
    })

    it("C20 shows exactly one question and one blocker for a pending write", async () => {
        const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
        setup()
        const gate = deferred()
        replies[ROLES] = () => gate.promise
        await ready()
        giveRole("dana")
        fireEvent.click(screen.getByRole("link", { name: "Sidebar home" }))
        await dialogHeading("Leave while this change is being saved?")
        expect(document.querySelectorAll("dialog[open]")).toHaveLength(1)
        expect(warn.mock.calls.filter((call) => String(call[0]).includes("one blocker"))).toEqual([])
        fireEvent.click(screen.getByRole("button", { name: "Stay", hidden: true }))
        await act(async () => gate.resolve({ status: 201, body: change() }))
    })
})

// C21 is an isolation regression guard that passes at the baseline: the page's loading branch unmounts SharingContent on
// any world or account change (plan DV-6, not reproduced). It needs no kept input and no departure guard.
describe("C21: isolation of typed, unsent values", () => {
    it("C21 drops typed but unsent values when the world changes", async () => {
        setup()
        await ready()
        fireEvent.change(loginField(), { target: { value: "dana" } })
        fireEvent.change(hostField(), { target: { value: "erin" } })
        fireEvent.click(screen.getByRole("link", { name: "Other world" }))
        expect(await screen.findByText("Nia Owner")).toBeInTheDocument()
        expect(loginField()).toHaveValue("")
        expect(hostField()).toHaveValue("")
    })

    it("C21 drops typed but unsent values when the signed-in account changes", async () => {
        setup({ bootstrapAfterSwitch: OTHER_USER })
        await ready()
        fireEvent.change(loginField(), { target: { value: "dana" } })
        fireEvent.change(hostField(), { target: { value: "erin" } })
        fireEvent.click(screen.getByRole("button", { name: "Switch account" }))
        await waitFor(() => expect(loginField()).toHaveValue(""))
        expect(hostField()).toHaveValue("")
    })
})

describe("C21: isolation of a dialog and an unresolved attempt that need no typed input", () => {
    it("C21 drops an open dialog with an unknown outcome when the signed-in account changes", async () => {
        setup({ bootstrapAfterSwitch: OTHER_USER })
        replies["/worlds/w1/roles/m2/end"] = { status: 500, body: {} }
        await ready()
        const dialog = await endRole("Bob Editor")
        await within(dialog).findByText(/cannot tell whether this was saved/)
        fireEvent.click(screen.getByRole("button", { name: "Switch account" }))
        await waitFor(() => expect(screen.queryByText(/cannot tell whether this was saved/)).toBeNull())
        await screen.findByText("Bob Editor")
        expect(screen.queryByRole("button", { name: "Retry" })).toBeNull()
        expect(screen.queryByRole("dialog")).toBeNull()
        expect(posts("/worlds/w1/roles/m2/end")).toHaveLength(1)
    })

    it("C21 shows no late answer for an in-flight end-role after the signed-in account changes", async () => {
        setup({ bootstrapAfterSwitch: OTHER_USER })
        const gate = deferred()
        replies["/worlds/w1/roles/m2/end"] = () => gate.promise
        await ready()
        await endRole("Bob Editor")
        await waitFor(() => expect(posts("/worlds/w1/roles/m2/end")).toHaveLength(1))
        fireEvent.click(screen.getByRole("button", { name: "Switch account" }))
        await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
        await screen.findByText("Bob Editor")
        await act(async () => gate.resolve({ status: 200, body: change({ record_id: "m2" }) }))
        await settle()
        expect(announcer()).not.toHaveTextContent(/has ended/)
        expect(posts("/worlds/w1/roles/m2/end")).toHaveLength(1)
        expect(screen.queryByRole("button", { name: "Retry" })).toBeNull()
    })
})

describe("C22: no lookup", () => {
    it("C22 sends only the page's own reads and the person's own writes, and shows only the typed login and listed names", async () => {
        setup()
        await ready()
        fireEvent.change(loginField(), { target: { value: "dana" } })
        fireEvent.change(hostField(), { target: { value: "erin" } })
        fireEvent.click(screen.getByRole("button", { name: "Give role" }))
        await waitFor(() => expect(announcer()).toHaveTextContent("dana now has the Editor role on this world."))
        const paths = server.calls.map((call) => `${call.method} ${call.path}`)
        const unexpected = paths.filter((path) => !/^(GET \/worlds\/w1(\/access)?|POST \/worlds\/w1\/roles)$/.test(path))
        expect(unexpected).toEqual([])
        expect(server.calls.some((call) => call.path.includes("dana") || call.path.includes("erin"))).toBe(false)
    })
})
