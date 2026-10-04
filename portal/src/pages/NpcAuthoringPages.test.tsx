import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { TEST_CSRF, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { CreateNpcPage, EditNpcPage } from "./NpcAuthoringPages"

const OPTIONS = {
    can_create: true,
    species: [
        { species_id: "sp-human", name: "Human", ruleset_name: "D&D 5e" },
        { species_id: "sp-elf", name: "Elf", ruleset_name: "D&D 5e" },
    ],
    sizes: [
        { code: "small", label: "Small" },
        { code: "medium", label: "Medium" },
    ],
    limits: {
        name_max_length: 200,
        summary_max_length: 4000,
        text_max_length: 4000,
        change_note_max_length: 1000,
    },
}

const VIEW = {
    npc_id: "n1",
    name: "Mira",
    summary: "A baker.",
    species: { species_id: "sp-human", name: "Human" },
    size: { code: "medium", label: "Medium" },
    origin: { entity_id: "l1", name: "Hearth", canon_status: "canon", lifecycle_status: "active" },
    background: "Raised in the hills.",
    appearance: "Tall.",
    notes: "Secretly a spy.",
    canon_status: "draft",
    lifecycle_status: "active",
    row_version: 3,
    available_actions: ["update"],
    blocked_actions: [],
    field_locks: [],
}

const OPTIONS_PATH = "/campaigns/c1/authoring/npcs/options"
const CREATE_PATH = "/campaigns/c1/authoring/npcs"
const VIEW_PATH = "/campaigns/c1/authoring/npcs/n1"
const UPDATE_PATH = "/campaigns/c1/authoring/npcs/n1/update"

function mockOrigins(server: ReturnType<typeof installMockServer>) {
    server.on("GET", /\/authoring\/locations\/parent-options/, {
        body: {
            items: [
                {
                    location_id: "l2",
                    name: "Harbor",
                    category: { code: "settlement", label: "Settlement" },
                    canon_status: "canon",
                },
            ],
            next_cursor: null,
        },
    })
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("CreateNpcPage", () => {
    function setup() {
        const server = installMockServer()
        server.on("GET", OPTIONS_PATH, { body: OPTIONS })
        mockOrigins(server)
        const rendered = renderAuthoringRoutes({
            initialEntry: "/app/c1/characters/npc/new",
            routes: [
                { path: "/app/:campaignId/characters/npc/new", element: <CreateNpcPage /> },
                { path: "/app/:campaignId/world/character/:entityId", element: <p>Character detail page</p> },
                { path: "/app/:campaignId/world", element: <p>World page</p> },
            ],
        })
        return { server, ...rendered }
    }

    it("offers the server's species and sizes and labels the GM-only notes", async () => {
        setup()
        const species = await screen.findByRole("combobox", { name: /Species/ })
        expect(within(species).getAllByRole("option").map((o) => o.textContent)).toEqual([
            "Choose a species",
            "Human (D&D 5e)",
            "Elf (D&D 5e)",
        ])
        expect(
            within(screen.getByRole("combobox", { name: /Size/ }))
                .getAllByRole("option")
                .map((o) => o.textContent),
        ).toEqual(["Choose a size", "Small", "Medium"])
        const notes = screen.getByRole("textbox", { name: "GM notes" })
        expect(document.getElementById(notes.getAttribute("aria-describedby")!)).toHaveTextContent(
            "Never shown to players",
        )
    })

    it("requires a name, a species, and a size before sending anything", async () => {
        const { server } = setup()
        await screen.findByRole("combobox", { name: /Species/ })
        fireEvent.click(screen.getByRole("button", { name: "Create NPC" }))
        const summary = await screen.findByRole("alert")
        for (const message of ["Name is required.", "Choose a species.", "Choose a size."]) {
            expect(summary).toHaveTextContent(message)
        }
        expect(server.callsTo("POST", CREATE_PATH)).toHaveLength(0)
    })

    it("creates a draft and replaces history with the character detail", async () => {
        const { server, router } = setup()
        server.on("POST", CREATE_PATH, { status: 201, body: { ...VIEW, changed: true } })
        await screen.findByRole("combobox", { name: /Species/ })
        fireEvent.change(screen.getByRole("textbox", { name: /Name/ }), { target: { value: " Mira " } })
        fireEvent.change(screen.getByRole("combobox", { name: /Species/ }), { target: { value: "sp-elf" } })
        fireEvent.change(screen.getByRole("combobox", { name: /Size/ }), { target: { value: "small" } })
        fireEvent.focus(screen.getByRole("combobox", { name: "Origin" }))
        fireEvent.click(await screen.findByRole("option", { name: /Harbor/ }))
        fireEvent.change(screen.getByRole("textbox", { name: "GM notes" }), { target: { value: "Spy." } })
        fireEvent.click(screen.getByRole("button", { name: "Create NPC" }))

        await screen.findByText("Character detail page")
        const [call] = server.callsTo("POST", CREATE_PATH)
        expect(call!.headers["X-CSRF-Token"]).toBe(TEST_CSRF)
        expect(call!.body).toEqual({
            name: "Mira",
            summary: null,
            species_id: "sp-elf",
            size_category: "small",
            origin_location_id: "l2",
            background: null,
            appearance: null,
            notes: "Spy.",
        })
        expect(router.state.historyAction).toBe("REPLACE")
        expect(router.state.location.pathname).toBe("/app/c1/world/character/n1")
    })

    it("maps a refused species and origin onto their fields", async () => {
        const { server } = setup()
        server.on("POST", CREATE_PATH, {
            status: 400,
            body: { error: { code: "species_not_available", message: "m", correlation_id: "c" } },
        })
        await screen.findByRole("combobox", { name: /Species/ })
        fireEvent.change(screen.getByRole("textbox", { name: /Name/ }), { target: { value: "Mira" } })
        fireEvent.change(screen.getByRole("combobox", { name: /Species/ }), { target: { value: "sp-elf" } })
        fireEvent.change(screen.getByRole("combobox", { name: /Size/ }), { target: { value: "small" } })
        fireEvent.click(screen.getByRole("button", { name: "Create NPC" }))
        await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("not available"))
        expect(screen.getByRole("textbox", { name: /Name/ })).toHaveValue("Mira")
    })

    it("explains a refused options read", async () => {
        const server = installMockServer()
        server.on("GET", OPTIONS_PATH, { status: 403 })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/characters/npc/new",
            routes: [{ path: "/app/:campaignId/characters/npc/new", element: <CreateNpcPage /> }],
        })
        expect(await screen.findByRole("alert")).toHaveTextContent("do not have permission to create NPCs")
    })
})

describe("EditNpcPage", () => {
    function setup(initial: object = VIEW) {
        const server = installMockServer()
        let current: object = initial
        server.on("GET", VIEW_PATH, () => ({ body: current }))
        server.on("GET", OPTIONS_PATH, { body: OPTIONS })
        mockOrigins(server)
        const rendered = renderAuthoringRoutes({
            initialEntry: "/app/c1/characters/n1/edit",
            routes: [
                { path: "/app/:campaignId/characters/:characterId/edit", element: <EditNpcPage /> },
                { path: "/app/:campaignId/world/character/:entityId", element: <p>Character detail page</p> },
            ],
        })
        return { server, setCurrent: (next: object) => (current = next), ...rendered }
    }

    it("pre-fills identity and keeps a no-longer-offered species selectable", async () => {
        setup({ ...VIEW, species: { species_id: "sp-old", name: "Old Human" } })
        await screen.findByRole("textbox", { name: /Name/ })
        expect(screen.getByRole("textbox", { name: /Name/ })).toHaveValue("Mira")
        const species = screen.getByRole("combobox", { name: /Species/ })
        expect(species).toHaveValue("sp-old")
        expect(within(species).getByRole("option", { name: "Old Human" })).toBeInTheDocument()
        expect(screen.getByRole("combobox", { name: /Size/ })).toHaveValue("medium")
        expect(screen.getByRole("combobox", { name: "Origin" })).toHaveValue("Hearth")
        expect(screen.getByRole("textbox", { name: "GM notes" })).toHaveValue("Secretly a spy.")
    })

    it("saves against the loaded version", async () => {
        const { server } = setup()
        server.on("POST", UPDATE_PATH, { body: { ...VIEW, row_version: 4 } })
        await screen.findByRole("textbox", { name: /Name/ })
        fireEvent.change(screen.getByRole("combobox", { name: /Size/ }), { target: { value: "small" } })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        await screen.findByText("Character detail page")
        expect(server.callsTo("POST", UPDATE_PATH)[0]!.body).toEqual({
            expected_row_version: 3,
            name: "Mira",
            summary: "A baker.",
            species_id: "sp-human",
            size_category: "small",
            origin_location_id: "l1",
            background: "Raised in the hills.",
            appearance: "Tall.",
            notes: "Secretly a spy.",
            change_note: null,
        })
    })

    it("keeps the user's values across a stale write", async () => {
        const { server, setCurrent } = setup()
        server.on("POST", UPDATE_PATH, {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        await screen.findByRole("textbox", { name: /Name/ })
        fireEvent.change(screen.getByRole("textbox", { name: /Name/ }), { target: { value: "Mine" } })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        expect(await screen.findByRole("alert")).toHaveTextContent("Someone else changed this record")
        setCurrent({ ...VIEW, name: "Theirs", row_version: 6 })
        fireEvent.click(screen.getByRole("button", { name: "Load latest version" }))
        await waitFor(() => expect(screen.getByRole("textbox", { name: /Name/ })).toHaveValue("Theirs"))
        expect(screen.getByRole("region", { name: "Your unsaved changes" })).toHaveTextContent("Mine")
    })

    it("shows the non-disclosing state for a player character or missing NPC", async () => {
        const server = installMockServer()
        server.on("GET", VIEW_PATH, { status: 404 })
        server.on("GET", OPTIONS_PATH, { body: OPTIONS })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/characters/n1/edit",
            routes: [{ path: "/app/:campaignId/characters/:characterId/edit", element: <EditNpcPage /> }],
        })
        expect(await screen.findByRole("alert")).toHaveTextContent(
            "This NPC does not exist, or you do not have access to it.",
        )
    })

    it("explains an NPC that cannot be edited and never shows raw ids", async () => {
        setup({
            ...VIEW,
            npc_id: "3f2b8c1e-5d4a-4e7b-9c1d-2a6f8b0e4d11",
            canon_status: "proposed",
            available_actions: ["approve"],
            blocked_actions: [{ action: "update", reason: "review_in_progress" }],
        })
        const alert = await screen.findByRole("alert")
        expect(alert).toHaveTextContent("awaiting review")
        expect(document.body.textContent).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-/i)
    })
})
