import { fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { ItemDefinitionFormPage, ItemDefinitionsPage } from "./ItemDefinitionPages"

const BASE = "/campaigns/c1/authoring/item-definitions"

const OPTIONS = {
    categories: [
        { value: "weapon", label: "Weapon" },
        { value: "potion", label: "Potion" },
    ],
    rarities: [
        { value: "common", label: "Common" },
        { value: "rare", label: "Rare" },
    ],
    canon_states: [
        { value: "draft", label: "Draft" },
        { value: "canon", label: "Canon" },
    ],
    limits: { name_max_length: 200, description_max_length: 4000 },
}

function definition(overrides: object = {}) {
    return {
        item_definition_id: "d1",
        code: "moonblade",
        name: "Moonblade",
        category: "weapon",
        category_label: "Weapon",
        description: "Glows",
        rarity: "rare",
        requires_attunement: true,
        weight: 3,
        base_cost_gp: 1200.5,
        canon_status: "draft",
        row_version: 2,
        is_homebrew: true,
        can_edit: true,
        ...overrides,
    }
}

const GENERIC = definition({
    item_definition_id: "g1",
    code: "longsword",
    name: "Longsword",
    rarity: "common",
    canon_status: "canon",
    is_homebrew: false,
    can_edit: false,
})

afterEach(() => {
    vi.unstubAllGlobals()
})

function render(entry: string, capabilities = ["canon.edit"]) {
    const server = installMockServer()
    server.on("GET", `${BASE}/options`, { body: OPTIONS })
    server.on("GET", BASE, { body: { items: [GENERIC, definition()] } })
    server.on("GET", `${BASE}/d1`, { body: definition() })
    server.on("GET", `${BASE}/g1`, { body: GENERIC })
    server.on("POST", BASE, { status: 201, body: definition({ item_definition_id: "d2" }) })
    server.on("POST", `${BASE}/d1/update`, { body: definition({ row_version: 3 }) })
    renderAuthoringRoutes({
        initialEntry: entry,
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
        }),
        routes: [
            { path: "/app/:campaignId/item-definitions", element: <ItemDefinitionsPage /> },
            { path: "/app/:campaignId/item-definitions/new", element: <ItemDefinitionFormPage /> },
            { path: "/app/:campaignId/item-definitions/:definitionId", element: <ItemDefinitionFormPage /> },
        ],
    })
    return server
}

describe("ItemDefinitionsPage", () => {
    it("lists generic and homebrew definitions and only offers edit for homebrew", async () => {
        render("/app/c1/item-definitions")
        expect(await screen.findByText(/Longsword \(Weapon, common\)/)).toBeInTheDocument()
        expect(screen.getByText(/\(generic\)/)).toBeInTheDocument()
        expect(screen.getByText(/Moonblade \(Weapon, rare\) \(draft\)/)).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Edit Moonblade" })).toHaveAttribute(
            "href",
            "/app/c1/item-definitions/d1",
        )
        expect(screen.queryByRole("link", { name: "Edit Longsword" })).not.toBeInTheDocument()
    })

    it("filters to this world's definitions and by category", async () => {
        render("/app/c1/item-definitions")
        await screen.findByText(/Longsword/)
        fireEvent.click(screen.getByRole("checkbox", { name: /only this world/ }))
        expect(screen.queryByText(/Longsword/)).not.toBeInTheDocument()
        expect(screen.getByText(/Moonblade \(Weapon, rare\)/)).toBeInTheDocument()
        fireEvent.click(screen.getByRole("checkbox", { name: /only this world/ }))
        await screen.findByText(/Longsword/)
        fireEvent.change(screen.getByRole("combobox", { name: "Category" }), { target: { value: "potion" } })
        expect(screen.getByText("No item definitions match.")).toBeInTheDocument()
    })

    it("reads its filters from the address", async () => {
        render("/app/c1/item-definitions?homebrew=1&category=weapon")
        await screen.findByText(/Moonblade \(Weapon/)
        expect(screen.queryByText(/Longsword/)).not.toBeInTheDocument()
        expect(screen.getByRole("checkbox", { name: /only this world/ })).toBeChecked()
        expect(screen.getByRole("combobox", { name: "Category" })).toHaveValue("weapon")
    })

    it("keeps the filters when the form returns to the list", async () => {
        render("/app/c1/item-definitions?homebrew=1")
        fireEvent.click(await screen.findByRole("link", { name: "Edit Moonblade" }))
        const crumb = await screen.findByRole("link", { name: "Item definitions" })
        expect(crumb).toHaveAttribute("href", "/app/c1/item-definitions?homebrew=1")
        fireEvent.click(crumb)
        await screen.findByText(/Moonblade \(Weapon/)
        expect(screen.queryByText(/Longsword/)).not.toBeInTheDocument()
    })

    it("refuses people without canon.edit", async () => {
        render("/app/c1/item-definitions", [])
        expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/)
    })
})

describe("ItemDefinitionFormPage", () => {
    it("creates a definition with trimmed and parsed values", async () => {
        const server = render("/app/c1/item-definitions/new")
        const form = await screen.findByRole("form", { name: "Item definition" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Name/ }), { target: { value: "  Sunblade " } })
        fireEvent.change(within(form).getByRole("combobox", { name: /Category/ }), { target: { value: "weapon" } })
        fireEvent.change(within(form).getByRole("textbox", { name: /Weight/ }), { target: { value: "2.5" } })
        fireEvent.click(within(form).getByRole("button", { name: "Create item definition" }))
        await vi.waitFor(() => expect(server.callsTo("POST", BASE)).toHaveLength(1))
        expect(server.callsTo("POST", BASE)[0]!.body).toEqual({
            name: "Sunblade",
            category: "weapon",
            description: null,
            rarity: "common",
            requires_attunement: false,
            weight: 2.5,
            base_cost_gp: null,
            canon_status: "draft",
        })
    })

    it("explains missing and malformed fields without sending anything", async () => {
        const server = render("/app/c1/item-definitions/new")
        const form = await screen.findByRole("form", { name: "Item definition" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Weight/ }), { target: { value: "heavy" } })
        fireEvent.click(within(form).getByRole("button", { name: "Create item definition" }))
        expect(await screen.findByText("Enter a name.")).toBeInTheDocument()
        expect(screen.getByText("Choose a category.")).toBeInTheDocument()
        expect(screen.getByText(/Enter a number such as/)).toBeInTheDocument()
        expect(server.callsTo("POST", BASE)).toHaveLength(0)
    })

    it("saves an edit against the row version it loaded", async () => {
        const server = render("/app/c1/item-definitions/d1")
        const form = await screen.findByRole("form", { name: "Item definition" })
        expect(within(form).getByRole("textbox", { name: /Name/ })).toHaveValue("Moonblade")
        fireEvent.change(within(form).getByRole("combobox", { name: /Status/ }), { target: { value: "canon" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save item definition" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/d1/update`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/d1/update`)[0]!.body).toMatchObject({
            expected_row_version: 2,
            name: "Moonblade",
            canon_status: "canon",
            weight: 3,
            base_cost_gp: 1200.5,
            requires_attunement: true,
        })
    })

    it("explains a stale save", async () => {
        const server = render("/app/c1/item-definitions/d1")
        server.on("POST", `${BASE}/d1/update`, {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        const form = await screen.findByRole("form", { name: "Item definition" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Name/ }), { target: { value: "Changed" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save item definition" }))
        expect(await screen.findByText(/Load latest version/i)).toBeInTheDocument()
    })

    it("does not offer a form for a generic definition", async () => {
        render("/app/c1/item-definitions/g1")
        expect(await screen.findByText(/generic definition from the ruleset/)).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Item definition" })).not.toBeInTheDocument()
    })
})

describe("Item definitions without the world's private-read authority", () => {
    function renderWithout(entry: string, worldCapabilities: string[]) {
        const server = installMockServer()
        server.on("GET", /.*/, { status: 403, body: { error: { code: "world_authority_required", message: "m", correlation_id: "x" } } })
        renderAuthoringRoutes({
            initialEntry: entry,
            bootstrap: bootstrapWith({
                campaigns: [
                    {
                        ...sessionBootstrapFixture.campaigns[0]!,
                        campaign_id: "c1",
                        capabilities: ["canon.edit"],
                        world_capabilities: worldCapabilities,
                    },
                ],
            }),
            routes: [
                { path: "/app/:campaignId/item-definitions", element: <ItemDefinitionsPage /> },
                { path: "/app/:campaignId/item-definitions/new", element: <ItemDefinitionFormPage /> },
                { path: "/app/:campaignId/item-definitions/:definitionId", element: <ItemDefinitionFormPage /> },
            ],
        })
        return server
    }

    it.each([
        ["the catalog", "/app/c1/item-definitions"],
        ["a new definition", "/app/c1/item-definitions/new"],
        ["an existing definition", "/app/c1/item-definitions/d1"],
    ])("explains %s is for world-role holders and requests nothing", async (_name, entry) => {
        const server = renderWithout(entry, ["world.view", "world.canon.read"])
        const alert = await screen.findByRole("alert")
        expect(alert).toHaveTextContent(/authoring catalog, including drafts, and need a world role/)
        expect(alert).toHaveTextContent(/choose a published definition when you create an item/)
        expect(screen.queryByText(/could not be loaded/)).toBeNull()
        expect(screen.queryByRole("link", { name: "New item definition" })).toBeNull()
        await new Promise((resolve) => setTimeout(resolve, 50))
        expect(server.calls).toEqual([])
    })

    it("still loads the catalog and its actions for an Editor", async () => {
        const server = installMockServer()
        server.on("GET", `${BASE}/options`, { body: OPTIONS })
        server.on("GET", BASE, { body: { items: [GENERIC, definition()] } })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/item-definitions",
            bootstrap: bootstrapWith({
                campaigns: [
                    {
                        ...sessionBootstrapFixture.campaigns[0]!,
                        campaign_id: "c1",
                        capabilities: ["canon.edit"],
                        world_capabilities: ["world.view", "world.canon.read", "world.canon.read_private", "world.canon.edit"],
                    },
                ],
            }),
            routes: [{ path: "/app/:campaignId/item-definitions", element: <ItemDefinitionsPage /> }],
        })
        expect(await screen.findByRole("link", { name: "Edit Moonblade" })).toBeInTheDocument()
        expect(server.callsTo("GET", BASE)).toHaveLength(1)
    })

    it("lets a Reviewer read the catalog without create or edit actions", async () => {
        const server = installMockServer()
        server.on("GET", `${BASE}/options`, { body: OPTIONS })
        server.on("GET", BASE, { body: { items: [GENERIC, definition()] } })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/item-definitions",
            bootstrap: bootstrapWith({
                campaigns: [
                    {
                        ...sessionBootstrapFixture.campaigns[0]!,
                        campaign_id: "c1",
                        capabilities: ["canon.edit"],
                        world_capabilities: ["world.view", "world.canon.read", "world.canon.read_private", "world.canon.review"],
                    },
                ],
            }),
            routes: [{ path: "/app/:campaignId/item-definitions", element: <ItemDefinitionsPage /> }],
        })
        // A Reviewer reads the catalog, including the world's own draft, but is offered no change:
        // creating and editing need `world.canon.edit`.
        expect(await screen.findByText(/Moonblade/)).toBeInTheDocument()
        expect(screen.getByText(/Longsword/)).toBeInTheDocument()
        expect(screen.queryByRole("link", { name: "New item definition" })).toBeNull()
        expect(screen.queryByRole("link", { name: /^Edit / })).toBeNull()
        expect(screen.getByText(/needs the world Editor role/)).toBeInTheDocument()
        expect(server.callsTo("GET", BASE)).toHaveLength(1)
    })

    it.each(["/app/c1/item-definitions/new", "/app/c1/item-definitions/d1"])(
        "explains the form %s to a Reviewer and requests nothing",
        async (entry) => {
            const server = installMockServer()
            renderAuthoringRoutes({
                initialEntry: entry,
                bootstrap: bootstrapWith({
                    campaigns: [
                        {
                            ...sessionBootstrapFixture.campaigns[0]!,
                            campaign_id: "c1",
                            capabilities: ["canon.edit"],
                            world_capabilities: ["world.view", "world.canon.read", "world.canon.read_private", "world.canon.review"],
                        },
                    ],
                }),
                routes: [
                    { path: "/app/:campaignId/item-definitions/new", element: <ItemDefinitionFormPage /> },
                    { path: "/app/:campaignId/item-definitions/:definitionId", element: <ItemDefinitionFormPage /> },
                ],
            })
            expect(await screen.findByRole("alert")).toHaveTextContent(/needs the world Editor role/)
            expect(screen.queryByRole("button", { name: /Create|Save/ })).toBeNull()
            await new Promise((resolve) => setTimeout(resolve, 50))
            expect(server.calls).toEqual([])
        },
    )
})
