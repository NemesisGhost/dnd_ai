import { fireEvent, screen, within } from "@testing-library/react"
import { useLocation } from "react-router"
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

function LocationProbe() {
    const location = useLocation()
    return (
        <p>
            Location page {location.search} {JSON.stringify(location.state)}
        </p>
    )
}

function setup(path: string | { pathname: string; state?: unknown }, element: React.ReactNode, routePath: string, view: object) {
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
            { path: "/app/:campaignId/world/location/:entityId", element: <LocationProbe /> },
        ],
    })
    return server
}

describe("CreateDungeonPage", () => {
    it("creates a draft dungeon and opens its Areas, keeping where the person came from", async () => {
        const server = setup(
            { pathname: "/app/c1/world/dungeon/new", state: { worldSearch: "?category=location", junk: "x" } },
            <CreateDungeonPage />,
            "/app/:campaignId/world/dungeon/new",
            dungeon(),
        )
        server.on("POST", `${BASE}/dungeons`, { status: 201, body: dungeon() })
        fireEvent.change(await screen.findByRole("textbox", { name: /Name/ }), {
            target: { value: " The Sunken Vault " },
        })
        fireEvent.change(screen.getByRole("combobox", { name: /Danger level/ }), { target: { value: "6" } })
        fireEvent.click(screen.getByRole("button", { name: "Create dungeon" }))
        const opened = await screen.findByText(/Location page \?section=areas/)
        expect(opened).toHaveTextContent('"worldSearch":"?category=location"')
        expect(opened).toHaveTextContent('"announce":"Dungeon created as a draft"')
        expect(opened).not.toHaveTextContent("junk")
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

    it("edits the details only, and points to the workspace for areas, connections and publication", async () => {
        const server = setup(
            { pathname: "/app/c1/world/dungeon/d1/edit", state: { reviewSearch: "?status=draft" } },
            <EditDungeonPage />,
            route,
            dungeon(),
        )
        expect(await screen.findByRole("textbox", { name: /Name/ })).toHaveValue("The Sunken Vault")
        // The structure forms, the area list and the lifecycle panel are not repeated here.
        expect(screen.queryByRole("form", { name: "Add an area" })).not.toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Add a connection" })).not.toBeInTheDocument()
        expect(screen.queryByRole("link", { name: "Entry Hall" })).not.toBeInTheDocument()
        expect(screen.queryByRole("article")).not.toBeInTheDocument()
        expect(server.calls.some((c) => c.path.includes("/lifecycle"))).toBe(false)
        const nav = screen.getByRole("navigation", { name: "Other parts of this record" })
        expect(within(nav).getAllByRole("link").map((l) => [l.textContent, l.getAttribute("href")])).toEqual([
            ["Areas", "/app/c1/world/location/d1?section=areas"],
            ["Connections", "/app/c1/world/location/d1?section=connections"],
            ["Publication", "/app/c1/world/location/d1?section=publication"],
        ])
    })

    it("carries the return state on those links", async () => {
        setup(
            { pathname: "/app/c1/world/dungeon/d1/edit", state: { reviewSearch: "?status=draft" } },
            <EditDungeonPage />,
            route,
            dungeon(),
        )
        fireEvent.click(await screen.findByRole("link", { name: "Connections" }))
        expect(await screen.findByText(/Location page \?section=connections/)).toHaveTextContent(
            '{"reviewSearch":"?status=draft"}',
        )
    })
})

describe("EditDungeonAreaPage", () => {
    const route = "/app/:campaignId/world/dungeon/:dungeonId/areas/:areaId/edit"
    const path = "/app/c1/world/dungeon/d1/areas/a1/edit"

    it("links back to the dungeon client-side, carrying the return state", async () => {
        setup(
            { pathname: path, state: { worldSearch: "?q=vault", reviewSearch: "?scope=mine", junk: "x" } },
            <EditDungeonAreaPage />,
            route,
            area(),
        )
        const link = await screen.findByRole("link", { name: "Back to The Sunken Vault" })
        expect(link).toHaveAttribute("href", "/app/c1/world/location/d1?section=areas")
        fireEvent.click(link)
        expect(await screen.findByText(/Location page \?section=areas/)).toHaveTextContent(
            '{"worldSearch":"?q=vault","reviewSearch":"?scope=mine"}',
        )
    })

    it("edits the area's details only, and points to Contents, Area now and Publication in the workspace", async () => {
        const server = setup(
            { pathname: path, state: { worldSearch: "?q=vault" } },
            <EditDungeonAreaPage />,
            route,
            area(),
        )
        expect(await screen.findByRole("textbox", { name: /Name/ })).toHaveValue("Entry Hall")
        // No contents, state or lifecycle controls are repeated here.
        expect(screen.queryByRole("article")).not.toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Add a hazard" })).not.toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "The area now" })).not.toBeInTheDocument()
        expect(server.calls.some((c) => c.path.includes("/lifecycle"))).toBe(false)
        const nav = screen.getByRole("navigation", { name: "Other parts of this record" })
        expect(within(nav).getAllByRole("link").map((l) => [l.textContent, l.getAttribute("href")])).toEqual([
            ["Contents", "/app/c1/world/location/a1?section=contents"],
            ["Area now", "/app/c1/world/location/a1?section=area-now"],
            ["Publication", "/app/c1/world/location/a1?section=publication"],
        ])
    })

    it("returns to its dungeon's Areas when it was opened from there, and nowhere else the state names", async () => {
        setup(
            {
                pathname: path,
                state: {
                    worldSearch: "?q=vault",
                    returnTo: { pathname: "/app/c1/world/location/d1", search: "?section=areas" },
                },
            },
            <EditDungeonAreaPage />,
            route,
            area(),
        )
        fireEvent.click(await screen.findByRole("button", { name: "Cancel" }))
        expect(await screen.findByText(/Location page \?section=areas/)).toHaveTextContent('"worldSearch":"?q=vault"')
    })

    it("does not return to a dungeon that only the state names", async () => {
        setup(
            {
                pathname: path,
                state: { returnTo: { pathname: "/app/c1/world/location/elsewhere", search: "?section=areas" } },
            },
            <EditDungeonAreaPage />,
            route,
            area(),
        )
        fireEvent.click(await screen.findByRole("button", { name: "Cancel" }))
        expect(await screen.findByText(/Location page/)).not.toHaveTextContent("section=areas")
    })
})
