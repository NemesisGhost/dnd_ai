import { fireEvent, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { CreateItemPage, EditItemPage, ItemsPage } from "./ItemPages"

const BASE = "/campaigns/c1/authoring/items"

const OPTIONS = {
    can_create: true,
    definitions: [
        { value: "d1", label: "Longsword (Weapon)", category: "weapon" },
        { value: "d2", label: "Healing Potion (Potion)", category: "potion" },
    ],
    limits: {
        name_max_length: 200,
        summary_max_length: 4000,
        origin_notes_max_length: 4000,
        change_note_max_length: 1000,
        quantity_max: 9999,
    },
}

const VIEW = {
    item_instance_id: "i1",
    name: "Moonblade",
    summary: "Glows",
    origin_notes: "A ditch",
    item_definition_id: "d1",
    definition_name: "Longsword",
    category: "weapon",
    category_label: "Weapon",
    rarity: "common",
    requires_attunement: false,
    weight: null,
    canon_status: "draft",
    lifecycle_status: "active",
    row_version: 2,
    is_container: false,
    quantity: 1,
    condition_percentage: null,
    is_equipped: false,
    is_destroyed: false,
    last_event_id: null,
    holder: null,
    container: null,
    location: null,
    owner: null,
    attuned_to: null,
    available_actions: ["update"],
    blocked_actions: [],
    can_operate: false,
}

afterEach(() => {
    vi.unstubAllGlobals()
})

function render(entry: string, capabilities = ["canon.edit"]) {
    const server = installMockServer()
    server.on("GET", `${BASE}/options`, { body: OPTIONS })
    server.on("GET", BASE, {
        body: {
            items: [
                {
                    item_instance_id: "i1",
                    name: "Moonblade",
                    definition_name: "Longsword",
                    category_label: "Weapon",
                    canon_status: "canon",
                    lifecycle_status: "active",
                    holder_name: "Aldric",
                    is_destroyed: false,
                },
                {
                    item_instance_id: "i2",
                    name: "Spare Potion",
                    definition_name: "Healing Potion",
                    category_label: "Potion",
                    canon_status: "draft",
                    lifecycle_status: "active",
                    holder_name: null,
                    is_destroyed: true,
                },
            ],
        },
    })
    server.on("GET", `${BASE}/i1`, { body: VIEW })
    server.on("POST", BASE, { status: 201, body: { ...VIEW, item_instance_id: "i3" } })
    server.on("POST", `${BASE}/i1/update`, { body: { ...VIEW, row_version: 3 } })
    renderAuthoringRoutes({
        initialEntry: entry,
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
        }),
        routes: [
            { path: "/app/:campaignId/items", element: <ItemsPage /> },
            { path: "/app/:campaignId/items/new", element: <CreateItemPage /> },
            { path: "/app/:campaignId/items/:itemId/edit", element: <EditItemPage /> },
        ],
    })
    return server
}

describe("ItemsPage", () => {
    it("lists items with who carries them and their status", async () => {
        render("/app/c1/items")
        expect(await screen.findByRole("link", { name: "Moonblade" })).toHaveAttribute(
            "href",
            "/app/c1/world/item/i1",
        )
        expect(screen.getByText(/carried by Aldric/)).toBeInTheDocument()
        expect(screen.getByText(/destroyed/)).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "New item" })).toHaveAttribute("href", "/app/c1/items/new")
    })

    it("refuses people without canon.edit", async () => {
        render("/app/c1/items", [])
        expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/)
    })
})

describe("CreateItemPage", () => {
    it("creates a draft with trimmed values", async () => {
        const server = render("/app/c1/items/new")
        fireEvent.change(await screen.findByRole("textbox", { name: /Name/ }), {
            target: { value: "  Sunblade " },
        })
        fireEvent.change(screen.getByRole("combobox", { name: /Kind of item/ }), { target: { value: "d1" } })
        fireEvent.click(screen.getByRole("button", { name: "Create item" }))
        await vi.waitFor(() => expect(server.callsTo("POST", BASE)).toHaveLength(1))
        expect(server.callsTo("POST", BASE)[0]!.body).toEqual({
            name: "Sunblade",
            summary: null,
            item_definition_id: "d1",
            origin_notes: null,
        })
    })

    it("needs a name and a kind of item", async () => {
        const server = render("/app/c1/items/new")
        await screen.findByRole("textbox", { name: /Name/ })
        fireEvent.click(screen.getByRole("button", { name: "Create item" }))
        expect(await screen.findAllByText(/Choose the kind of item/)).not.toHaveLength(0)
        expect(server.callsTo("POST", BASE)).toHaveLength(0)
    })
})

describe("EditItemPage", () => {
    it("shows the fixed definition and saves against the row version", async () => {
        const server = render("/app/c1/items/i1/edit")
        const name = await screen.findByRole("textbox", { name: /Name/ })
        expect(screen.getByText("Longsword")).toBeInTheDocument()
        expect(screen.queryByRole("combobox", { name: /Kind of item/ })).not.toBeInTheDocument()
        fireEvent.change(name, { target: { value: "Moonblade II" } })
        fireEvent.click(screen.getByRole("button", { name: /Save/ }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/i1/update`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/i1/update`)[0]!.body).toMatchObject({
            expected_row_version: 2,
            name: "Moonblade II",
            summary: "Glows",
            origin_notes: "A ditch",
        })
    })
})
