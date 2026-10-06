import { fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { NpcRuntimePanel } from "./NpcRuntimePanel"

const BASE = "/campaigns/c1/characters/n1"

const TIME = {
    world_time_id: "t1",
    calendar_id: "cal",
    year: 1,
    month_number: null,
    day: null,
    hour: null,
    minute: null,
    label: null,
    precision: "year",
    sort_key: 1,
    display: "Year 1",
}

function setup(canon = "canon", capabilities = ["canon.edit"]) {
    const server = installMockServer()
    server.on("GET", /authoring\/npcs\/n1$/, { body: { npc_id: "n1", canon_status: canon, row_version: 1 } })
    server.on("GET", /npc-runtime-options/, {
        body: {
            conditions: [{ value: "c-poisoned", label: "Poisoned", code: "poisoned" }],
            resources: [{ value: "r-ki", label: "Ki points", code: "ki_points" }],
        },
    })
    server.on("GET", BASE, {
        body: {
            character_id: "n1",
            name: "Mira",
            species_code: "human",
            size_category: "medium",
            current_hit_points: 12,
            maximum_hit_points: 20,
            temporary_hit_points: null,
            exhaustion_level: null,
            death_save_successes: null,
            death_save_failures: null,
            current_location_id: null,
            active_encounter_id: null,
            conditions: [{ condition_code: "poisoned", source_description: "A dart" }],
            resources: [{ resource_code: "ki_points", current_amount: 2, maximum_amount: 4 }],
        },
    })
    server.on("GET", /world-times/, { body: { items: [TIME], next_cursor: null } })
    server.on("GET", /calendars/, { body: { calendars: [] } })
    server.on("GET", /world\/search/, {
        body: {
            items: [
                { entity_id: "l1", category: "location", entity_type_code: "settlement", name: "Stonebridge", summary: null },
            ],
            next_cursor: null,
        },
    })
    server.on("POST", new RegExp(`${BASE}/`), { body: { changed: true } })
    server.on("POST", "/campaigns/c1/travel", { body: { changed: true, moved: ["n1"], already_there: [] } })
    renderAuthoringRoutes({
        initialEntry: "/app/c1/npc",
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
        }),
        routes: [{ path: "/app/:campaignId/npc", element: <NpcRuntimePanel campaignId="c1" characterId="n1" /> }],
    })
    return server
}

async function chooseTime() {
    fireEvent.change(await screen.findByRole("combobox", { name: "When this happens" }), { target: { value: "t1" } })
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("NpcRuntimePanel", () => {
    it("shows the state of a published NPC", async () => {
        setup()
        expect(await screen.findByText("12 of 20")).toBeInTheDocument()
        expect(screen.getByText(/poisoned \(A dart\)/)).toBeInTheDocument()
        expect(screen.getByText(/ki points: 2 of 4/)).toBeInTheDocument()
    })

    it("asks to publish a draft NPC and shows no controls", async () => {
        setup("draft")
        expect(await screen.findByText(/Publish this NPC/)).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Adjust hit points" })).not.toBeInTheDocument()
    })

    it("shows nothing and sends nothing to people who cannot edit", async () => {
        const server = setup("canon", [])
        await new Promise((resolve) => setTimeout(resolve, 50))
        expect(screen.queryByRole("heading", { name: "Run this NPC" })).not.toBeInTheDocument()
        expect(server.callsTo("GET", BASE)).toHaveLength(0)
    })

    it("needs a time before anything is sent", async () => {
        const server = setup()
        const form = await screen.findByRole("form", { name: "Adjust hit points" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Change/ }), { target: { value: "-5" } })
        fireEvent.click(within(form).getByRole("button", { name: "Apply hit point change" }))
        expect(await screen.findByText(/Choose when this happens first/)).toBeInTheDocument()
        expect(server.callsTo("POST", `${BASE}/hit-points`)).toHaveLength(0)
    })

    it("adjusts hit points at the chosen time", async () => {
        const server = setup()
        await chooseTime()
        const form = await screen.findByRole("form", { name: "Adjust hit points" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Change/ }), { target: { value: "-5" } })
        fireEvent.click(within(form).getByRole("button", { name: "Apply hit point change" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/hit-points`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/hit-points`)[0]!.body).toEqual({ world_time_id: "t1", delta: -5 })
    })

    it("rejects a zero or fractional change", async () => {
        const server = setup()
        await chooseTime()
        const form = await screen.findByRole("form", { name: "Adjust hit points" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Change/ }), { target: { value: "0" } })
        fireEvent.click(within(form).getByRole("button", { name: "Apply hit point change" }))
        expect(await screen.findByText(/whole number other than zero/)).toBeInTheDocument()
        expect(server.callsTo("POST", `${BASE}/hit-points`)).toHaveLength(0)
    })

    it("adds and removes a condition", async () => {
        const server = setup()
        await chooseTime()
        const form = await screen.findByRole("form", { name: "Add a condition" })
        fireEvent.change(within(form).getByRole("combobox", { name: "Condition" }), { target: { value: "c-poisoned" } })
        fireEvent.change(within(form).getByRole("textbox", { name: /Source/ }), { target: { value: "A trap" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add condition" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/conditions`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/conditions`)[0]!.body).toEqual({
            world_time_id: "t1",
            condition_id: "c-poisoned",
            source_description: "A trap",
        })
    })

    it("removes a condition by its rules id", async () => {
        const server = setup()
        await chooseTime()
        fireEvent.click(await screen.findByRole("button", { name: "Remove Poisoned" }))
        await vi.waitFor(() =>
            expect(server.callsTo("POST", `${BASE}/conditions/c-poisoned/remove`)).toHaveLength(1),
        )
    })

    it("adjusts a resource and moves the NPC", async () => {
        const server = setup()
        await chooseTime()
        const resourceForm = await screen.findByRole("form", { name: "Adjust a resource" })
        fireEvent.change(within(resourceForm).getByRole("combobox", { name: "Resource" }), { target: { value: "r-ki" } })
        fireEvent.change(within(resourceForm).getByRole("textbox", { name: /Change/ }), { target: { value: "-1" } })
        fireEvent.click(within(resourceForm).getByRole("button", { name: "Adjust resource" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/resources`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/resources`)[0]!.body).toEqual({
            world_time_id: "t1",
            resource_definition_id: "r-ki",
            delta: -1,
        })
        const move = screen.getByRole("form", { name: "Move this NPC" })
        fireEvent.focus(within(move).getByRole("combobox", { name: "Move to" }))
        fireEvent.click(await within(move).findByRole("option", { name: /Stonebridge/ }))
        await vi.waitFor(() =>
            expect(within(move).getByRole("button", { name: "Move NPC" })).toBeEnabled(),
        )
        fireEvent.click(within(move).getByRole("button", { name: "Move NPC" }))
        await vi.waitFor(() => expect(server.callsTo("POST", "/campaigns/c1/travel")).toHaveLength(1))
        expect(server.callsTo("POST", "/campaigns/c1/travel")[0]!.body).toEqual({
            destination_location_id: "l1",
            character_ids: ["n1"],
            party_id: null,
            route_id: null,
            world_time_id: "t1",
        })
    })
})
