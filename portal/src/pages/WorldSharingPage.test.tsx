import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { TEST_CSRF, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { WorldSharingPage } from "./WorldSharingPage"

const world = {
    world_id: "w1",
    name: "Eberron",
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

function access(overrides: object = {}) {
    return {
        assignments: [
            {
                world_membership_id: "m1",
                user_id: "u1",
                display_name: "Alice Owner",
                role_code: "world_owner",
                role_display_name: "World owner",
                granted_at: "2026-10-06T10:00:00Z",
                granted_by_display_name: null,
                account_active: true,
            },
            {
                world_membership_id: "m2",
                user_id: "u2",
                display_name: "Bob Editor",
                role_code: "world_editor",
                role_display_name: "World editor",
                granted_at: "2026-10-06T10:05:00Z",
                granted_by_display_name: "Alice Owner",
                account_active: true,
            },
        ],
        use_grants: [
            {
                world_use_grant_id: "g1",
                user_id: "u3",
                display_name: "Cara Host",
                granted_at: "2026-10-06T10:10:00Z",
                granted_by_display_name: "Alice Owner",
                account_active: true,
            },
        ],
        may_transfer: true,
        ...overrides,
    }
}

function setup(view: object = access()) {
    const server = installMockServer()
    let current: object = view
    server.on("GET", "/worlds/w1", { body: world })
    server.on("GET", "/worlds/w1/access", () => ({ body: current }))
    const rendered = renderAuthoringRoutes({
        initialEntry: "/worlds/w1/sharing",
        routes: [{ path: "/worlds/:worldId/sharing", element: <WorldSharingPage /> }],
    })
    return {
        server,
        setCurrent: (next: object) => {
            current = next
        },
        ...rendered,
    }
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("WorldSharingPage", () => {
    it("lists role holders and use grants from the server", async () => {
        setup()
        expect(await screen.findByText("Bob Editor")).toBeInTheDocument()
        expect(screen.getByText("Cara Host")).toBeInTheDocument()
        expect(within(screen.getByRole("table")).getByText("Editor")).toBeInTheDocument()
    })

    it("keeps the roles table in its own named, keyboard-scrollable region so the page never scrolls sideways", async () => {
        setup()
        await screen.findByText("Bob Editor")
        const region = screen.getByRole("region", { name: "World roles" })
        expect(region).toHaveClass("table-scroll")
        expect(region).toHaveAttribute("tabindex", "0")
        expect(within(region).getByRole("table")).toBeInTheDocument()
        // Every action stays reachable inside the region.
        expect(within(region).getAllByRole("button", { name: /^End role for / }).length).toBeGreaterThan(0)
    })

    it("explains an unavailable page instead of showing controls", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1", { body: world })
        server.on("GET", "/worlds/w1/access", { status: 403, body: { error: { code: "forbidden" } } })
        renderAuthoringRoutes({
            initialEntry: "/worlds/w1/sharing",
            routes: [{ path: "/worlds/:worldId/sharing", element: <WorldSharingPage /> }],
        })
        expect(await screen.findByText(/Sharing is not available/)).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /Give role/ })).not.toBeInTheDocument()
    })

    it("gives a role with the CSRF token and refetches the list", async () => {
        const { server } = setup()
        server.on("POST", "/worlds/w1/roles", {
            status: 201,
            body: { world_id: "w1", user_id: "u9", record_id: "m9", role_code: "world_reader", changed: true },
        })
        await screen.findByText("Bob Editor")
        fireEvent.change(screen.getByRole("textbox", { name: "Login name" }), {
            target: { value: " dana " },
        })
        fireEvent.change(screen.getByRole("combobox", { name: "Role" }), {
            target: { value: "world_reader" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Give role" }))

        await waitFor(() => expect(server.callsTo("POST", "/worlds/w1/roles")).toHaveLength(1))
        const [call] = server.callsTo("POST", "/worlds/w1/roles")
        expect(call!.headers["X-CSRF-Token"]).toBe(TEST_CSRF)
        expect(call!.body).toEqual({ login_name: "dana", role_code: "world_reader" })
        await waitFor(() => expect(server.callsTo("GET", "/worlds/w1/access").length).toBeGreaterThan(1))
    })

    it("confirms before ending a role, then ends it", async () => {
        const { server } = setup()
        server.on("POST", "/worlds/w1/roles/m2/end", {
            body: { world_id: "w1", user_id: "u2", record_id: "m2", role_code: "world_editor", changed: true },
        })
        await screen.findByText("Bob Editor")
        fireEvent.click(screen.getByRole("button", { name: /End role for Bob Editor/ }))
        expect(server.callsTo("POST", "/worlds/w1/roles/m2/end")).toHaveLength(0)
        const dialog = await screen.findByRole("dialog")
        fireEvent.click(within(dialog).getByRole("button", { name: "End role" }))
        await waitFor(() =>
            expect(server.callsTo("POST", "/worlds/w1/roles/m2/end")).toHaveLength(1),
        )
    })

    it("hides ownership transfer and Owner assignment without world.transfer", async () => {
        setup(access({ may_transfer: false }))
        await screen.findByText("Bob Editor")
        expect(screen.queryByRole("heading", { name: "Transfer ownership" })).not.toBeInTheDocument()
        const roleSelect = screen.getByRole("combobox", { name: "Role" })
        expect(within(roleSelect).queryByText(/^Owner/)).not.toBeInTheDocument()
        // The owner's own assignment cannot be ended from here.
        expect(screen.queryByRole("button", { name: /End role for Alice Owner/ })).not.toBeInTheDocument()
    })

    it("transfers ownership only after confirmation, keeping the chosen role", async () => {
        const { server } = setup()
        server.on("POST", "/worlds/w1/ownership-transfer", {
            body: {
                world_id: "w1",
                previous_owner_user_id: "u1",
                new_owner_user_id: "u4",
                retained_role_code: "world_editor",
            },
        })
        await screen.findByText("Bob Editor")
        fireEvent.change(screen.getByRole("textbox", { name: /New owner/ }), {
            target: { value: "erin" },
        })
        fireEvent.change(screen.getByRole("combobox", { name: /Keep me on the world as/ }), {
            target: { value: "world_editor" },
        })
        fireEvent.click(screen.getByRole("button", { name: /Transfer ownership…/ }))
        expect(server.callsTo("POST", "/worlds/w1/ownership-transfer")).toHaveLength(0)
        const dialog = await screen.findByRole("dialog")
        fireEvent.click(within(dialog).getByRole("button", { name: "Transfer ownership" }))
        await waitFor(() =>
            expect(server.callsTo("POST", "/worlds/w1/ownership-transfer")).toHaveLength(1),
        )
        expect(server.callsTo("POST", "/worlds/w1/ownership-transfer")[0]!.body).toEqual({
            login_name: "erin",
            retain_previous_owner_as: "world_editor",
        })
    })

    it("shows the server's reason when a new owner lacks the game master role", async () => {
        const { server } = setup()
        server.on("POST", "/worlds/w1/ownership-transfer", {
            status: 409,
            body: { error: { code: "target_requires_system_gm" } },
        })
        await screen.findByText("Bob Editor")
        fireEvent.change(screen.getByRole("textbox", { name: /New owner/ }), {
            target: { value: "plain" },
        })
        fireEvent.click(screen.getByRole("button", { name: /Transfer ownership…/ }))
        const dialog = await screen.findByRole("dialog")
        fireEvent.click(within(dialog).getByRole("button", { name: "Transfer ownership" }))
        expect(
            await within(await screen.findByRole("dialog")).findByText(
                "A world owner must hold the game master system role.",
            ),
        ).toBeInTheDocument()
    })
})

describe("WorldSharingPage: last owner, focus and the transfer control (CP-4 smoke D-7, O-1, O-2)", () => {
    it("explains the last-owner refusal and what to do first, and changes nothing", async () => {
        const { server } = setup()
        server.on("POST", "/worlds/w1/roles/m1/end", {
            status: 409,
            body: { error: { code: "world_owner_required", message: "A world must keep at least one owner.", correlation_id: "x" } },
        })
        await screen.findByText("Bob Editor")
        fireEvent.click(screen.getByRole("button", { name: /End role for Alice Owner/ }))
        const dialog = await screen.findByRole("dialog")
        fireEvent.click(within(dialog).getByRole("button", { name: "End role" }))
        const message = await within(await screen.findByRole("dialog")).findByText(/A world must keep at least one owner/)
        expect(message).toHaveTextContent(/Give the Owner role to someone else \(or transfer ownership\) first/)
        expect(message).not.toHaveTextContent(/Try again/)
        // The list is exactly what the server holds: still both holders.
        expect(screen.getAllByRole("row")).toHaveLength(3)
    })

    it("keeps an unknown failure of ending a role on the safe fallback", async () => {
        const { server } = setup()
        server.on("POST", "/worlds/w1/roles/m2/end", { status: 500, body: {} })
        await screen.findByText("Bob Editor")
        fireEvent.click(screen.getByRole("button", { name: /End role for Bob Editor/ }))
        fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "End role" }))
        expect(await within(await screen.findByRole("dialog")).findByText(/cannot tell whether this was saved/)).toBeInTheDocument()
    })

    it("moves focus to the page heading when a transfer leaves the person without Sharing, not to the page", async () => {
        const { server, setCurrent } = setup()
        server.on("POST", "/worlds/w1/ownership-transfer", {
            body: { world_id: "w1", previous_owner_user_id: "u1", new_owner_user_id: "u4", retained_role_code: "world_editor" },
        })
        await screen.findByText("Bob Editor")
        fireEvent.change(screen.getByRole("textbox", { name: /New owner/ }), { target: { value: "erin" } })
        fireEvent.click(screen.getByRole("button", { name: /Transfer ownership…/ }))
        const dialog = await screen.findByRole("dialog")
        // The transferred-away person is refused the access read from now on.
        server.on("GET", "/worlds/w1/access", { status: 403, body: { error: { code: "forbidden", message: "m", correlation_id: "x" } } })
        setCurrent(access())
        fireEvent.click(within(dialog).getByRole("button", { name: "Transfer ownership" }))
        expect(await screen.findByText(/Sharing is not available for this world with your account/)).toBeInTheDocument()
        await waitFor(() => expect(screen.getByRole("heading", { level: 1, name: "Sharing" })).toHaveFocus())
    })

    it("opens the transfer dialog on one ordinary press-and-release of the button", async () => {
        setup()
        await screen.findByText("Bob Editor")
        fireEvent.change(screen.getByRole("textbox", { name: /New owner/ }), { target: { value: "erin" } })
        const button = screen.getByRole("button", { name: /Transfer ownership…/ })
        fireEvent.pointerDown(button)
        fireEvent.mouseDown(button)
        fireEvent.pointerUp(button)
        fireEvent.mouseUp(button)
        fireEvent.click(button)
        expect(await screen.findByRole("dialog")).toHaveAccessibleName("Transfer ownership?")
    })

    it("returns focus to the Transfer button when the dialog is cancelled, and opens by keyboard", async () => {
        setup()
        await screen.findByText("Bob Editor")
        const field = screen.getByRole("textbox", { name: /New owner/ })
        fireEvent.change(field, { target: { value: "erin" } })
        const button = screen.getByRole("button", { name: /Transfer ownership…/ })
        button.focus()
        // Enter on a submit button submits its form: the keyboard path.
        fireEvent.submit(field.closest("form")!)
        const dialog = await screen.findByRole("dialog")
        fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
        await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
        await waitFor(() => expect(button).toHaveFocus())
    })

    it("lands on the roles heading, not the page, when the control that opened the dialog is gone", async () => {
        const { server, setCurrent } = setup()
        server.on("POST", "/worlds/w1/roles/m2/end", {
            body: { world_id: "w1", user_id: "u2", record_id: "m2", role_code: "world_editor", changed: true },
        })
        await screen.findByText("Bob Editor")
        const end = screen.getByRole("button", { name: /End role for Bob Editor/ })
        end.focus()
        fireEvent.click(end)
        const dialog = await screen.findByRole("dialog")
        // After the change the editor's row (and its End role button) no longer exists.
        setCurrent(access({ assignments: access().assignments.slice(0, 1) }))
        fireEvent.click(within(dialog).getByRole("button", { name: "End role" }))
        await waitFor(() => expect(screen.queryByText("Bob Editor")).not.toBeInTheDocument())
        await waitFor(() => expect(screen.getByRole("heading", { name: "People with a role" })).toHaveFocus())
    })

    it("reports a saved role whose list re-read fails, holds the controls, and recovers by reading only", async () => {
        const { server, setCurrent } = setup()
        server.on("POST", "/worlds/w1/roles", {
            status: 201,
            body: { world_id: "w1", user_id: "u9", record_id: "m9", role_code: "world_reader", changed: true },
        })
        await screen.findByText("Bob Editor")
        fireEvent.change(screen.getByRole("textbox", { name: "Login name" }), { target: { value: "dana" } })
        server.on("GET", "/worlds/w1/access", { status: 500, body: {} })
        fireEvent.click(screen.getByRole("button", { name: "Give role" }))

        expect(await screen.findByText(/Role assigned\. The latest sharing list could not be loaded/)).toBeInTheDocument()
        const live = screen.getByTestId("authoring-announcer")
        expect(live).toHaveTextContent("Saved, but the latest data could not be loaded.")
        expect(live).not.toHaveTextContent(/^Role assigned/)
        // The list on screen stays, and nothing can be changed from it until it is read again.
        expect(screen.getByText("Bob Editor")).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Give role" })).toBeDisabled()
        expect(screen.getByRole("button", { name: /End role for Bob Editor/ })).toBeDisabled()
        expect(server.callsTo("POST", "/worlds/w1/roles")).toHaveLength(1)

        setCurrent(access())
        server.on("GET", "/worlds/w1/access", () => ({ body: access() }))
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        await waitFor(() => expect(screen.getByRole("button", { name: "Give role" })).toBeEnabled())
        await waitFor(() => expect(live).toHaveTextContent("Role assigned"))
        expect(screen.queryByText(/could not be loaded/)).toBeNull()
        expect(server.callsTo("POST", "/worlds/w1/roles")).toHaveLength(1)
    })

    it("still announces a transfer whose read-back is the denial that ended the person's own access", async () => {
        const { server } = setup()
        server.on("POST", "/worlds/w1/ownership-transfer", {
            body: { world_id: "w1", previous_owner_user_id: "u1", new_owner_user_id: "u4", retained_role_code: "world_editor" },
        })
        await screen.findByText("Bob Editor")
        fireEvent.change(screen.getByRole("textbox", { name: /New owner/ }), { target: { value: "erin" } })
        fireEvent.click(screen.getByRole("button", { name: /Transfer ownership…/ }))
        const dialog = await screen.findByRole("dialog")
        server.on("GET", "/worlds/w1/access", { status: 403, body: { error: { code: "forbidden", message: "m", correlation_id: "x" } } })
        fireEvent.click(within(dialog).getByRole("button", { name: "Transfer ownership" }))
        expect(await screen.findByText(/Sharing is not available for this world with your account/)).toBeInTheDocument()
        // A denied read is the authoritative answer here, not a read that failed: the loss is explained
        // and the transfer is announced; the removed content is not kept.
        await waitFor(() => expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Ownership transferred"))
        expect(screen.queryByText("Bob Editor")).toBeNull()
        expect(server.callsTo("POST", "/worlds/w1/ownership-transfer")).toHaveLength(1)
    })
})
