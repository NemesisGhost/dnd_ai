import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"
import type { MockServer } from "../../test/authoringHarness"
import {
    CAMPAIGN_ONLY_RECORD_AUTHORING,
    NO_WORLD_CAPABILITIES,
    OWNER_WORLD_CAPABILITIES,
} from "../../test/recordAuthoring"
import { CampaignWorldDetailPage } from "../../pages/CampaignWorldDetailPage"

// "Area now" records what is happening in a published dungeon area. It reads the campaign's own
// runtime projection (`.../dungeon-areas/{id}/runtime`), never the area's authoring view, so a
// campaign GM with no world role can run the area and no private-authoring request is made to
// render it.

const C = "c1"
const NOT_FOUND = { status: 404, body: { error: { code: "not_found", message: "m", correlation_id: "x" } } }
const AUTHORING = /\/authoring\//
const PRIVATE = /\/authoring\/|\/provenance|\/revisions|\/sources/

const detail = (authoring: object) => ({
    authoring,
    location_id: "l1",
    name: "Entry hall",
    summary: null,
    location_type_code: "dungeon_area",
    parent_location_id: "d1",
    breadcrumbs: [{ location_id: "d1", name: "Crypt", location_type_code: "dungeon" }],
    population: null,
    building_use: null,
    danger_level: null,
    is_searched: true,
    is_destroyed: false,
    alarm_level: 2,
    condition_notes: null,
    canon_status: "canon",
    lifecycle_status: "active",
    superseded_by: null,
})

const runtime = (over: object = {}) => ({
    dungeon_area_id: "l1",
    name: "Entry hall",
    dungeon: { entity_id: "d1", name: "Crypt" },
    can_set_state: true,
    state: { is_searched: true, is_destroyed: false, alarm_level: 2, condition_notes: "Dusty", state_event_id: "ev0" },
    state_choices: {
        connection_status: [{ value: "open", label: "Open" }],
        hazard_status: [
            { value: "armed", label: "Armed" },
            { value: "triggered", label: "Triggered" },
        ],
        interactable_status: [{ value: "active", label: "Active" }],
    },
    connections: [],
    features: [],
    hazards: [{ child_id: "h1", child_type: "Spike trap", status: "armed", is_destroyed: null, state_event_id: "ev1" }],
    interactables: [],
    limits: { alarm_level_max: 1000, notes_max_length: 4000 },
    ...over,
})

const lifecycle = {
    entity_id: "l1",
    entity_type_code: "dungeon_area",
    canonical_name: "Entry hall",
    canon_status: "canon",
    lifecycle_status: "active",
    row_version: 3,
    lifecycle_managed: true,
    superseded_by: null,
    available_actions: [],
    blocked_actions: [],
}

function setup(options: {
    authoring: object
    worldCapabilities: readonly string[]
    runtime?: object
    extra?: (server: MockServer) => void
}) {
    const server = installMockServer()
    server.on("GET", /.*/, NOT_FOUND)
    server.on("GET", `/campaigns/${C}/world/locations/l1`, { body: detail(options.authoring) })
    server.on("GET", `/campaigns/${C}/dungeon-areas/l1/runtime`, options.runtime ?? { body: runtime() })
    server.on("GET", `/campaigns/${C}/entities/l1/lifecycle`, { body: lifecycle })
    server.on("GET", `/campaigns/${C}/entities/l1/provenance`, { body: { entity_id: "l1", links: [], transitions: [], supersedes: [] } })
    server.on("GET", `/campaigns/${C}/entities/l1/revisions`, { body: { revisions: [] } })
    server.on("GET", `/campaigns/${C}/sources`, { body: { items: [], source_types: [], limits: {} } })
    // The authoring view and its options: only a caller with the world's private side reads them.
    server.on("GET", `/campaigns/${C}/authoring/dungeon-areas/l1`, {
        body: {
            ...runtime(),
            summary: null,
            area_type: "room",
            dimensions: null,
            environmental_properties: null,
            dungeon: { entity_id: "d1", name: "Crypt", canon_status: "canon", lifecycle_status: "active" },
            dungeon_row_version: 1,
            canon_status: "canon",
            lifecycle_status: "active",
            row_version: 2,
            available_actions: ["update"],
            blocked_actions: [],
            structure_actions: [],
            features: [],
            hazards: [],
            interactables: [],
            connections: [],
        },
    })
    server.on("GET", `/campaigns/${C}/authoring/dungeons/options`, {
        body: {
            can_create: true,
            connection_types: [],
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
        },
    })
    server.on("POST", `/campaigns/${C}/dungeon-areas/l1/state`, {
        body: { dungeon_area_id: "l1", kind: "hazard", target_id: "h1", changed: true },
    })
    options.extra?.(server)
    const rendered = renderAuthoringRoutes({
        initialEntry: `/app/${C}/world/location/l1?section=area-now`,
        bootstrap: bootstrapWith({
            campaigns: [
                {
                    ...sessionBootstrapFixture.campaigns[0]!,
                    campaign_id: C,
                    capabilities: ["canon.edit", "campaign.view"],
                    world_capabilities: [...options.worldCapabilities],
                },
            ],
        }),
        routes: [{ path: "/app/:campaignId/world/:category/:entityId", element: <CampaignWorldDetailPage /> }],
    })
    return { server, ...rendered }
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("Area now for a campaign GM with no world role", () => {
    it("lists what can be recorded from the runtime projection, with no private-authoring request", async () => {
        const { server } = setup({ authoring: CAMPAIGN_ONLY_RECORD_AUTHORING, worldCapabilities: NO_WORLD_CAPABILITIES })
        expect(await screen.findByRole("heading", { level: 2, name: "Area now" })).toBeVisible()
        const list = await screen.findByRole("list", { name: "What can be recorded" })
        expect(within(list).getByText(/Spike trap/)).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Change status of Spike trap" })).toBeEnabled()
        expect(server.calls.map((c) => c.path).filter((p) => PRIVATE.test(p))).toEqual([])
        expect(server.calls.some((c) => /\/dungeon-areas\/l1\/runtime$/.test(c.path))).toBe(true)
    })

    it("records a status against the event it was read at", async () => {
        const { server } = setup({ authoring: CAMPAIGN_ONLY_RECORD_AUTHORING, worldCapabilities: NO_WORLD_CAPABILITIES })
        fireEvent.click(await screen.findByRole("button", { name: "Change status of Spike trap" }))
        const select = await screen.findByRole("combobox", { name: /status/i })
        fireEvent.change(select, { target: { value: "triggered" } })
        fireEvent.click(screen.getByRole("button", { name: /^(Save|Record)/ }))
        await waitFor(() => expect(server.callsTo("POST", `/campaigns/${C}/dungeon-areas/l1/state`)).toHaveLength(1))
        expect(server.callsTo("POST", `/campaigns/${C}/dungeon-areas/l1/state`)[0]!.body).toMatchObject({
            kind: "hazard",
            target_id: "h1",
            expected_last_event_id: "ev1",
            hazard_status: "triggered",
        })
        expect(server.calls.map((c) => c.path).filter((p) => AUTHORING.test(p))).toEqual([])
    })

    it("reports a recorded status whose runtime re-read fails, holds further commands, and recovers by reading only", async () => {
        let readFails = false
        const { server } = setup({
            authoring: CAMPAIGN_ONLY_RECORD_AUTHORING,
            worldCapabilities: NO_WORLD_CAPABILITIES,
            runtime: () => (readFails ? { status: 500, body: {} } : { body: runtime() }),
            extra: (srv) =>
                srv.on("POST", `/campaigns/${C}/dungeon-areas/l1/state`, () => {
                    readFails = true
                    return { body: { dungeon_area_id: "l1", kind: "hazard", target_id: "h1", changed: true } }
                }),
        })
        fireEvent.click(await screen.findByRole("button", { name: "Change status of Spike trap" }))
        fireEvent.change(await screen.findByRole("combobox", { name: /status/i }), { target: { value: "triggered" } })
        fireEvent.click(screen.getByRole("button", { name: /^(Save|Record)/ }))
        await waitFor(() => expect(server.callsTo("POST", `/campaigns/${C}/dungeon-areas/l1/state`)).toHaveLength(1))

        expect(await screen.findByText(/Hazard status saved\. The latest dungeon could not be loaded/)).toBeInTheDocument()
        expect(screen.getByTestId("authoring-announcer")).not.toHaveTextContent(/^Hazard status saved/)
        // The stale event token is what every further command would name, so a save is held (the
        // editor opens, with what is typed, but cannot send).
        fireEvent.click(screen.getByRole("button", { name: "Change status of Spike trap" }))
        expect(await screen.findByRole("button", { name: /^(Save|Record)/ })).toBeDisabled()
        expect(server.callsTo("POST", `/campaigns/${C}/dungeon-areas/l1/state`)).toHaveLength(1)

        readFails = false
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        await waitFor(() => expect(screen.getByRole("button", { name: /^(Save|Record)/ })).toBeEnabled())
        await waitFor(() => expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Hazard status saved"))
        expect(server.callsTo("POST", `/campaigns/${C}/dungeon-areas/l1/state`)).toHaveLength(1)
    })

    it("keeps the rest of the record when the optional read fails, and retries only that read", async () => {
        let fail = true
        const { server } = setup({
            authoring: CAMPAIGN_ONLY_RECORD_AUTHORING,
            worldCapabilities: NO_WORLD_CAPABILITIES,
            runtime: () => (fail ? { status: 500, body: {} } : { body: runtime() }),
        })
        expect(await screen.findByText("What can be recorded here could not be loaded.")).toBeInTheDocument()
        expect(screen.getByRole("heading", { level: 1, name: "Entry hall" })).toBeInTheDocument()
        fail = false
        const before = server.calls.length
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        expect(await screen.findByRole("list", { name: "What can be recorded" })).toBeInTheDocument()
        expect(server.calls.slice(before).every((c) => c.method === "GET" && /runtime$/.test(c.path))).toBe(true)
    })

    it("says so, and leaves the record usable, when the area is not available to this caller", async () => {
        setup({ authoring: CAMPAIGN_ONLY_RECORD_AUTHORING, worldCapabilities: NO_WORLD_CAPABILITIES, runtime: NOT_FOUND })
        expect(await screen.findByText(/not available to you/)).toBeInTheDocument()
        expect(screen.getByRole("heading", { level: 1, name: "Entry hall" })).toBeInTheDocument()
    })

    it("never shows one area's recorded state under another after navigating", async () => {
        const { router } = setup({
            authoring: CAMPAIGN_ONLY_RECORD_AUTHORING,
            worldCapabilities: NO_WORLD_CAPABILITIES,
            extra: (server) => {
                server.on("GET", `/campaigns/${C}/world/locations/l2`, { body: { ...detail(CAMPAIGN_ONLY_RECORD_AUTHORING), location_id: "l2", name: "Vault" } })
                server.on("GET", `/campaigns/${C}/entities/l2/lifecycle`, { body: { ...lifecycle, entity_id: "l2" } })
                server.on("GET", `/campaigns/${C}/dungeon-areas/l2/runtime`, NOT_FOUND)
            },
        })
        expect(await screen.findByRole("list", { name: "What can be recorded" })).toBeInTheDocument()
        await router.navigate(`/app/${C}/world/location/l2?section=area-now`)
        expect(await screen.findByText(/not available to you/)).toBeInTheDocument()
        expect(screen.queryByText(/Spike trap/)).toBeNull()
    })

    it("offers nothing to record while the area is not published, and says why", async () => {
        setup({
            authoring: CAMPAIGN_ONLY_RECORD_AUTHORING,
            worldCapabilities: NO_WORLD_CAPABILITIES,
            runtime: { body: runtime({ can_set_state: false }) },
        })
        expect(await screen.findByText(/Publish Crypt first/)).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /^Change/ })).toBeNull()
    })
})

describe("Area now for a world Owner", () => {
    it("reads the runtime projection for this panel and the authoring view only for Contents", async () => {
        const { server } = setup({
            authoring: { campaign_originated: false, can_read_private: true, can_edit: true, can_review: true },
            worldCapabilities: OWNER_WORLD_CAPABILITIES,
        })
        expect(await screen.findByRole("list", { name: "What can be recorded" })).toBeInTheDocument()
        expect(server.calls.some((c) => /\/dungeon-areas\/l1\/runtime$/.test(c.path))).toBe(true)
        // Contents is the preparation of the definition: its authoring read is the owner's to make.
        await waitFor(() => expect(server.calls.some((c) => /\/authoring\/dungeon-areas\/l1$/.test(c.path))).toBe(true))
    })
})

describe("A dungeon for a campaign GM with no world role", () => {
    it("requests none of the dungeon's authoring reads", async () => {
        const { server } = setup({
            authoring: CAMPAIGN_ONLY_RECORD_AUTHORING,
            worldCapabilities: NO_WORLD_CAPABILITIES,
            extra: (srv) =>
                srv.on("GET", `/campaigns/${C}/world/locations/l1`, {
                    body: { ...detail(CAMPAIGN_ONLY_RECORD_AUTHORING), name: "Crypt", location_type_code: "dungeon", parent_location_id: null, breadcrumbs: [] },
                }),
        })
        expect(await screen.findByRole("heading", { level: 1, name: "Crypt" })).toBeInTheDocument()
        await waitFor(() => expect(server.calls.some((c) => /world\/locations\/l1$/.test(c.path))).toBe(true))
        await new Promise((resolve) => setTimeout(resolve, 200))
        expect(server.calls.map((c) => c.path).filter((p) => PRIVATE.test(p))).toEqual([])
    })

    it.each([
        ["dungeon", "Crypt", "this dungeon"],
        ["building", "Guildhall", "this place"],
    ])("calls a %s by its own kind, never 'character'", async (typeCode, name, noun) => {
        setup({
            authoring: CAMPAIGN_ONLY_RECORD_AUTHORING,
            worldCapabilities: NO_WORLD_CAPABILITIES,
            extra: (srv) =>
                srv.on("GET", `/campaigns/${C}/world/locations/l1`, {
                    body: { ...detail(CAMPAIGN_ONLY_RECORD_AUTHORING), name, location_type_code: typeCode, parent_location_id: null, breadcrumbs: [] },
                }),
        })
        await screen.findByRole("heading", { level: 1, name })
        const note = await screen.findByText(/You can read and use this/)
        expect(note).toHaveTextContent(`You can read and use ${noun} in this campaign.`)
        expect(note).not.toHaveTextContent("character")
    })
})
