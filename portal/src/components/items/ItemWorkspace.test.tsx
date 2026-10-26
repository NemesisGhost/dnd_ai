import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { Link, useLocation } from "react-router"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../../fixtures/sessionBootstrap"
import { CampaignWorldDetailPage } from "../../pages/CampaignWorldDetailPage"
import { EditItemPage, ItemsPage } from "../../pages/ItemPages"
import { ItemWorkspacePage } from "../../pages/ItemWorkspacePage"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"

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
const STONEBRIDGE = { entity_id: "l1", name: "Stonebridge", entity_type_code: "settlement" }

function view(overrides: object = {}) {
    return {
        item_instance_id: "i1",
        name: "Moonblade",
        summary: "A pale sword.",
        origin_notes: "Found in a barrow.",
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
        available_actions: ["update", "supersede", "archive"] as string[],
        blocked_actions: [] as { action: string; reason: string }[],
        can_operate: true,
        ...overrides,
    }
}

function lifecycleOf(v: ReturnType<typeof view>) {
    return {
        entity_id: "i1",
        entity_type_code: "item_instance",
        canonical_name: v.name,
        canon_status: v.canon_status,
        lifecycle_status: v.lifecycle_status,
        row_version: v.row_version,
        lifecycle_managed: true,
        superseded_by: null,
        available_actions: v.available_actions.filter((a) => a !== "update"),
        blocked_actions: v.blocked_actions.filter((b) => b.action !== "update"),
    }
}

const PROVENANCE = {
    entity_id: "i1",
    name: "Moonblade",
    entity_type_code: "item_instance",
    canon_status: "canon",
    lifecycle_status: "active",
    created_at: "2026-10-04T00:00:00Z",
    created_by_name: "GM",
    origin: null,
    links: [],
    transitions: [],
    superseded_by: null,
    supersedes: [],
}

const OPTIONS = {
    can_create: true,
    definitions: [{ value: "d1", label: "Longsword", category: "weapon" }],
    limits: {
        name_max_length: 200,
        summary_max_length: 2000,
        origin_notes_max_length: 4000,
        change_note_max_length: 500,
        quantity_max: 9999,
    },
}

// The World list stand-in: a link that carries the browser's query as router state, exactly as the
// World category browser does.
function WorldStub() {
    const location = useLocation()
    return (
        <div>
            <p data-testid="where">{location.pathname}</p>
            <Link to="/app/c1/world/item/i1" state={{ worldSearch: "?category=item&cursor=abc" }}>
                Open from World
            </Link>
        </div>
    )
}

function Probe() {
    const location = useLocation()
    return <p data-testid="where">{`${location.pathname}${location.search}`}</p>
}

interface Setup {
    current?: ReturnType<typeof view>
    capabilities?: string[]
    worldCapabilities?: string[]
}

function setup(
    entry: string,
    { current = view(), capabilities = ["canon.edit"], worldCapabilities }: Setup = {},
) {
    const state = { current }
    const server = installMockServer()
    server.on("GET", VIEW_PATH, () => ({ body: state.current }))
    server.on("GET", "/campaigns/c1/entities/i1/lifecycle", () => ({ body: lifecycleOf(state.current) }))
    server.on("GET", "/campaigns/c1/entities/i1/provenance", { body: PROVENANCE })
    server.on("GET", "/campaigns/c1/sources", {
        body: { items: [], source_types: [{ value: "session", label: "Session" }], limits: { title_max_length: 200, reference_max_length: 500 } },
    })
    server.on("GET", "/campaigns/c1/authoring/items", {
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
            ],
        },
    })
    server.on("GET", "/campaigns/c1/authoring/items/options", { body: OPTIONS })
    server.on("GET", /world-times/, { body: { items: [TIME], next_cursor: null } })
    server.on("GET", /calendars/, { body: { calendars: [] } })
    server.on("GET", /world\/search/, {
        body: {
            items: [
                { entity_id: "n1", category: "character", entity_type_code: "player_character", name: "Aldric", summary: null, canon_status: "canon" },
                { entity_id: "n2", category: "character", entity_type_code: "npc", name: "Brea", summary: null, canon_status: "canon" },
                { entity_id: "l1", category: "location", entity_type_code: "settlement", name: "Stonebridge", summary: null },
            ],
            next_cursor: null,
        },
    })
    server.on("GET", "/campaigns/c1/world/items/i1", {
        body: {
            item_instance_id: "i1",
            name: "Moonblade",
            summary: "A pale sword.",
            item_definition_id: null,
            origin_notes: null,
            quantity: 1,
            condition_percentage: null,
            charges_current: null,
            charges_maximum: null,
            is_equipped: false,
            is_destroyed: false,
        },
    })
    server.on("POST", /\/items\/i1\//, () => ({ body: view({ last_event_id: "e2" }) }))
    server.on("POST", "/campaigns/c1/authoring/items/i1/update", { body: view() })
    const rendered = renderAuthoringRoutes({
        initialEntry: entry,
        bootstrap: bootstrapWith({
            campaigns: [
                {
                    ...sessionBootstrapFixture.campaigns[0]!,
                    campaign_id: "c1",
                    capabilities,
                    ...(worldCapabilities === undefined ? {} : { world_capabilities: worldCapabilities }),
                },
            ],
        }),
        routes: [
            { path: "/app/:campaignId/items", element: <><ItemsPage /><Probe /></> },
            { path: "/app/:campaignId/items/:itemId", element: <><ItemWorkspacePage /><Probe /></> },
            { path: "/app/:campaignId/items/:itemId/edit", element: <><EditItemPage /><Probe /></> },
            { path: "/app/:campaignId/world", element: <WorldStub /> },
            { path: "/app/:campaignId/world/:category/:entityId", element: <><CampaignWorldDetailPage /><Probe /></> },
        ],
    })
    return { server, state, ...rendered }
}

afterEach(() => {
    vi.unstubAllGlobals()
})

const where = () => screen.getByTestId("where").textContent
const waitReady = () => screen.findByRole("heading", { level: 1, name: "Moonblade" })
const panel = (key: string) => document.getElementById(`item-section-${key}-heading`)!.closest("section")!
const stageLink = (n: number) => screen.getByRole("link", { name: new RegExp(`^${n}\\.`) })
const sectionLink = (name: string) => screen.getByRole("link", { name })

describe("navigation", () => {
    it("opens an item from the item inventory with an inventory breadcrumb and no World link", async () => {
        setup("/app/c1/items")
        fireEvent.click(await screen.findByRole("link", { name: "Moonblade" }))
        await waitReady()
        await waitFor(() => expect(where()).toBe("/app/c1/items/i1?section=move"))
        const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" })
        expect(within(crumbs).getByRole("link", { name: "Item inventory" })).toHaveAttribute("href", "/app/c1/items")
        expect(within(crumbs).getByText("Moonblade")).toHaveAttribute("aria-current", "page")
        expect(screen.queryByRole("link", { name: "Back to World" })).not.toBeInTheDocument()
    })

    it("keeps World context for an item opened from the World, through section changes", async () => {
        setup("/app/c1/world")
        fireEvent.click(await screen.findByRole("link", { name: "Open from World" }))
        await waitReady()
        // The missing section is filled in by replacing the address, which must keep the origin.
        await waitFor(() => expect(where()).toBe("/app/c1/world/item/i1?section=move"))
        const back = () => screen.getByRole("link", { name: "Back to World" })
        expect(back()).toHaveAttribute("href", "/app/c1/world?category=item&cursor=abc")
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).not.toBeInTheDocument()
        fireEvent.click(sectionLink("Equip & attune"))
        await waitFor(() => expect(where()).toContain("section=equipment"))
        fireEvent.click(stageLink(1))
        await waitFor(() => expect(where()).toContain("section=details"))
        expect(back()).toHaveAttribute("href", "/app/c1/world?category=item&cursor=abc")
    })

    it("returns to the plain collections for a direct link", async () => {
        const { unmount } = setup("/app/c1/items/i1")
        await waitReady()
        expect(screen.getByRole("link", { name: "Item inventory" })).toHaveAttribute("href", "/app/c1/items")
        unmount()
        setup("/app/c1/world/item/i1")
        await waitReady()
        expect(screen.getByRole("link", { name: "Back to World" })).toHaveAttribute("href", "/app/c1/world")
    })

    it("refuses people without canon.edit on the inventory route and sends no item request", async () => {
        const { server } = setup("/app/c1/items/i1", { capabilities: [] })
        expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/)
        expect(server.callsTo("GET", VIEW_PATH)).toHaveLength(0)
    })

    it("shows the reader to a player on the World page, with no authoring request", async () => {
        const { server } = setup("/app/c1/world/item/i1", { capabilities: [] })
        expect(await screen.findByRole("heading", { level: 2, name: "In play" })).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Back to World" })).toBeInTheDocument()
        expect(screen.queryByRole("link", { name: "1. Prepare" })).not.toBeInTheDocument()
        expect(server.callsTo("GET", VIEW_PATH)).toHaveLength(0)
        expect(server.callsTo("GET", /entities\/i1\//)).toHaveLength(0)
    })

    it("returns from the edit page to the item page it was opened from", async () => {
        setup("/app/c1/world")
        fireEvent.click(await screen.findByRole("link", { name: "Open from World" }))
        await waitReady()
        fireEvent.click(stageLink(1))
        fireEvent.click(await screen.findByRole("link", { name: "Edit item" }))
        const crumbs = await screen.findByRole("navigation", { name: "Breadcrumb" }).catch(() => null)
        expect(crumbs).toBeNull()
        fireEvent.click(await screen.findByRole("button", { name: "Cancel" }))
        await waitReady()
        await waitFor(() => expect(where()).toBe("/app/c1/world/item/i1?section=details"))
        expect(screen.getByRole("link", { name: "Back to World" })).toHaveAttribute(
            "href",
            "/app/c1/world?category=item&cursor=abc",
        )
    })

    it("returns from the edit page to the inventory item page", async () => {
        setup("/app/c1/items/i1?section=details")
        fireEvent.click(await screen.findByRole("link", { name: "Edit item" }))
        expect(await screen.findByRole("heading", { level: 1, name: "Edit item" })).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        await waitReady()
        await waitFor(() => expect(where()).toBe("/app/c1/items/i1?section=details"))
    })

    it("ignores a return address that is not this item", async () => {
        const { router } = setup("/app/c1/items")
        await screen.findByRole("link", { name: "Moonblade" })
        void router.navigate("/app/c1/items/i1/edit", {
            state: { returnTo: { pathname: "/app/c1/world/item/other", search: "" } },
        })
        fireEvent.click(await screen.findByRole("button", { name: "Cancel" }))
        await waitReady()
        expect(where().startsWith("/app/c1/items/i1")).toBe(true)
    })
})

describe("stages and sections", () => {
    it.each([
        [{}, "move"],
        [{ canon_status: "draft", can_operate: false, available_actions: ["update", "submit_for_review"] }, "details"],
        [{ canon_status: "rejected", can_operate: false, available_actions: ["return_to_draft"] }, "details"],
        [{ canon_status: "proposed", can_operate: false, available_actions: ["approve"] }, "publication"],
        [{ canon_status: "approved", can_operate: false, available_actions: ["publish"] }, "publication"],
        [{ canon_status: "superseded", can_operate: false, available_actions: ["archive"] }, "publication"],
        [{ lifecycle_status: "archived", can_operate: false, available_actions: ["restore"] }, "publication"],
    ])("opens %j on %s without sending anything", async (overrides, section) => {
        const { server } = setup("/app/c1/items/i1", { current: view(overrides) })
        await waitReady()
        await waitFor(() => expect(where()).toBe(`/app/c1/items/i1?section=${section}`))
        expect(server.calls.filter((c) => c.method === "POST")).toHaveLength(0)
    })

    it("replaces an unknown section and keeps other query parameters", async () => {
        const { router } = setup("/app/c1/items/i1?section=nonsense&x=1")
        await waitReady()
        await waitFor(() => expect(where()).toBe("/app/c1/items/i1?section=move&x=1"))
        expect(router.state.historyAction).toBe("REPLACE")
    })

    it("navigates by links only: no request, one history entry per choice", async () => {
        const { server, router } = setup("/app/c1/items/i1")
        await waitReady()
        const before = server.calls.length
        fireEvent.click(stageLink(2))
        await waitFor(() => expect(where()).toContain("section=publication"))
        fireEvent.click(stageLink(3))
        await waitFor(() => expect(where()).toContain("section=move"))
        expect(server.calls.slice(before).filter((c) => c.method !== "GET")).toHaveLength(0)
        void router.navigate(-1)
        await waitFor(() => expect(where()).toContain("section=publication"), { timeout: 4000 })
        expect(stageLink(2)).toHaveAttribute("aria-current", "step")
    })

    it("moves focus to the section heading, not the page heading, when a section is chosen", async () => {
        setup("/app/c1/items/i1")
        await waitReady()
        await waitFor(() => expect(where()).toContain("section=move"))
        fireEvent.click(sectionLink("Use & condition"))
        await waitFor(() => expect(document.activeElement?.id).toBe("item-section-condition-heading"))
    })

    it("shows the real status in the header, apart from the stage navigation", async () => {
        setup("/app/c1/items/i1", { current: view({ canon_status: "proposed", can_operate: false, available_actions: ["approve"] }) })
        await waitReady()
        const status = screen.getByRole("group", { name: "Record status" })
        expect(within(status).getByText("In review")).toBeInTheDocument()
        expect(within(screen.getByRole("navigation", { name: "Item stages" })).queryByText(/review$/i)).toBeNull()
    })

    it("offers the next step as navigation to where it lives", async () => {
        setup("/app/c1/items/i1", { current: view({ holder: null, owner: null, last_event_id: null }) })
        await waitReady()
        expect(
            screen.getByRole("link", { name: "Give it to someone or place it ›" }).getAttribute("href"),
        ).toContain("section=move")
    })

    it("explains an unpublished item instead of showing use-in-play forms", async () => {
        setup("/app/c1/items/i1?section=move", {
            current: view({ canon_status: "draft", can_operate: false, available_actions: ["update", "submit_for_review"] }),
        })
        await waitReady()
        expect(await within(panel("move")).findByText(/Only a published item can be used in play/)).toBeInTheDocument()
        expect(within(panel("move")).queryByRole("radio")).not.toBeInTheDocument()
        expect(within(panel("move")).getByRole("link", { name: "Submit for review ›" })).toBeInTheDocument()
    })

    it("offers editing by status and explains when it is not offered", async () => {
        const { unmount } = setup("/app/c1/items/i1?section=details")
        await waitReady()
        expect(within(panel("details")).getByRole("link", { name: "Edit item" })).toBeInTheDocument()
        expect(within(panel("details")).getByText("Longsword (fixed once created)")).toBeInTheDocument()
        unmount()
        setup("/app/c1/items/i1?section=details", {
            current: view({
                canon_status: "proposed",
                can_operate: false,
                available_actions: ["approve"],
                blocked_actions: [{ action: "update", reason: "review_in_progress" }],
            }),
        })
        await waitReady()
        expect(within(panel("details")).queryByRole("link", { name: "Edit item" })).not.toBeInTheDocument()
        expect(within(panel("details")).getByText(/Editing unavailable/)).toBeInTheDocument()
    })

    it("keeps lifecycle actions in Publication with the server's blocked reasons", async () => {
        setup("/app/c1/items/i1?section=publication")
        await waitReady()
        await within(panel("publication")).findByRole("button", { name: "Archive" })
    })
})

describe("in play state", () => {
    it("shows one In play summary and no Current State or Run this item panel", async () => {
        setup("/app/c1/items/i1", { current: view({ condition_percentage: 60, quantity: 3 }) })
        await waitReady()
        expect(screen.getAllByRole("heading", { name: "In play" })).toHaveLength(1)
        const summary = screen.getByRole("heading", { name: "In play" }).closest("section")!
        expect(within(summary).getByText("Carried by Aldric")).toBeInTheDocument()
        expect(within(summary).getByText("60%")).toBeInTheDocument()
        expect(within(summary).getByText("3")).toBeInTheDocument()
        expect(screen.queryByRole("heading", { name: /Current State|Run this item/ })).not.toBeInTheDocument()
    })

    it("does not invent a condition or a quantity for an item nothing has happened to", async () => {
        setup("/app/c1/items/i1", { current: view({ holder: null, owner: null, last_event_id: null }) })
        await waitReady()
        const summary = screen.getByRole("heading", { name: "In play" }).closest("section")!
        expect(within(summary).getByText(/Not in play yet/)).toBeInTheDocument()
        expect(within(summary).queryByText("Quantity")).not.toBeInTheDocument()
        expect(within(summary).queryByText("Condition")).not.toBeInTheDocument()
        expect(screen.queryByText("Undamaged")).not.toBeInTheDocument()
    })

    it("shows custody that was recorded without an event, rather than claiming the item is not in play", async () => {
        setup("/app/c1/items/i1", { current: view({ last_event_id: null }) })
        await waitReady()
        const summary = screen.getByRole("heading", { name: "In play" }).closest("section")!
        expect(within(summary).queryByText(/Not in play yet/)).not.toBeInTheDocument()
        expect(within(summary).getByText("Carried by Aldric")).toBeInTheDocument()
    })

    it("keeps the recorded quantity of an item that was released to no place", async () => {
        setup("/app/c1/items/i1", { current: view({ holder: null, owner: null, last_event_id: "e5", quantity: 1 }) })
        await waitReady()
        const summary = screen.getByRole("heading", { name: "In play" }).closest("section")!
        expect(within(summary).queryByText(/Not in play yet/)).not.toBeInTheDocument()
        expect(within(summary).getByText("Quantity")).toBeInTheDocument()
        expect(within(summary).getByText("Not placed")).toBeInTheDocument()
        expect(within(summary).getByText("No damage recorded")).toBeInTheDocument()
    })

    it("says no damage is recorded rather than showing a default condition", async () => {
        setup("/app/c1/items/i1")
        await waitReady()
        const summary = screen.getByRole("heading", { name: "In play" }).closest("section")!
        expect(within(summary).getByText("No damage recorded")).toBeInTheDocument()
        expect(screen.queryByText("100%")).not.toBeInTheDocument()
    })

    it("reflects what the server holds after a command, without a reload", async () => {
        const { server, state } = setup("/app/c1/items/i1?section=condition")
        await waitReady()
        const form = await within(panel("condition")).findByRole("form", { name: "Change this item" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Amount/ }), { target: { value: "40" } })
        server.on("POST", OP("damage"), () => {
            state.current = view({ condition_percentage: 60, last_event_id: "e2" })
            return { body: state.current }
        })
        fireEvent.click(within(form).getByRole("button", { name: "Damage" }))
        const summary = screen.getByRole("heading", { name: "In play" }).closest("section")!
        await waitFor(() => expect(within(summary).getByText("60%")).toBeInTheDocument())
        expect(server.callsTo("POST", OP("damage"))[0]!.body).toEqual({ expected_last_event_id: "e1", amount: 40 })
    })

    it("lists a destroyed item as destroyed and offers nothing", async () => {
        setup("/app/c1/items/i1", { current: view({ is_destroyed: true }) })
        await waitReady()
        expect(within(screen.getByRole("group", { name: "Record status" })).getByText("Destroyed")).toBeInTheDocument()
        expect(await within(panel("move")).findByText(/This item is destroyed/)).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Equip" })).not.toBeInTheDocument()
    })
})

describe("give versus place", () => {
    async function chooseGive() {
        fireEvent.click(await screen.findByRole("radio", { name: "Give to a character" }))
        return screen.getByRole("form", { name: "Give this item to a character" })
    }
    async function pick(form: HTMLElement, name: string, option: RegExp) {
        fireEvent.focus(within(form).getByRole("combobox", { name }))
        fireEvent.click(await within(form).findByRole("option", { name: option }))
    }

    it("sends nothing and shows only the chosen action's inputs", async () => {
        const { server } = setup("/app/c1/items/i1")
        await waitReady()
        expect(screen.queryByRole("combobox", { name: "Give to" })).not.toBeInTheDocument()
        expect(screen.queryByRole("combobox", { name: "Place at" })).not.toBeInTheDocument()
        const before = server.calls.length
        fireEvent.click(await screen.findByRole("radio", { name: "Give to a character" }))
        expect(screen.getByRole("combobox", { name: "Give to" })).toBeInTheDocument()
        expect(screen.queryByRole("combobox", { name: "Place at" })).not.toBeInTheDocument()
        fireEvent.click(screen.getByRole("radio", { name: "Place at a location" }))
        expect(screen.getByRole("combobox", { name: "Place at" })).toBeInTheDocument()
        expect(screen.queryByRole("combobox", { name: "Give to" })).not.toBeInTheDocument()
        expect(server.calls.slice(before).filter((c) => c.method !== "GET")).toHaveLength(0)
    })

    it("gives a carried item and keeps the owner when asked to", async () => {
        const { server } = setup("/app/c1/items/i1")
        await waitReady()
        const form = await chooseGive()
        await pick(form, "Give to", /Brea/)
        expect(within(form).getByText("Aldric will no longer carry it.")).toBeInTheDocument()
        fireEvent.click(within(form).getByRole("radio", { name: "Keep the current owner (Aldric)" }))
        fireEvent.click(within(form).getByRole("button", { name: "Give item" }))
        await waitFor(() => expect(server.callsTo("POST", OP("transfer"))).toHaveLength(1))
        expect(server.callsTo("POST", OP("transfer"))[0]!.body).toEqual({
            expected_last_event_id: "e1",
            holder_entity_id: "n2",
            transfer_ownership: false,
        })
    })

    it("transfers ownership only when that is chosen", async () => {
        const { server } = setup("/app/c1/items/i1")
        await waitReady()
        const form = await chooseGive()
        await pick(form, "Give to", /Brea/)
        fireEvent.click(within(form).getByRole("radio", { name: "Make Brea the owner" }))
        fireEvent.click(within(form).getByRole("button", { name: "Give item" }))
        await waitFor(() => expect(server.callsTo("POST", OP("transfer"))).toHaveLength(1))
        expect(server.callsTo("POST", OP("transfer"))[0]!.body).toMatchObject({ transfer_ownership: true })
    })

    it("refuses a give with no ownership choice or no recipient, and sends nothing", async () => {
        const { server } = setup("/app/c1/items/i1")
        await waitReady()
        const form = await chooseGive()
        fireEvent.click(within(form).getByRole("button", { name: "Give item" }))
        expect(await screen.findByText(/Choose who receives it/)).toBeInTheDocument()
        await pick(form, "Give to", /Brea/)
        fireEvent.click(within(form).getByRole("button", { name: "Give item" }))
        expect(await screen.findByText(/Choose who owns it afterwards/)).toBeInTheDocument()
        expect(server.callsTo("POST", /\/items\/i1\//)).toHaveLength(0)
    })

    it("places a carried item without touching ownership and says what it leaves", async () => {
        const { server } = setup("/app/c1/items/i1")
        await waitReady()
        fireEvent.click(await screen.findByRole("radio", { name: "Place at a location" }))
        const form = screen.getByRole("form", { name: "Place this item at a location" })
        expect(within(form).getByText(/Aldric will no longer carry it\. The owner stays Aldric\./)).toBeInTheDocument()
        expect(within(form).queryByRole("radio")).not.toBeInTheDocument()
        await pick(form, "Place at", /Stonebridge/)
        fireEvent.click(within(form).getByRole("button", { name: "Place item" }))
        await waitFor(() => expect(server.callsTo("POST", OP("transfer"))).toHaveLength(1))
        expect(server.callsTo("POST", OP("transfer"))[0]!.body).toEqual({
            expected_last_event_id: "e1",
            location_id: "l1",
        })
    })

    it("awards an unplaced item with a quantity and an explicit owner choice", async () => {
        const { server } = setup("/app/c1/items/i1", { current: view({ holder: null, owner: null, last_event_id: null }) })
        await waitReady()
        const form = await chooseGive()
        await pick(form, "Give to", /Aldric/)
        fireEvent.change(within(form).getByRole("textbox", { name: "Quantity" }), { target: { value: "2" } })
        fireEvent.click(within(form).getByRole("radio", { name: "Make Aldric the owner" }))
        fireEvent.click(within(form).getByRole("button", { name: "Give item" }))
        await waitFor(() => expect(server.callsTo("POST", OP("award"))).toHaveLength(1))
        expect(server.callsTo("POST", OP("award"))[0]!.body).toEqual({
            expected_last_event_id: null,
            holder_entity_id: "n1",
            quantity: 2,
            set_owner: true,
        })
    })

    it("can place an unplaced item at a location", async () => {
        const { server } = setup("/app/c1/items/i1", { current: view({ holder: null, owner: null, last_event_id: null }) })
        await waitReady()
        fireEvent.click(await screen.findByRole("radio", { name: "Place at a location" }))
        const form = screen.getByRole("form", { name: "Place this item at a location" })
        await pick(form, "Place at", /Stonebridge/)
        fireEvent.click(within(form).getByRole("button", { name: "Place item" }))
        await waitFor(() => expect(server.callsTo("POST", OP("transfer"))).toHaveLength(1))
        expect(server.callsTo("POST", OP("transfer"))[0]!.body).toEqual({
            expected_last_event_id: null,
            location_id: "l1",
        })
    })

    it("blocks giving or placing an equipped item and points to the step that unlocks it", async () => {
        setup("/app/c1/items/i1", { current: view({ is_equipped: true }) })
        await waitReady()
        const move = panel("move")
        expect(await within(move).findByText(/has it equipped/)).toBeInTheDocument()
        expect(within(move).queryByRole("radio")).not.toBeInTheDocument()
        expect(within(move).getByRole("link", { name: /Unequip it first/ }).getAttribute("href")).toContain(
            "section=equipment",
        )
    })

    it("includes the chosen world time", async () => {
        const { server } = setup("/app/c1/items/i1?section=equipment")
        await waitReady()
        fireEvent.change(await screen.findByRole("combobox", { name: "When this happens (in-world)" }), {
            target: { value: "t1" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Equip" }))
        await waitFor(() => expect(server.callsTo("POST", OP("equip"))).toHaveLength(1))
        expect(server.callsTo("POST", OP("equip"))[0]!.body).toEqual({
            expected_last_event_id: "e1",
            world_time_id: "t1",
        })
    })

    it("keeps drafts across sections, stages and a refused command, and clears them once the command succeeds", async () => {
        const { server } = setup("/app/c1/items/i1")
        await waitReady()
        const form = await chooseGive()
        await pick(form, "Give to", /Brea/)
        fireEvent.click(within(form).getByRole("radio", { name: "Make Brea the owner" }))
        // Switch away and back: stages and sections only hide the panels.
        fireEvent.click(sectionLink("Use & condition"))
        fireEvent.click(stageLink(2))
        fireEvent.click(stageLink(3))
        fireEvent.click(sectionLink("Give or place"))
        expect(screen.getByRole("combobox", { name: "Give to" })).toHaveValue("Brea")
        expect(screen.getByRole("radio", { name: "Make Brea the owner" })).toBeChecked()
        // A refused command keeps everything and explains itself in the section.
        server.on("POST", OP("transfer"), {
            status: 409,
            body: { error: { code: "item_equipped", message: "m", correlation_id: "c" } },
        })
        fireEvent.click(screen.getByRole("button", { name: "Give item" }))
        expect(await screen.findByText("Unequip the item first.")).toBeInTheDocument()
        expect(screen.getByRole("combobox", { name: "Give to" })).toHaveValue("Brea")
        // A success clears what that command consumed.
        server.on("POST", OP("transfer"), { body: view({ last_event_id: "e2" }) })
        fireEvent.click(screen.getByRole("button", { name: "Give item" }))
        await waitFor(() => expect(screen.queryByRole("combobox", { name: "Give to" })).toHaveValue(""))
    })

    it("keeps typed input when the item is reloaded after a stale write", async () => {
        const { server } = setup("/app/c1/items/i1?section=condition")
        await waitReady()
        const form = await within(panel("condition")).findByRole("form", { name: "Change this item" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Amount/ }), { target: { value: "15" } })
        server.on("POST", OP("repair"), {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        fireEvent.click(within(form).getByRole("button", { name: "Repair" }))
        fireEvent.click(await screen.findByRole("button", { name: /Load latest/i }))
        expect(within(form).getByRole("textbox", { name: /Amount/ })).toHaveValue("15")
    })

    it("asks before destroying and refuses while attuned", async () => {
        const { server } = setup("/app/c1/items/i1?section=condition")
        await waitReady()
        fireEvent.click(await screen.findByRole("button", { name: "Destroy item" }))
        const dialog = await screen.findByRole("dialog", { name: "Destroy this item?" })
        expect(server.callsTo("POST", OP("destroy"))).toHaveLength(0)
        fireEvent.click(within(dialog).getByRole("button", { name: "Destroy item" }))
        await waitFor(() => expect(server.callsTo("POST", OP("destroy"))).toHaveLength(1))
    })

    it("attunes to the carrier and offers to end an attunement", async () => {
        const { server, unmount } = setup("/app/c1/items/i1?section=equipment", {
            current: view({ requires_attunement: true }),
        })
        await waitReady()
        fireEvent.click(await screen.findByRole("button", { name: "Attune to Aldric" }))
        await waitFor(() => expect(server.callsTo("POST", OP("attune"))).toHaveLength(1))
        expect(server.callsTo("POST", OP("attune"))[0]!.body).toEqual({
            expected_last_event_id: "e1",
            character_id: "n1",
        })
        unmount()
        setup("/app/c1/items/i1?section=equipment", {
            current: view({ requires_attunement: true, attuned_to: ALDRIC }),
        })
        expect(await screen.findByRole("button", { name: "End attunement" })).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Destroy item", hidden: true })).toBeDisabled()
    })

    it("lists nobody as carrier when only a place holds it", async () => {
        setup("/app/c1/items/i1", { current: view({ holder: null, location: STONEBRIDGE }) })
        await waitReady()
        const summary = screen.getByRole("heading", { name: "In play" }).closest("section")!
        expect(within(summary).getByText("Lying at Stonebridge")).toBeInTheDocument()
    })

    describe("time and retry", () => {
        const TIME_LABEL = "When this happens (in-world)"
        const picker = () => screen.findByRole("combobox", { name: TIME_LABEL })
        const timeValue = () => screen.getByRole("combobox", { name: TIME_LABEL })

        it("uses a chosen time once, then defaults to the campaign clock", async () => {
            const { server, state } = setup("/app/c1/items/i1?section=equipment")
            await waitReady()
            fireEvent.change(await picker(), { target: { value: "t1" } })
            server.on("POST", OP("equip"), () => {
                state.current = view({ is_equipped: true, last_event_id: "e2" })
                return { body: state.current }
            })
            server.on("POST", OP("unequip"), () => ({ body: view({ last_event_id: "e3" }) }))
            fireEvent.click(screen.getByRole("button", { name: "Equip" }))
            await waitFor(() => expect(server.callsTo("POST", OP("equip"))).toHaveLength(1))
            await screen.findByRole("button", { name: "Unequip" })
            await waitFor(() => expect(timeValue()).toHaveValue(""))
            fireEvent.click(screen.getByRole("button", { name: "Unequip" }))
            await waitFor(() => expect(server.callsTo("POST", OP("unequip"))).toHaveLength(1))
            expect(server.callsTo("POST", OP("equip"))[0]!.body).toEqual({
                expected_last_event_id: "e1",
                world_time_id: "t1",
            })
            expect(server.callsTo("POST", OP("unequip"))[0]!.body).toEqual({ expected_last_event_id: "e2" })
        })

        it.each(["give", "place", "condition"])("consumes the time after a successful %s", async (name) => {
            const { server } = setup(`/app/c1/items/i1?section=${name === "condition" ? "condition" : "move"}`)
            await waitReady()
            fireEvent.change(await picker(), { target: { value: "t1" } })
            if (name === "condition") {
                const form = await within(panel("condition")).findByRole("form", { name: "Change this item" })
                fireEvent.change(within(form).getByRole("textbox", { name: /Amount/ }), { target: { value: "5" } })
                fireEvent.click(within(form).getByRole("button", { name: "Damage" }))
                await waitFor(() => expect(server.callsTo("POST", OP("damage"))).toHaveLength(1))
            } else if (name === "give") {
                fireEvent.click(await screen.findByRole("radio", { name: "Give to a character" }))
                const form = screen.getByRole("form", { name: "Give this item to a character" })
                fireEvent.focus(within(form).getByRole("combobox", { name: "Give to" }))
                fireEvent.click(await within(form).findByRole("option", { name: /Brea/ }))
                fireEvent.click(within(form).getByRole("radio", { name: "Keep the current owner (Aldric)" }))
                fireEvent.click(within(form).getByRole("button", { name: "Give item" }))
                await waitFor(() => expect(server.callsTo("POST", OP("transfer"))).toHaveLength(1))
            } else {
                fireEvent.click(await screen.findByRole("radio", { name: "Place at a location" }))
                const form = screen.getByRole("form", { name: "Place this item at a location" })
                fireEvent.focus(within(form).getByRole("combobox", { name: "Place at" }))
                fireEvent.click(await within(form).findByRole("option", { name: /Stonebridge/ }))
                fireEvent.click(within(form).getByRole("button", { name: "Place item" }))
                await waitFor(() => expect(server.callsTo("POST", OP("transfer"))).toHaveLength(1))
            }
            expect(server.callsTo("POST", /\/items\/i1\//)[0]!.body).toMatchObject({ world_time_id: "t1" })
            await waitFor(() => expect(timeValue()).toHaveValue(""))
        })

        it("keeps the chosen time after a refused or stale command", async () => {
            const { server } = setup("/app/c1/items/i1?section=equipment")
            await waitReady()
            fireEvent.change(await picker(), { target: { value: "t1" } })
            server.on("POST", OP("equip"), {
                status: 409,
                body: { error: { code: "item_attuned", message: "m", correlation_id: "c" } },
            })
            fireEvent.click(screen.getByRole("button", { name: "Equip" }))
            await screen.findByText("End the attunement first.")
            expect(timeValue()).toHaveValue("t1")
            server.on("POST", OP("equip"), {
                status: 409,
                body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
            })
            fireEvent.click(screen.getByRole("button", { name: "Equip" }))
            await screen.findByRole("button", { name: /Load latest/i })
            expect(timeValue()).toHaveValue("t1")
        })

        const UNAVAILABLE = {
            status: 503,
            body: { error: { code: "unavailable", message: "m", correlation_id: "c" } },
        }

        it("retries the original request with its key, whatever the picker says now", async () => {
            const { server } = setup("/app/c1/items/i1?section=condition")
            await waitReady()
            const form = await within(panel("condition")).findByRole("form", { name: "Change this item" })
            fireEvent.change(within(form).getByRole("textbox", { name: /Amount/ }), { target: { value: "15" } })
            server.on("POST", OP("repair"), UNAVAILABLE)
            fireEvent.click(within(form).getByRole("button", { name: "Repair" }))
            const retry = await screen.findByRole("button", { name: /Retry|Try again/i })
            fireEvent.change(await picker(), { target: { value: "t1" } })
            server.on("POST", OP("repair"), { body: view({ last_event_id: "e2" }) })
            fireEvent.click(retry)
            await waitFor(() => expect(server.callsTo("POST", OP("repair"))).toHaveLength(2))
            const [first, second] = server.callsTo("POST", OP("repair"))
            expect(second!.body).toEqual(first!.body)
            expect(first!.body).toEqual({ expected_last_event_id: "e1", amount: 15 })
            expect(second!.headers["Idempotency-Key"]).toBe(first!.headers["Idempotency-Key"])
        })

        it("gives a deliberate new submission with different data a new key", async () => {
            const { server } = setup("/app/c1/items/i1?section=condition")
            await waitReady()
            const form = await within(panel("condition")).findByRole("form", { name: "Change this item" })
            server.on("POST", OP("repair"), UNAVAILABLE)
            fireEvent.change(within(form).getByRole("textbox", { name: /Amount/ }), { target: { value: "15" } })
            fireEvent.click(within(form).getByRole("button", { name: "Repair" }))
            await screen.findByRole("button", { name: /Retry|Try again/i })
            fireEvent.change(await picker(), { target: { value: "t1" } })
            fireEvent.click(within(form).getByRole("button", { name: "Repair" }))
            await waitFor(() => expect(server.callsTo("POST", OP("repair"))).toHaveLength(2))
            const [first, second] = server.callsTo("POST", OP("repair"))
            expect(second!.body).toEqual({ expected_last_event_id: "e1", world_time_id: "t1", amount: 15 })
            expect(second!.headers["Idempotency-Key"]).not.toBe(first!.headers["Idempotency-Key"])
        })
    })

    describe("a failed refresh", () => {
        const failGet = (server: ReturnType<typeof setup>["server"], status: number) =>
            server.on("GET", VIEW_PATH, {
                status,
                body: { error: { code: status === 404 ? "not_found" : "unavailable", message: "m", correlation_id: "c" } },
            })

        it("keeps unrelated drafts through a successful command, a failed read and a retry", async () => {
            const { server, state } = setup("/app/c1/items/i1?section=condition")
            await waitReady()
            const form = await within(panel("condition")).findByRole("form", { name: "Change this item" })
            fireEvent.change(within(form).getByRole("textbox", { name: /Amount/ }), { target: { value: "17" } })
            fireEvent.click(sectionLink("Give or place"))
            fireEvent.click(await screen.findByRole("radio", { name: "Place at a location" }))
            const place = screen.getByRole("form", { name: "Place this item at a location" })
            fireEvent.focus(within(place).getByRole("combobox", { name: "Place at" }))
            fireEvent.click(await within(place).findByRole("option", { name: /Stonebridge/ }))
            fireEvent.click(sectionLink("Equip & attune"))
            server.on("POST", OP("equip"), () => {
                failGet(server, 503)
                return { body: view({ last_event_id: "e2" }) }
            })
            fireEvent.click(await screen.findByRole("button", { name: "Equip" }))
            expect(await screen.findByText(/may be out of date/)).toBeInTheDocument()
            // The command was confirmed: the re-read is behind, the command is not done, and the
            // write was sent once and is not repeated by the retry of the read.
            const live = screen.getByTestId("authoring-announcer")
            expect(live).toHaveTextContent("Saved, but the latest data could not be loaded.")
            expect(server.calls.filter((c) => c.method === "POST" && c.path.endsWith("/equip"))).toHaveLength(1)
            expect(within(form).getByRole("textbox", { name: /Amount/, hidden: true })).toHaveValue("17")
            expect(screen.getByRole("combobox", { name: "Place at", hidden: true })).toHaveValue("Stonebridge")
            server.on("GET", VIEW_PATH, () => ({ body: state.current }))
            fireEvent.click(screen.getByRole("button", { name: "Try again" }))
            await waitFor(() => expect(screen.queryByText(/may be out of date/)).not.toBeInTheDocument())
            expect(server.calls.filter((c) => c.method === "POST" && c.path.endsWith("/equip"))).toHaveLength(1)
            expect(within(form).getByRole("textbox", { name: /Amount/, hidden: true })).toHaveValue("17")
            expect(screen.getByRole("combobox", { name: "Place at", hidden: true })).toHaveValue("Stonebridge")
        })

        it("keeps a Give draft through a failed read", async () => {
            const { server } = setup("/app/c1/items/i1?section=move")
            await waitReady()
            fireEvent.click(await screen.findByRole("radio", { name: "Give to a character" }))
            const give = screen.getByRole("form", { name: "Give this item to a character" })
            fireEvent.focus(within(give).getByRole("combobox", { name: "Give to" }))
            fireEvent.click(await within(give).findByRole("option", { name: /Brea/ }))
            fireEvent.click(sectionLink("Equip & attune"))
            server.on("POST", OP("equip"), () => {
                failGet(server, 503)
                return { body: view({ last_event_id: "e2" }) }
            })
            fireEvent.click(await screen.findByRole("button", { name: "Equip" }))
            await screen.findByText(/may be out of date/)
            fireEvent.click(sectionLink("Give or place"))
            expect(screen.getByRole("combobox", { name: "Give to" })).toHaveValue("Brea")
        })

        it("fails closed when the record becomes unavailable, discarding the cached item", async () => {
            const { server } = setup("/app/c1/items/i1?section=equipment")
            await waitReady()
            server.on("POST", OP("equip"), () => {
                failGet(server, 404)
                return { body: view({ last_event_id: "e2" }) }
            })
            fireEvent.click(await screen.findByRole("button", { name: "Equip" }))
            expect(await screen.findByRole("heading", { name: "Item unavailable" })).toBeInTheDocument()
            expect(screen.queryByRole("link", { name: /Prepare/ })).not.toBeInTheDocument()
            expect(screen.queryByText("Moonblade")).not.toBeInTheDocument()
        })

        it("does not carry drafts to another item", async () => {
            const { router, server } = setup("/app/c1/items/i1?section=condition")
            server.on("GET", "/campaigns/c1/authoring/items/i2", {
                status: 404,
                body: { error: { code: "not_found", message: "m", correlation_id: "c" } },
            })
            server.on("GET", "/campaigns/c1/entities/i2/lifecycle", { status: 404 })
            server.on("GET", "/campaigns/c1/entities/i2/provenance", { status: 404 })
            await waitReady()
            const form = await within(panel("condition")).findByRole("form", { name: "Change this item" })
            fireEvent.change(within(form).getByRole("textbox", { name: /Amount/ }), { target: { value: "9" } })
            void router.navigate("/app/c1/items/i2?section=condition")
            // Leaving with unsent input asks first; discarding opens the other item with no draft.
            fireEvent.click(await screen.findByRole("button", { name: "Discard" }))
            await screen.findByRole("heading", { name: "Item unavailable" })
            expect(screen.queryByDisplayValue("9")).not.toBeInTheDocument()
        })
    })
})

describe("sources of an item instance (D-8)", () => {
    it("tells a campaign GM with no world role that sources are the world's preparation, and requests none", async () => {
        const { server } = setup("/app/c1/items/i1", { worldCapabilities: [] })
        await waitReady()
        expect(await within(panel("sources")).findByText(/need a world Editor or Reviewer role/)).toBeInTheDocument()
        expect(server.calls.map((c) => c.path).filter((p) => /\/sources$|\/provenance$/.test(p))).toEqual([])
        // Everything the campaign owns about the item still works.
        expect(panel("details")).toBeInTheDocument()
    })

    it("reads the catalog and provenance for a world Editor or Reviewer", async () => {
        const { server } = setup("/app/c1/items/i1", {
            worldCapabilities: ["world.view", "world.canon.read", "world.canon.read_private"],
        })
        await waitReady()
        await waitFor(() => expect(server.calls.some((c) => c.path.endsWith("/campaigns/c1/sources"))).toBe(true))
        expect(server.calls.some((c) => c.path.endsWith("/entities/i1/provenance"))).toBe(true)
        expect(within(panel("sources")).queryByText(/need a world Editor or Reviewer role/)).toBeNull()
    })
})
