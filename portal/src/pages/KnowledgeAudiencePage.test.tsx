import { fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { KnowledgeAudiencePage } from "./KnowledgeAudiencePage"

const BASE = "/campaigns/c1/knowledge"

const AUDIENCE = {
    knowledge_item_id: "k1",
    awareness_levels: ["aware", "rumored", "suspected"],
    transfer_methods: ["dialogue", "rumor"],
    parties: [
        { party_knowledge_id: "pk1", party_id: "p1", party_name: "Red Company", awareness_level: "aware" },
    ],
    knowers: [
        {
            entity_knowledge_id: "ek1",
            knower_entity_id: "n1",
            knower_name: "Mira",
            knower_type: "npc",
            awareness_level: "suspected",
            confidence: 60,
            interpretation: "He only seems pale.",
            willing_to_share: true,
            last_event_id: "ev1",
        },
    ],
    public: [
        { public_knowledge_id: "pub1", location_id: "l1", location_name: "Stonebridge", awareness_level: "rumored" },
    ],
}

const PARTIES = {
    can_create: true,
    items: [
        { party_id: "p1", name: "Red Company", description: null, lifecycle_status: "active", row_version: 1 },
        { party_id: "p2", name: "Blue Company", description: null, lifecycle_status: "active", row_version: 1 },
    ],
}

afterEach(() => {
    vi.unstubAllGlobals()
})

function setup(capabilities = ["canon.edit"]) {
    const server = installMockServer()
    server.on("GET", `${BASE}/k1/audience`, () => ({ body: AUDIENCE }))
    server.on("GET", /\/parties/, { body: PARTIES })
    server.on("GET", /world\/search/, {
        body: {
            items: [{ entity_id: "n2", category: "character", entity_type_code: "npc", name: "Tom", summary: null }],
            next_cursor: null,
        },
    })
    server.on("POST", new RegExp(BASE), {
        body: { knowledge_item_id: "k1", record_id: "r1", changed: true, event_id: "e1" },
    })
    renderAuthoringRoutes({
        initialEntry: "/app/c1/knowledge/k1/audience",
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
        }),
        routes: [
            { path: "/app/:campaignId/knowledge/:knowledgeItemId/audience", element: <KnowledgeAudiencePage /> },
        ],
    })
    return server
}

describe("KnowledgeAudiencePage", () => {
    it("shows each audience", async () => {
        setup()
        expect(await screen.findByText(/Red Company: Aware/)).toBeInTheDocument()
        const card = screen.getByRole("article", { name: "Belief of Mira" })
        expect(within(card).getByText(/Suspects, 60% sure/)).toBeInTheDocument()
        expect(within(card).getByText("He only seems pale.")).toBeInTheDocument()
        expect(screen.getByText(/Stonebridge: Has heard a rumor/)).toBeInTheDocument()
    })

    it("offers only parties that do not know it yet, and tells one", async () => {
        const server = setup()
        const form = await screen.findByRole("form", { name: "Tell a party" })
        const select = within(form).getByRole("combobox", { name: /Party/ })
        expect(within(select).queryByRole("option", { name: "Red Company" })).not.toBeInTheDocument()
        fireEvent.click(within(form).getByRole("button", { name: "Tell party" }))
        expect(await within(form).findByText("Choose a party.")).toBeInTheDocument()
        expect(server.callsTo("POST", `${BASE}/k1/reveal-to-party`)).toHaveLength(0)
        fireEvent.change(select, { target: { value: "p2" } })
        fireEvent.click(within(form).getByRole("button", { name: "Tell party" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/k1/reveal-to-party`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/k1/reveal-to-party`)[0]!.body).toEqual({
            party_id: "p2",
            awareness_level: "aware",
        })
    })

    it("changes a belief naming the event that last wrote it", async () => {
        const server = setup()
        fireEvent.click(await screen.findByRole("button", { name: "Change belief of Mira" }))
        const form = await screen.findByRole("form", { name: "Change belief of Mira" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Confidence/ }), { target: { value: "90" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save belief" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/knowers/ek1/belief`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/knowers/ek1/belief`)[0]!.body).toEqual({
            expected_last_event_id: "ev1",
            awareness_level: "suspected",
            confidence: 90,
            interpretation: "He only seems pale.",
        })
    })

    it("rejects a confidence outside 0 to 100 without sending", async () => {
        const server = setup()
        fireEvent.click(await screen.findByRole("button", { name: "Change belief of Mira" }))
        const form = await screen.findByRole("form", { name: "Change belief of Mira" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Confidence/ }), { target: { value: "150" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save belief" }))
        expect(await within(form).findByText(/whole number from 0 to 100/)).toBeInTheDocument()
        expect(server.callsTo("POST", `${BASE}/knowers/ek1/belief`)).toHaveLength(0)
    })

    it("records that someone learned it, picking them from a search", async () => {
        const server = setup()
        const form = await screen.findByRole("form", { name: "Record that someone learned this" })
        fireEvent.click(within(form).getByRole("button", { name: "Record knowledge" }))
        expect(await within(form).findByText("Choose who learned it.")).toBeInTheDocument()
        const input = within(form).getByRole("combobox", { name: /Who learned it/ })
        fireEvent.focus(input)
        fireEvent.click((await within(form).findAllByRole("option", { name: /Tom/ }))[0]!)
        fireEvent.click(within(form).getByRole("button", { name: "Record knowledge" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/k1/learn`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/k1/learn`)[0]!.body).toMatchObject({
            knower_entity_id: "n2",
            awareness_level: "aware",
            confidence: null,
        })
    })

    it("makes it public at a searched location", async () => {
        const server = setup()
        const form = await screen.findByRole("form", { name: "Make this public" })
        const input = within(form).getByRole("combobox", { name: /Location/ })
        fireEvent.focus(input)
        fireEvent.click(await within(form).findByRole("option", { name: /Tom/ }))
        fireEvent.click(within(form).getByRole("button", { name: "Make public" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/k1/make-public`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/k1/make-public`)[0]!.body).toEqual({
            location_id: "n2",
            awareness_level: "aware",
        })
    })

    it("explains a refused command", async () => {
        const server = setup()
        server.on("POST", `${BASE}/k1/reveal-to-party`, {
            status: 409,
            body: { error: { code: "clock_required", message: "m", correlation_id: "c" } },
        })
        const form = await screen.findByRole("form", { name: "Tell a party" })
        fireEvent.change(within(form).getByRole("combobox", { name: /Party/ }), { target: { value: "p2" } })
        fireEvent.click(within(form).getByRole("button", { name: "Tell party" }))
        expect(await screen.findByRole("alert")).toHaveTextContent("Set the campaign time first.")
    })

    it("refuses people without canon.edit", async () => {
        setup([])
        expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/)
    })
})
