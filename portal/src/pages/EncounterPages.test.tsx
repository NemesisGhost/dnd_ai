import { fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { PrepareEncounterPage, PreparedEncounterPage } from "./EncounterPages"
import { SessionEncountersSection } from "../components/SessionEncountersSection"

const AUTH = "/campaigns/c1/authoring/encounters"
const BASE = "/campaigns/c1/encounters"

const OPTIONS = {
    sides: [
        { value: "party", label: "Party" },
        { value: "ally", label: "Ally" },
        { value: "enemy", label: "Enemy" },
        { value: "neutral", label: "Neutral" },
    ],
    limits: { summary_max_length: 4000, initiative_min: -100, initiative_max: 1000, max_participants: 50 },
}

function encounter(overrides: object = {}) {
    return {
        encounter_id: "e1",
        session_id: "s1",
        status: "pending",
        can_prepare: true,
        summary: "Ambush",
        location_id: "l1",
        location_name: "Stonebridge",
        world_time_id: "t1",
        participants: [
            {
                encounter_participant_id: "p1",
                participant_entity_id: "n1",
                name: "Aldric",
                entity_type_code: "player_character",
                side: "party",
                initiative: 14,
            },
        ],
        ...overrides,
    }
}

afterEach(() => {
    vi.unstubAllGlobals()
})

function setup(entry: string, view: object = encounter(), capabilities = ["canon.edit"]) {
    const server = installMockServer()
    server.on("GET", `${AUTH}/options`, { body: OPTIONS })
    server.on("GET", `${AUTH}/e1`, () => ({ body: view }))
    server.on("GET", /world\/search/, {
        body: {
            items: [
                { entity_id: "n2", category: "character", entity_type_code: "npc", name: "Bryn", summary: null, canon_status: "canon" },
                { entity_id: "l2", category: "location", entity_type_code: "settlement", name: "Northmark", summary: null },
            ],
            next_cursor: null,
        },
    })
    server.on("POST", `${BASE}/prepare`, { status: 201, body: encounter({ encounter_id: "e2", participants: [] }) })
    server.on("POST", new RegExp(`${BASE}/e1/`), { body: encounter() })
    renderAuthoringRoutes({
        initialEntry: entry,
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
        }),
        routes: [
            { path: "/app/:campaignId/sessions/:sessionId/encounters/new", element: <PrepareEncounterPage /> },
            { path: "/app/:campaignId/sessions/:sessionId/encounters/:encounterId", element: <PreparedEncounterPage /> },
        ],
    })
    return server
}

describe("PrepareEncounterPage", () => {
    it("prepares a pending encounter in the session", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/new")
        const form = await screen.findByRole("form", { name: "Prepare an encounter" })
        fireEvent.focus(within(form).getByRole("combobox", { name: /Where it happens/ }))
        fireEvent.click(await within(form).findByRole("option", { name: /Northmark/ }))
        fireEvent.change(within(form).getByRole("textbox", { name: /Summary/ }), { target: { value: "  Gate fight " } })
        fireEvent.click(within(form).getByRole("button", { name: "Prepare encounter" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/prepare`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/prepare`)[0]!.body).toEqual({
            session_id: "s1",
            location_id: "l2",
            summary: "Gate fight",
        })
    })

    it("refuses people without canon.edit", async () => {
        setup("/app/c1/sessions/s1/encounters/new", encounter(), [])
        expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/)
    })
})

describe("PreparedEncounterPage", () => {
    it("shows the participants with their side and initiative", async () => {
        setup("/app/c1/sessions/s1/encounters/e1")
        expect(await screen.findByText("Aldric")).toBeInTheDocument()
        expect(screen.getByRole("combobox", { name: "Side of Aldric" })).toHaveValue("party")
        expect(screen.getByRole("textbox", { name: "Initiative of Aldric" })).toHaveValue("14")
    })

    it("adds a character with a side and initiative", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1")
        const form = await screen.findByRole("form", { name: "Add a participant" })
        fireEvent.focus(within(form).getByRole("combobox", { name: "Character" }))
        fireEvent.click(await within(form).findByRole("option", { name: /Bryn/ }))
        fireEvent.change(within(form).getByRole("combobox", { name: "Side" }), { target: { value: "enemy" } })
        fireEvent.change(within(form).getByRole("textbox", { name: /Initiative/ }), { target: { value: "9" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add participant" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/e1/participants`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/e1/participants`)[0]!.body).toEqual({
            participant_entity_id: "n2",
            side: "enemy",
            initiative: 9,
        })
    })

    it("needs a character and a whole-number initiative", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1")
        const form = await screen.findByRole("form", { name: "Add a participant" })
        fireEvent.click(within(form).getByRole("button", { name: "Add participant" }))
        expect(await screen.findByText(/Choose a character to add/)).toBeInTheDocument()
        expect(server.callsTo("POST", `${BASE}/e1/participants`)).toHaveLength(0)
    })

    it("changes a participant's side and initiative, and removes one", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1")
        const form = await screen.findByRole("form", { name: "Change Aldric" })
        fireEvent.change(within(form).getByRole("combobox", { name: "Side of Aldric" }), { target: { value: "ally" } })
        fireEvent.change(within(form).getByRole("textbox", { name: "Initiative of Aldric" }), { target: { value: "" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save Aldric" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/e1/participants/p1/update`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/e1/participants/p1/update`)[0]!.body).toEqual({
            side: "ally",
            initiative: null,
        })
        // The first command finishes (and announces) before the next one can start.
        await screen.findByText("Aldric updated")
        fireEvent.click(screen.getByRole("button", { name: "Remove Aldric" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/e1/participants/p1/remove`)).toHaveLength(1))
    })

    it("saves the place and summary", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1")
        const form = await screen.findByRole("form", { name: "Encounter details" })
        fireEvent.change(within(form).getByRole("textbox", { name: "Summary" }), { target: { value: "Changed" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save details" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/e1/update`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/e1/update`)[0]!.body).toEqual({
            location_id: "l1",
            summary: "Changed",
        })
    })

    it("is read-only once the encounter has started", async () => {
        setup("/app/c1/sessions/s1/encounters/e1", encounter({ status: "active", can_prepare: false }))
        expect(await screen.findByText(/Preparation is over/)).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Add a participant" })).not.toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Remove Aldric" })).not.toBeInTheDocument()
        expect(screen.getByText(/initiative 14/)).toBeInTheDocument()
    })

    it("explains a refusal because it already started", async () => {
        const server = setup("/app/c1/sessions/s1/encounters/e1")
        server.on("POST", `${BASE}/e1/update`, {
            status: 409,
            body: { error: { code: "encounter_not_pending", message: "m", correlation_id: "c" } },
        })
        const form = await screen.findByRole("form", { name: "Encounter details" })
        fireEvent.click(within(form).getByRole("button", { name: "Save details" }))
        expect(await screen.findByText(/already started or finished/)).toBeInTheDocument()
    })
})

describe("SessionEncountersSection", () => {
    it("lists the session's encounters with a link to prepare another", async () => {
        const server = installMockServer()
        server.on("GET", `${AUTH}?session_id=s1`, {
            body: {
                items: [
                    { encounter_id: "e1", status: "pending", summary: "Ambush", location_name: "Stonebridge", participant_count: 2 },
                ],
            },
        })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/x",
            bootstrap: bootstrapWith({
                campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1" }],
            }),
            routes: [
                { path: "/app/:campaignId/x", element: <SessionEncountersSection campaignId="c1" sessionId="s1" /> },
            ],
        })
        expect(await screen.findByRole("link", { name: "Ambush" })).toHaveAttribute(
            "href",
            "/app/c1/sessions/s1/encounters/e1",
        )
        expect(screen.getByText(/pending, at Stonebridge, 2 participants/)).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Prepare an encounter" })).toHaveAttribute(
            "href",
            "/app/c1/sessions/s1/encounters/new",
        )
    })
})
