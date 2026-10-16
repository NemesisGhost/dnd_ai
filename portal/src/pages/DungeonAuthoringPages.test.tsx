import { fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { CreateDungeonPage, EditDungeonAreaPage, EditDungeonPage } from "./DungeonAuthoringPages"

const BASE = "/campaigns/c1/authoring"

const OPTIONS = {
    can_create: true,
    connection_types: [
        { value: "door", label: "Door" },
        { value: "secret_door", label: "Secret door" },
    ],
    limits: {
        name_max_length: 200,
        summary_max_length: 4000,
        short_text_max_length: 200,
        notes_max_length: 4000,
        change_note_max_length: 1000,
        rating_min: 1,
        rating_max: 10,
        alarm_level_max: 1000,
    },
}

const ref = (id: string, name: string, canon = "draft") => ({
    entity_id: id,
    name,
    canon_status: canon,
    lifecycle_status: "active",
})

function dungeon(overrides: object = {}) {
    return {
        dungeon_id: "d1",
        name: "The Sunken Vault",
        summary: "Flooded halls.",
        danger_level: 6,
        parent: null,
        canon_status: "draft",
        lifecycle_status: "active",
        row_version: 3,
        available_actions: [
            "update",
            "add_area",
            "add_connection",
            "update_connection",
            "remove_connection",
        ],
        blocked_actions: [],
        field_locks: [],
        areas: [
            {
                dungeon_area_id: "a1",
                name: "Entry Hall",
                area_type: "hall",
                canon_status: "draft",
                lifecycle_status: "active",
                row_version: 1,
                feature_count: 1,
                hazard_count: 0,
                interactable_count: 0,
            },
            {
                dungeon_area_id: "a2",
                name: "Vault",
                area_type: null,
                canon_status: "draft",
                lifecycle_status: "active",
                row_version: 1,
                feature_count: 0,
                hazard_count: 0,
                interactable_count: 0,
            },
        ],
        connections: [
            {
                area_connection_id: "c1",
                from_area: ref("a1", "Entry Hall"),
                to_area: ref("a2", "Vault"),
                connection_type: "door",
                connection_type_label: "Door",
                is_one_way: false,
                is_hidden: false,
                description: null,
                is_conditional: false,
                condition_description: null,
                status: null,
                state_event_id: null,
            },
        ],
        ...overrides,
    }
}

function area(overrides: object = {}) {
    return {
        dungeon_area_id: "a1",
        name: "Entry Hall",
        summary: null,
        area_type: "hall",
        dimensions: "30 ft",
        environmental_properties: null,
        dungeon: ref("d1", "The Sunken Vault", "canon"),
        dungeon_row_version: 7,
        canon_status: "canon",
        lifecycle_status: "active",
        row_version: 2,
        available_actions: ["update"],
        blocked_actions: [],
        field_locks: [],
        structure_actions: [
            "add_feature",
            "update_feature",
            "add_hazard",
            "update_hazard",
            "add_interactable",
            "update_interactable",
        ],
        features: [
            {
                kind: "feature",
                child_id: "f1",
                child_type: "mural",
                description: "A faded mural.",
                is_hidden: false,
                severity: null,
                status: null,
                is_destroyed: null,
                condition_notes: null,
                state_event_id: null,
            },
        ],
        hazards: [
            {
                kind: "hazard",
                child_id: "h1",
                child_type: "pit",
                description: null,
                is_hidden: true,
                severity: 4,
                status: "armed",
                is_destroyed: null,
                condition_notes: null,
                state_event_id: "ev1",
            },
        ],
        interactables: [],
        connections: dungeon().connections,
        state: {
            is_searched: false,
            is_destroyed: false,
            alarm_level: 0,
            condition_notes: null,
            state_event_id: null,
        },
        can_set_state: true,
        state_choices: {
            connection_status: [
                { value: "open", label: "Open" },
                { value: "locked", label: "Locked" },
            ],
            hazard_status: [
                { value: "armed", label: "Armed" },
                { value: "triggered", label: "Triggered" },
            ],
            interactable_status: [{ value: "active", label: "Active" }],
        },
        ...overrides,
    }
}

afterEach(() => {
    vi.unstubAllGlobals()
})

function setup(path: string, element: React.ReactNode, routePath: string, view: object) {
    const server = installMockServer()
    server.on("GET", `${BASE}/dungeons/options`, { body: OPTIONS })
    server.on("GET", `${BASE}/dungeons/d1`, () => ({ body: view }))
    server.on("GET", `${BASE}/dungeon-areas/a1`, () => ({ body: view }))
    server.on("GET", /\/entities\/.*\/lifecycle$/, {
        body: {
            entity_id: "d1",
            entity_type_code: "dungeon",
            canonical_name: "x",
            canon_status: "draft",
            lifecycle_status: "active",
            row_version: 1,
            lifecycle_managed: true,
            superseded_by: null,
            available_actions: [],
            blocked_actions: [],
        },
    })
    server.on("POST", new RegExp(`${BASE}/`), { body: { ...dungeon(), changed: true } })
    server.on("POST", /dungeon-areas\/a1\/state/, {
        body: { dungeon_area_id: "a1", kind: "hazard", target_id: "h1", changed: true },
    })
    renderAuthoringRoutes({
        initialEntry: path,
        bootstrap: bootstrapWith({
            campaigns: [
                { ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["canon.edit"] },
            ],
        }),
        routes: [
            { path: routePath, element },
            { path: "/app/:campaignId/world/dungeon/:dungeonId/edit", element: <p>Dungeon editor page</p> },
            { path: "/app/:campaignId/world/location/:entityId", element: <p>Location page</p> },
        ],
    })
    return server
}

describe("CreateDungeonPage", () => {
    it("creates a draft dungeon and opens its editor", async () => {
        const server = setup("/app/c1/world/dungeon/new", <CreateDungeonPage />, "/app/:campaignId/world/dungeon/new", dungeon())
        server.on("POST", `${BASE}/dungeons`, { status: 201, body: dungeon() })
        fireEvent.change(await screen.findByRole("textbox", { name: /Name/ }), {
            target: { value: " The Sunken Vault " },
        })
        fireEvent.change(screen.getByRole("combobox", { name: /Danger level/ }), { target: { value: "6" } })
        fireEvent.click(screen.getByRole("button", { name: "Create dungeon" }))
        await screen.findByText("Dungeon editor page")
        expect(server.callsTo("POST", `${BASE}/dungeons`)[0]!.body).toEqual({
            name: "The Sunken Vault",
            summary: null,
            danger_level: 6,
            parent_location_id: null,
        })
    })

    it("requires a name and sends nothing otherwise", async () => {
        const server = setup("/app/c1/world/dungeon/new", <CreateDungeonPage />, "/app/:campaignId/world/dungeon/new", dungeon())
        await screen.findByRole("textbox", { name: /Name/ })
        fireEvent.click(screen.getByRole("button", { name: "Create dungeon" }))
        expect((await screen.findAllByText("Name is required.")).length).toBeGreaterThan(0)
        expect(server.callsTo("POST", `${BASE}/dungeons`)).toHaveLength(0)
    })
})

describe("EditDungeonPage", () => {
    const route = "/app/:campaignId/world/dungeon/:dungeonId/edit"

    it("lists areas and connections", async () => {
        setup("/app/c1/world/dungeon/d1/edit", <EditDungeonPage />, route, dungeon())
        expect(await screen.findByRole("link", { name: "Entry Hall" })).toBeInTheDocument()
        expect(screen.getByRole("article", { name: "Connection Entry Hall to Vault" })).toBeInTheDocument()
    })

    it("adds a connection naming the dungeon version, after checking the areas differ", async () => {
        const server = setup("/app/c1/world/dungeon/d1/edit", <EditDungeonPage />, route, dungeon())
        const form = await screen.findByRole("form", { name: "Add a connection" })
        const [from, to, kind] = within(form).getAllByRole("combobox")
        fireEvent.change(from!, { target: { value: "a1" } })
        fireEvent.change(to!, { target: { value: "a1" } })
        fireEvent.change(kind!, { target: { value: "secret_door" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add connection" }))
        expect(await within(form).findByText("Choose two different areas.")).toBeInTheDocument()
        expect(server.callsTo("POST", `${BASE}/dungeons/d1/connections`)).toHaveLength(0)
        fireEvent.change(to!, { target: { value: "a2" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add connection" }))
        await vi.waitFor(() =>
            expect(server.callsTo("POST", `${BASE}/dungeons/d1/connections`)).toHaveLength(1),
        )
        expect(server.callsTo("POST", `${BASE}/dungeons/d1/connections`)[0]!.body).toMatchObject({
            expected_row_version: 3,
            from_area_id: "a1",
            to_area_id: "a2",
            connection_type: "secret_door",
            is_hidden: false,
            is_conditional: false,
        })
    })

    it("removes a connection while the dungeon is a draft", async () => {
        const server = setup("/app/c1/world/dungeon/d1/edit", <EditDungeonPage />, route, dungeon())
        fireEvent.click(await screen.findByRole("button", { name: "Remove connection Entry Hall to Vault" }))
        await vi.waitFor(() =>
            expect(server.callsTo("POST", `${BASE}/dungeons/d1/connections/c1/remove`)).toHaveLength(1),
        )
        expect(server.callsTo("POST", `${BASE}/dungeons/d1/connections/c1/remove`)[0]!.body).toEqual({
            expected_row_version: 3,
        })
    })

    it("offers no removal once the dungeon is published", async () => {
        setup(
            "/app/c1/world/dungeon/d1/edit",
            <EditDungeonPage />,
            route,
            dungeon({
                canon_status: "canon",
                available_actions: ["update", "add_area", "add_connection", "update_connection"],
            }),
        )
        await screen.findByRole("article", { name: "Connection Entry Hall to Vault" })
        expect(screen.queryByRole("button", { name: /Remove connection/ })).not.toBeInTheDocument()
    })

    it("explains a refused removal", async () => {
        const server = setup("/app/c1/world/dungeon/d1/edit", <EditDungeonPage />, route, dungeon())
        server.on("POST", `${BASE}/dungeons/d1/connections/c1/remove`, {
            status: 409,
            body: { error: { code: "dungeon_not_draft", message: "m", correlation_id: "c" } },
        })
        fireEvent.click(await screen.findByRole("button", { name: "Remove connection Entry Hall to Vault" }))
        expect(await screen.findByRole("alert")).toHaveTextContent(/only while the dungeon is a draft/)
    })
})

describe("EditDungeonAreaPage", () => {
    const route = "/app/:campaignId/world/dungeon/:dungeonId/areas/:areaId/edit"
    const path = "/app/c1/world/dungeon/d1/areas/a1/edit"

    it("shows the area contents and adds a hazard against the dungeon version", async () => {
        const server = setup(path, <EditDungeonAreaPage />, route, area())
        expect(await screen.findByRole("article", { name: "feature mural" })).toBeInTheDocument()
        const form = screen.getByRole("form", { name: "Add a hazard" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Kind of hazard/ }), {
            target: { value: "trap" },
        })
        fireEvent.change(within(form).getByRole("textbox", { name: /Severity/ }), { target: { value: "11" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add hazard" }))
        expect(await within(form).findByText(/from 1 to 10/)).toBeInTheDocument()
        fireEvent.change(within(form).getByRole("textbox", { name: /Severity/ }), { target: { value: "7" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add hazard" }))
        await vi.waitFor(() =>
            expect(server.callsTo("POST", `${BASE}/dungeons/d1/hazards`)).toHaveLength(1),
        )
        expect(server.callsTo("POST", `${BASE}/dungeons/d1/hazards`)[0]!.body).toEqual({
            expected_row_version: 7,
            dungeon_area_id: "a1",
            child_type: "trap",
            description: null,
            is_hidden: false,
            severity: 7,
        })
    })

    it("sets a hazard status naming the event that last wrote it", async () => {
        const server = setup(path, <EditDungeonAreaPage />, route, area())
        const select = await screen.findByRole("combobox", { name: "New status for pit" })
        fireEvent.change(select, { target: { value: "triggered" } })
        fireEvent.click(screen.getByRole("button", { name: "Set status of pit" }))
        await vi.waitFor(() =>
            expect(server.callsTo("POST", /dungeon-areas\/a1\/state/)).toHaveLength(1),
        )
        expect(server.callsTo("POST", /dungeon-areas\/a1\/state/)[0]!.body).toEqual({
            kind: "hazard",
            target_id: "h1",
            expected_last_event_id: "ev1",
            hazard_status: "triggered",
        })
    })

    it("saves the area state and rejects an alarm level that is not a number", async () => {
        const server = setup(path, <EditDungeonAreaPage />, route, area())
        const form = await screen.findByRole("form", { name: "The area now" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Alarm level/ }), { target: { value: "x" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save area state" }))
        expect(await within(form).findByText(/whole number from 0 to 1000/)).toBeInTheDocument()
        expect(server.callsTo("POST", /dungeon-areas\/a1\/state/)).toHaveLength(0)
        fireEvent.change(within(form).getByRole("textbox", { name: /Alarm level/ }), { target: { value: "2" } })
        fireEvent.change(within(form).getByRole("combobox", { name: /Searched/ }), { target: { value: "yes" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save area state" }))
        await vi.waitFor(() =>
            expect(server.callsTo("POST", /dungeon-areas\/a1\/state/)).toHaveLength(1),
        )
        expect(server.callsTo("POST", /dungeon-areas\/a1\/state/)[0]!.body).toMatchObject({
            kind: "area",
            target_id: "a1",
            expected_last_event_id: null,
            is_searched: true,
            alarm_level: 2,
        })
    })

    it("asks for publication before state can be recorded", async () => {
        setup(path, <EditDungeonAreaPage />, route, area({ can_set_state: false, canon_status: "draft" }))
        expect(await screen.findByText(/Publish the dungeon and this area/)).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "The area now" })).not.toBeInTheDocument()
    })
})
