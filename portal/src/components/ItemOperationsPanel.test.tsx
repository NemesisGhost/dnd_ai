import { fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { ItemOperationsPanel } from "./ItemOperationsPanel"

const VIEW_PATH = "/campaigns/c1/authoring/items/i1"
const OP = (name: string): string => `/campaigns/c1/items/i1/${name}`

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

const ALDRIC = { entity_id: "n1", name: "Aldric", entity_type_code: "player_character" }

function view(overrides: object = {}) {
    return {
        item_instance_id: "i1",
        name: "Moonblade",
        summary: null,
        origin_notes: null,
        item_definition_id: "d1",
        definition_name: "Longsword",
        category: "weapon",
        category_label: "Weapon",
        rarity: "rare",
        requires_attunement: false,
        weight: null,
        canon_status: "canon",
        lifecycle_status: "active",
        row_version: 3,
        is_container: false,
        quantity: 1,
        condition_percentage: null,
        is_equipped: false,
        is_destroyed: false,
        last_event_id: "e1",
        holder: ALDRIC,
        container: null,
        location: null,
        owner: ALDRIC,
        attuned_to: null,
        available_actions: [],
        blocked_actions: [],
        can_operate: true,
        ...overrides,
    }
}

function setup(current: object = view(), capabilities = ["canon.edit"]) {
    const server = installMockServer()
    server.on("GET", VIEW_PATH, () => ({ body: current }))
    server.on("GET", /world-times/, { body: { items: [TIME], next_cursor: null } })
    server.on("GET", /calendars/, { body: { calendars: [] } })
    server.on("GET", /world\/search/, {
        body: {
            items: [
                { entity_id: "n1", category: "character", entity_type_code: "player_character", name: "Aldric", summary: null, canon_status: "canon" },
                { entity_id: "l1", category: "location", entity_type_code: "settlement", name: "Stonebridge", summary: null },
            ],
            next_cursor: null,
        },
    })
    server.on("POST", /\/items\/i1\//, { body: view({ last_event_id: "e2" }) })
    renderAuthoringRoutes({
        initialEntry: "/app/c1/item",
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
        }),
        routes: [{ path: "/app/:campaignId/item", element: <ItemOperationsPanel campaignId="c1" itemId="i1" /> }],
    })
    return server
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("ItemOperationsPanel", () => {
    it("shows nothing and sends nothing to people who cannot edit", async () => {
        const server = setup(view(), [])
        await new Promise((resolve) => setTimeout(resolve, 50))
        expect(screen.queryByRole("heading", { name: "Run this item" })).not.toBeInTheDocument()
        expect(server.callsTo("GET", VIEW_PATH)).toHaveLength(0)
    })

    it("asks to publish a draft item and shows no controls", async () => {
        setup(view({ canon_status: "draft", can_operate: false }))
        expect(await screen.findByText(/Publish this item/)).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Equip" })).not.toBeInTheDocument()
    })

    it("states where the item is and its condition", async () => {
        setup(view({ condition_percentage: 60, quantity: 3 }))
        expect((await screen.findAllByText("Aldric", { selector: "dd" })).length).toBe(2)
        expect(screen.getByText("60%")).toBeInTheDocument()
        expect(screen.getByText("3")).toBeInTheDocument()
    })

    it("awards an unplaced item against the token it saw", async () => {
        const server = setup(view({ holder: null, owner: null, last_event_id: null }))
        const form = await screen.findByRole("form", { name: "Award this item" })
        fireEvent.focus(within(form).getByRole("combobox", { name: "Award to" }))
        fireEvent.click(await within(form).findByRole("option", { name: /Aldric/ }))
        fireEvent.change(within(form).getByRole("textbox", { name: "Quantity" }), { target: { value: "2" } })
        fireEvent.click(within(form).getByRole("button", { name: "Award item" }))
        await vi.waitFor(() => expect(server.callsTo("POST", OP("award"))).toHaveLength(1))
        expect(server.callsTo("POST", OP("award"))[0]!.body).toEqual({
            expected_last_event_id: null,
            holder_entity_id: "n1",
            quantity: 2,
            set_owner: true,
        })
    })

    it("refuses an award without a holder", async () => {
        const server = setup(view({ holder: null, owner: null, last_event_id: null }))
        const form = await screen.findByRole("form", { name: "Award this item" })
        fireEvent.click(within(form).getByRole("button", { name: "Award item" }))
        expect(await screen.findByText(/Choose who receives it/)).toBeInTheDocument()
        expect(server.callsTo("POST", OP("award"))).toHaveLength(0)
    })

    it("equips and unequips", async () => {
        const server = setup()
        fireEvent.click(await screen.findByRole("button", { name: "Equip" }))
        await vi.waitFor(() => expect(server.callsTo("POST", OP("equip"))).toHaveLength(1))
        expect(server.callsTo("POST", OP("equip"))[0]!.body).toEqual({ expected_last_event_id: "e1" })
    })

    it("offers unequip for an equipped item", async () => {
        setup(view({ is_equipped: true }))
        expect(await screen.findByRole("button", { name: "Unequip" })).toBeInTheDocument()
    })

    it("damages by a whole amount and rejects a bad one", async () => {
        const server = setup()
        const form = await screen.findByRole("form", { name: "Change this item" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Amount/ }), { target: { value: "0" } })
        fireEvent.click(within(form).getByRole("button", { name: "Damage" }))
        expect(await screen.findByText(/whole number from 1 to 100/)).toBeInTheDocument()
        expect(server.callsTo("POST", OP("damage"))).toHaveLength(0)
        fireEvent.change(within(form).getByRole("textbox", { name: /Amount/ }), { target: { value: "30" } })
        fireEvent.click(within(form).getByRole("button", { name: "Damage" }))
        await vi.waitFor(() => expect(server.callsTo("POST", OP("damage"))).toHaveLength(1))
        expect(server.callsTo("POST", OP("damage"))[0]!.body).toEqual({
            expected_last_event_id: "e1",
            amount: 30,
        })
    })

    it("moves the item to a place and to another character", async () => {
        const server = setup()
        const place = await screen.findByRole("form", { name: "Leave this item at a place" })
        fireEvent.focus(within(place).getByRole("combobox", { name: "Leave at" }))
        fireEvent.click(await within(place).findByRole("option", { name: /Stonebridge/ }))
        fireEvent.click(within(place).getByRole("button", { name: "Leave item" }))
        await vi.waitFor(() => expect(server.callsTo("POST", OP("transfer"))).toHaveLength(1))
        expect(server.callsTo("POST", OP("transfer"))[0]!.body).toEqual({
            expected_last_event_id: "e1",
            location_id: "l1",
        })
    })

    it("includes the chosen time", async () => {
        const server = setup()
        fireEvent.change(await screen.findByRole("combobox", { name: "When this happens" }), {
            target: { value: "t1" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Equip" }))
        await vi.waitFor(() => expect(server.callsTo("POST", OP("equip"))).toHaveLength(1))
        expect(server.callsTo("POST", OP("equip"))[0]!.body).toEqual({
            expected_last_event_id: "e1",
            world_time_id: "t1",
        })
    })

    it("attunes to the holder and ends an attunement", async () => {
        const server = setup(view({ requires_attunement: true }))
        fireEvent.click(await screen.findByRole("button", { name: "Attune to Aldric" }))
        await vi.waitFor(() => expect(server.callsTo("POST", OP("attune"))).toHaveLength(1))
        expect(server.callsTo("POST", OP("attune"))[0]!.body).toEqual({
            expected_last_event_id: "e1",
            character_id: "n1",
        })
    })

    it("offers to end an attunement", async () => {
        setup(view({ requires_attunement: true, attuned_to: ALDRIC }))
        expect(await screen.findByRole("button", { name: "End attunement" })).toBeInTheDocument()
    })

    it("asks before destroying", async () => {
        const server = setup()
        fireEvent.click(await screen.findByRole("button", { name: "Destroy item" }))
        const dialog = await screen.findByRole("dialog", { name: "Destroy this item?" })
        expect(server.callsTo("POST", OP("destroy"))).toHaveLength(0)
        fireEvent.click(within(dialog).getByRole("button", { name: "Destroy item" }))
        await vi.waitFor(() => expect(server.callsTo("POST", OP("destroy"))).toHaveLength(1))
    })

    it("explains a destroyed item and offers nothing", async () => {
        setup(view({ is_destroyed: true }))
        expect(await screen.findByText(/This item is destroyed/)).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Equip" })).not.toBeInTheDocument()
    })

    it("explains a stale operation and a refused one", async () => {
        const server = setup()
        server.on("POST", OP("equip"), {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        fireEvent.click(await screen.findByRole("button", { name: "Equip" }))
        expect(await screen.findByText(/Load latest version/i)).toBeInTheDocument()
    })

    it("explains an item that is attuned", async () => {
        const server = setup()
        server.on("POST", OP("equip"), {
            status: 409,
            body: { error: { code: "item_attuned", message: "m", correlation_id: "c" } },
        })
        fireEvent.click(await screen.findByRole("button", { name: "Equip" }))
        expect(await screen.findByText(/End the attunement first/)).toBeInTheDocument()
    })
})
