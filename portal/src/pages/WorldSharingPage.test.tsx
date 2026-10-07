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
