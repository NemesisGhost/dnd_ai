import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { useSessionBootstrap } from "./hooks/useSessionBootstrap"
import { bootstrapFor, installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockResponse, MockServer } from "./test/authoringHarness"

// P02-7c: Items and Item definitions. The item inventory and the definitions catalog are two different
// lists of the Items root. They flow through the list, the item workspace, the edit and create pages and
// the definition form, carried by the shared breadcrumb, the validated task, the older itemsSearch /
// definitionsSearch keys and the label registry. These run the whole App over a memory data router (jsdom):
// they prove destinations, requests, history and rendered authorized content, not real-browser keyboard,
// focus, zoom or screen-reader behavior.

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
    recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const base = "/app/mundivita"
const API = "/campaigns/mundivita"
const AUTH = `${API}/authoring`
const NOT_FOUND: MockResponse = {
    status: 404,
    body: { error: { code: "not_found", message: "m", correlation_id: "c" } },
}

const ALDRIC = { entity_id: "n1", name: "Aldric", entity_type_code: "player_character" }
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

function itemView(overrides: object = {}) {
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

const ITEM_OPTIONS = {
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
const ITEM_LIST = {
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
}
const LIFECYCLE = {
    entity_id: "i1",
    entity_type_code: "item_instance",
    canonical_name: "Moonblade",
    canon_status: "canon",
    lifecycle_status: "active",
    row_version: 3,
    lifecycle_managed: true,
    superseded_by: null,
    available_actions: ["supersede", "archive"],
    blocked_actions: [],
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

const DEF_OPTIONS = {
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
        name: "Moonblade pattern",
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

let server: MockServer
let itemResponse: MockResponse
let itemGate: () => MockResponse | Promise<MockResponse>
let definitionResponse: MockResponse

beforeEach(() => {
    server = installCampaignShellMocks()
    itemResponse = { body: itemView() }
    itemGate = () => itemResponse
    definitionResponse = { body: definition() }
    server.on("GET", `${AUTH}/items`, { body: ITEM_LIST })
    server.on("GET", `${AUTH}/items/options`, { body: ITEM_OPTIONS })
    server.on("GET", `${AUTH}/items/i1`, () => itemGate())
    server.on("GET", `${API}/entities/i1/lifecycle`, { body: LIFECYCLE })
    server.on("GET", `${API}/entities/i1/provenance`, { body: PROVENANCE })
    server.on("GET", `${API}/sources`, {
        body: { items: [], source_types: [], limits: { title_max_length: 200, reference_max_length: 500 } },
    })
    server.on("GET", /world-times/, { body: { items: [TIME], next_cursor: null } })
    server.on("GET", /calendars/, { body: { calendars: [] } })
    server.on("POST", `${AUTH}/items`, { status: 201, body: itemView({ canon_status: "draft", available_actions: ["update"] }) })
    server.on("POST", `${AUTH}/items/i1/update`, () => ({ body: itemView({ name: "Moonblade II" }) }))

    server.on("GET", `${AUTH}/item-definitions/options`, { body: DEF_OPTIONS })
    server.on("GET", `${AUTH}/item-definitions`, { body: { items: [GENERIC, definition()] } })
    server.on("GET", `${AUTH}/item-definitions/d1`, () => definitionResponse)
    server.on("POST", `${AUTH}/item-definitions`, { status: 201, body: definition({ item_definition_id: "d2" }) })
})

afterEach(() => {
    vi.unstubAllGlobals()
})

type Opened = ReturnType<typeof openApp>
type EntryState = {
    task?: { root: string; scope: unknown; trail: Array<{ route: string }>; list?: { route: string; search: string } }
    itemsSearch?: string
    definitionsSearch?: string
    announce?: string
}
const entryState = (app: Pick<Opened, "router">) => app.router.state.location.state as EntryState | null
const breadcrumb = () => within(screen.getByRole("navigation", { name: "Breadcrumb" }))
const trail = () => breadcrumb().getAllByRole("listitem").map((item) => item.textContent)
const trailLinks = () => breadcrumb().getAllByRole("link").map((link) => link.getAttribute("href"))
const notGet = () => server.calls.filter((call) => call.method !== "GET")
const authoringReads = () => server.calls.filter((call) => call.path.includes("/authoring/"))
const itemHeading = () => screen.findByRole("heading", { level: 1, name: "Moonblade" })
const stageLink = (n: number) => screen.getByRole("link", { name: new RegExp(`^${n}\\.`) })
const task = (root: string, trailRoutes: object[] = []) => ({
    v: 1,
    root,
    scope: { campaignId: "mundivita" },
    trail: trailRoutes,
})

describe("Items: inventory, item workspace, edit and create", () => {
    it("an item opened from the inventory keeps the Items task, with no name in the entry state", async () => {
        const app = openApp(`${base}/items`)
        fireEvent.click(await screen.findByRole("link", { name: "Moonblade" }))
        await itemHeading()
        expect(entryState(app)?.task).toMatchObject({ root: "items", scope: { campaignId: "mundivita" } })
        expect(entryState(app)?.task?.trail.map((entry) => entry.route)).toEqual(["items.list"])
        expect(entryState(app)?.itemsSearch).toBe("")
        expect(JSON.stringify(entryState(app))).not.toContain("Moonblade")
        expect(trail()).toEqual(["Items", "Moonblade"])
        expect(trailLinks()).toEqual([`${base}/items`])
        expect(breadcrumb().getByText("Moonblade")).toHaveAttribute("aria-current", "page")
        expect(screen.queryByRole("link", { name: "Back to World" })).toBeNull()
        fireEvent.click(breadcrumb().getByRole("link", { name: "Items" }))
        await screen.findByRole("heading", { level: 1, name: "Item inventory" })
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
    })

    it("the section the workspace fills in and the stage links keep the task", async () => {
        const app = openApp(`${base}/items`)
        fireEvent.click(await screen.findByRole("link", { name: "Moonblade" }))
        await itemHeading()
        await waitFor(() => expect(app.router.state.location.search).toBe("?section=move"))
        expect(entryState(app)?.task).toMatchObject({ root: "items" })
        const key = app.router.state.location.key
        fireEvent.click(stageLink(1))
        await waitFor(() => expect(app.router.state.location.search).toBe("?section=details"))
        expect(app.router.state.location.key).not.toBe(key)
        expect(entryState(app)?.task?.trail.map((entry) => entry.route)).toEqual(["items.list"])
        expect(trail()).toEqual(["Items", "Moonblade"])
        // Back walks the sections and the task is still the entry's own.
        await act(async () => {
            await app.router.navigate(-1)
        })
        await waitFor(() => expect(app.router.state.location.search).toBe("?section=move"))
        expect(entryState(app)?.task).toMatchObject({ root: "items" })
    })

    it("Edit item continues the task, and the edit page's crumbs and Cancel come back to the item inside it", async () => {
        const app = openApp(`${base}/items`)
        fireEvent.click(await screen.findByRole("link", { name: "Moonblade" }))
        await itemHeading()
        fireEvent.click(stageLink(1))
        fireEvent.click(await screen.findByRole("link", { name: "Edit item" }))
        await screen.findByRole("heading", { level: 1, name: "Edit item" })
        expect(entryState(app)?.task?.trail.map((entry) => entry.route)).toEqual(["items.list", "items.detail"])
        await waitFor(() => expect(trail()).toEqual(["Items", "Moonblade", "Edit"]))
        expect(trailLinks()).toEqual([`${base}/items`, `${base}/items/i1`])
        expect(breadcrumb().getByText("Edit")).toHaveAttribute("aria-current", "page")
        expect(screen.queryByRole("link", { name: "Item inventory" })).toBeNull()
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        await itemHeading()
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/items/i1`))
        expect(app.router.state.location.search).toBe("?section=details")
        expect(entryState(app)?.task).toMatchObject({ root: "items" })
        expect(trail()).toEqual(["Items", "Moonblade"])
    })

    it("saving an edit goes back to the item with the task and announces once; the write is sent once", async () => {
        const app = openApp(`${base}/items`)
        fireEvent.click(await screen.findByRole("link", { name: "Moonblade" }))
        await itemHeading()
        fireEvent.click(stageLink(1))
        fireEvent.click(await screen.findByRole("link", { name: "Edit item" }))
        const name = await screen.findByLabelText(/^Name/)
        fireEvent.change(name, { target: { value: "Moonblade II" } })
        fireEvent.click(screen.getByRole("button", { name: /^Save/ }))
        const confirm = screen.queryByRole("dialog")
        if (confirm !== null) fireEvent.click(within(confirm).getByRole("button", { name: "Save changes" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/items/i1`))
        expect(notGet().filter((call) => call.method === "POST")).toHaveLength(1)
        expect(entryState(app)?.task).toMatchObject({ root: "items" })
        expect(entryState(app)?.announce).toBe("Item saved")
        await waitFor(() => expect(trail()).toHaveLength(2))
        expect(trail()[0]).toBe("Items")
    })

    it("a dirty edit page asks on a breadcrumb ancestor: Stay keeps the draft and the task, Leave goes without a write", async () => {
        const app = openApp(`${base}/items`)
        fireEvent.click(await screen.findByRole("link", { name: "Moonblade" }))
        await itemHeading()
        fireEvent.click(stageLink(1))
        fireEvent.click(await screen.findByRole("link", { name: "Edit item" }))
        fireEvent.change(await screen.findByLabelText(/^Name/), { target: { value: "Draft name" } })
        const key = app.router.state.location.key
        fireEvent.click(breadcrumb().getByRole("link", { name: "Items" }))
        const dialog = await screen.findByRole("dialog", { name: "Discard unsaved changes?" })
        expect(app.router.state.location.key).toBe(key)
        fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
        await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
        expect(screen.getByLabelText(/^Name/)).toHaveValue("Draft name")
        expect(entryState(app)?.task).toMatchObject({ root: "items" })
        fireEvent.click(breadcrumb().getByRole("link", { name: "Items" }))
        fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Discard changes" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/items`))
        expect(notGet()).toEqual([])
    })

    it("a dirty item workspace asks on the Items ancestor: Stay keeps the draft, the task and the entry", async () => {
        const app = openApp(`${base}/items`)
        fireEvent.click(await screen.findByRole("link", { name: "Moonblade" }))
        await itemHeading()
        await waitFor(() => expect(app.router.state.location.search).toBe("?section=move"))
        fireEvent.click(screen.getByRole("link", { name: "Use & condition" }))
        const form = await screen.findByRole("form", { name: "Change this item" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Amount/ }), { target: { value: "9" } })
        const key = app.router.state.location.key
        fireEvent.click(breadcrumb().getByRole("link", { name: "Items" }))
        const dialog = await screen.findByRole("dialog", { name: "Discard unsaved input?" })
        expect(app.router.state.location.key).toBe(key)
        fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
        await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
        expect(within(screen.getByRole("form", { name: "Change this item" })).getByRole("textbox", { name: /Amount/ })).toHaveValue("9")
        expect(entryState(app)?.task).toMatchObject({ root: "items" })
        fireEvent.click(breadcrumb().getByRole("link", { name: "Items" }))
        fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Discard" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/items`))
        expect(notGet()).toEqual([])
    })

    it("New item continues the task; a created item replaces the form inside it, and Back skips the form", async () => {
        const app = openApp(`${base}/items`)
        fireEvent.click(await screen.findByRole("link", { name: "New item" }))
        await screen.findByRole("heading", { level: 1, name: "New item" })
        expect(trail()).toEqual(["Items", "New item"])
        expect(trailLinks()).toEqual([`${base}/items`])
        fireEvent.change(await screen.findByLabelText(/^Name/), { target: { value: "Moonblade" } })
        fireEvent.change(screen.getByLabelText(/^Kind of item/), { target: { value: "d1" } })
        fireEvent.click(screen.getByRole("button", { name: "Create item" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/items/i1`))
        expect(app.router.state.historyAction).toBe("REPLACE")
        expect(entryState(app)?.task).toMatchObject({ root: "items" })
        expect(entryState(app)?.task?.trail.map((entry) => entry.route)).toEqual(["items.list"])
        expect(notGet().filter((call) => call.method === "POST")).toHaveLength(1)
        await act(async () => {
            await app.router.navigate(-1)
        })
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/items`))
    })

    it("a dirty New item form asks first: Stay keeps the draft and the task, Leave goes without a write", async () => {
        const app = openApp(`${base}/items`)
        fireEvent.click(await screen.findByRole("link", { name: "New item" }))
        fireEvent.change(await screen.findByLabelText(/^Name/), { target: { value: "Draft" } })
        const key = app.router.state.location.key
        fireEvent.click(breadcrumb().getByRole("link", { name: "Items" }))
        const dialog = await screen.findByRole("dialog")
        expect(app.router.state.location.key).toBe(key)
        fireEvent.click(within(dialog).getByRole("button", { name: /Keep editing/ }))
        await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
        expect(screen.getByLabelText(/^Name/)).toHaveValue("Draft")
        expect(entryState(app)?.task).toMatchObject({ root: "items" })
        fireEvent.click(breadcrumb().getByRole("link", { name: "Items" }))
        fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: /Discard/ }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/items`))
        expect(notGet()).toEqual([])
    })

    it("a direct entry shows the route's defaults and the pages keep the links they always had", async () => {
        const app = openApp(`${base}/items/i1`)
        await itemHeading()
        expect(entryState(app)?.task).toBeUndefined()
        expect(trail()).toEqual(["Items", "Moonblade"])
        expect(trailLinks()).toEqual([`${base}/items`])
        fireEvent.click(stageLink(1))
        fireEvent.click(await screen.findByRole("link", { name: "Edit item" }))
        await screen.findByRole("heading", { level: 1, name: "Edit item" })
        // No evidence of an origin: the edit page keeps its single back link, and the link carried nothing.
        expect(entryState(app)?.task).toBeUndefined()
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
        expect(screen.getByRole("link", { name: "Item inventory" })).toHaveAttribute("href", `${base}/items`)
    })

    it("state that fails validation falls back to the defaults; a valid task of another root shows that root", async () => {
        const app = openApp(`${base}/items`)
        await screen.findByRole("link", { name: "Moonblade" })
        const open = async (state: unknown) => {
            await act(async () => {
                await app.router.navigate(`${base}/items/i1?section=details`, { state })
            })
            await itemHeading()
        }
        // Another campaign, an unknown shape, a root this page does not allow: the defaults.
        await open({ task: { ...task("items"), scope: { campaignId: "elsewhere" } } })
        expect(trail()).toEqual(["Items", "Moonblade"])
        await open({ task: { v: 1, root: "nonsense" } })
        expect(trail()).toEqual(["Items", "Moonblade"])
        await open({ task: task("parties") })
        expect(trail()).toEqual(["Items", "Moonblade"])
        await open({ task: task("items", [{ route: "itemDefinitions.nowhere", params: { campaignId: "mundivita" } }]) })
        expect(trail()).toEqual(["Items", "Moonblade"])
        // A task another root started (Characters): its root is the first crumb, and nothing else is invented.
        await open({ task: task("characters") })
        expect(trail()).toEqual(["Characters", "Moonblade"])
        expect(trailLinks()).toEqual([`${base}/characters/all`])
        // Whatever it showed, viewing the item selected nothing.
        expect(vi.mocked(useSessionBootstrap)).toHaveBeenCalled()
        expect(notGet()).toEqual([])
    })

    it("a legacy itemsSearch key the inventory does not produce is no task, but its query still reaches the edit page's back link", async () => {
        const app = openApp(`${base}/items`)
        await screen.findByRole("link", { name: "Moonblade" })
        await act(async () => {
            await app.router.navigate(`${base}/items/i1?section=details`, { state: { itemsSearch: "?x=1" } })
        })
        await itemHeading()
        expect(trail()).toEqual(["Items", "Moonblade"])
        expect(trailLinks()).toEqual([`${base}/items`])
        fireEvent.click(await screen.findByRole("link", { name: "Edit item" }))
        await screen.findByRole("heading", { level: 1, name: "Edit item" })
        expect(entryState(app)?.itemsSearch).toBe("?x=1")
        expect(entryState(app)?.task).toBeUndefined()
        expect(screen.getByRole("link", { name: "Item inventory" })).toHaveAttribute("href", `${base}/items?x=1`)
    })

    it("an item opened from the World page inside World's task shows its breadcrumb; edit, which World's task cannot reach, keeps its own links", async () => {
        const app = openApp(`${base}/world`)
        await act(async () => {
            await app.router.navigate(`${base}/world/item/i1?section=details`, {
                state: { worldSearch: "?category=item&cursor=abc" },
            })
        })
        await itemHeading()
        // The legacy `worldSearch` entry is adapted to World's task (docs/UI_DESIGN.md §4.8.9).
        expect(trail()).toEqual(["World", "Moonblade"])
        expect(trailLinks()).toEqual([`${base}/world?category=item&cursor=abc`])
        expect(screen.queryByRole("link", { name: "Back to World" })).toBeNull()
        fireEvent.click(await screen.findByRole("link", { name: "Edit item" }))
        await screen.findByRole("heading", { level: 1, name: "Edit item" })
        // The item edit route allows no World task, so its single back link stays.
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
    })

    it("keeps item instances and definitions apart: the Items list's definitions link starts a task of its own", async () => {
        const app = openApp(`${base}/items`)
        fireEvent.click(await screen.findByRole("link", { name: "Item definitions" }))
        await screen.findByRole("heading", { level: 1, name: "Item definitions" })
        expect(app.router.state.location.pathname).toBe(`${base}/item-definitions`)
        expect(entryState(app)?.task).toBeUndefined()
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
        fireEvent.click(await screen.findByRole("link", { name: "Edit Moonblade pattern" }))
        await screen.findByRole("heading", { level: 1, name: "Edit item definition" })
        expect(trail()).toEqual(["Items", "Item definitions", "Moonblade pattern"])
        expect(trailLinks()).toEqual([`${base}/items`, `${base}/item-definitions`])
    })
})

describe("Item definitions: catalog, form and create", () => {
    it("a definition opened from a filtered catalog keeps the task and the filters, and the crumb restores them", async () => {
        const app = openApp(`${base}/item-definitions?homebrew=1&category=weapon`)
        fireEvent.click(await screen.findByRole("link", { name: "Edit Moonblade pattern" }))
        await screen.findByRole("heading", { level: 1, name: "Edit item definition" })
        expect(entryState(app)?.task).toMatchObject({
            root: "items",
            list: { route: "itemDefinitions.list", search: "?homebrew=1&category=weapon" },
        })
        expect(entryState(app)?.definitionsSearch).toBe("?homebrew=1&category=weapon")
        expect(JSON.stringify(entryState(app))).not.toContain("Moonblade")
        expect(trail()).toEqual(["Items", "Item definitions", "Moonblade pattern"])
        expect(trailLinks()).toEqual([`${base}/items`, `${base}/item-definitions?homebrew=1&category=weapon`])
        expect(breadcrumb().getByText("Moonblade pattern")).toHaveAttribute("aria-current", "page")
        fireEvent.click(breadcrumb().getByRole("link", { name: "Item definitions" }))
        await screen.findByRole("heading", { level: 1, name: "Item definitions" })
        expect(screen.getByRole("checkbox", { name: /only this world/ })).toBeChecked()
        expect(screen.getByRole("combobox", { name: "Category" })).toHaveValue("weapon")
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
    })

    it("the Items crumb opens the inventory, not the catalog", async () => {
        const app = openApp(`${base}/item-definitions?homebrew=1`)
        fireEvent.click(await screen.findByRole("link", { name: "Edit Moonblade pattern" }))
        await screen.findByRole("heading", { level: 1, name: "Edit item definition" })
        fireEvent.click(breadcrumb().getByRole("link", { name: "Items" }))
        await screen.findByRole("heading", { level: 1, name: "Item inventory" })
        expect(app.router.state.location.pathname).toBe(`${base}/items`)
    })

    it("New item definition continues the task; its crumb and the create destination keep the filters", async () => {
        const app = openApp(`${base}/item-definitions?category=potion`)
        fireEvent.click(await screen.findByRole("link", { name: "New item definition" }))
        await screen.findByRole("heading", { level: 1, name: "New item definition" })
        expect(trail()).toEqual(["Items", "Item definitions", "New item definition"])
        expect(trailLinks()).toEqual([`${base}/items`, `${base}/item-definitions?category=potion`])
        fireEvent.change(await screen.findByLabelText(/^Name/), { target: { value: "Elixir" } })
        fireEvent.change(screen.getByLabelText(/^Category/), { target: { value: "potion" } })
        fireEvent.click(screen.getByRole("button", { name: /^(Create|Save)/ }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/item-definitions`))
        expect(app.router.state.location.search).toBe("?category=potion")
        expect(notGet().filter((call) => call.method === "POST")).toHaveLength(1)
    })

    it("a legacy definitionsSearch key names the catalog with its filters; one the catalog does not produce is ignored", async () => {
        const app = openApp(`${base}/item-definitions`)
        await screen.findByRole("link", { name: "Edit Moonblade pattern" })
        await act(async () => {
            await app.router.navigate(`${base}/item-definitions/d1`, {
                state: { definitionsSearch: "?category=weapon&homebrew=1" },
            })
        })
        await screen.findByRole("heading", { level: 1, name: "Edit item definition" })
        expect(trail()).toEqual(["Items", "Item definitions", "Moonblade pattern"])
        expect(trailLinks()).toEqual([`${base}/items`, `${base}/item-definitions?category=weapon&homebrew=1`])
        await act(async () => {
            await app.router.navigate(`${base}/item-definitions/d1`, { state: { definitionsSearch: "?bogus=1" } })
        })
        await screen.findByRole("heading", { level: 1, name: "Edit item definition" })
        expect(trailLinks()).toEqual([`${base}/items`, `${base}/item-definitions`])
    })

    it("a direct entry to a definition shows the defaults, and a foreign or malformed task is ignored", async () => {
        const app = openApp(`${base}/item-definitions/d1`)
        await screen.findByRole("heading", { level: 1, name: "Edit item definition" })
        expect(entryState(app)?.task).toBeUndefined()
        expect(trail()).toEqual(["Items", "Item definitions", "Moonblade pattern"])
        expect(trailLinks()).toEqual([`${base}/items`, `${base}/item-definitions`])
        await act(async () => {
            await app.router.navigate(`${base}/item-definitions/d1`, {
                state: { task: { ...task("items"), scope: { campaignId: "elsewhere" } } },
            })
        })
        expect(trailLinks()).toEqual([`${base}/items`, `${base}/item-definitions`])
        await act(async () => {
            await app.router.navigate(`${base}/item-definitions/d1`, {
                state: {
                    task: {
                        ...task("items"),
                        list: { route: "itemDefinitions.list", search: "?category=weapon&evil=1" },
                    },
                },
            })
        })
        expect(trailLinks()).toEqual([`${base}/items`, `${base}/item-definitions`])
    })

    it("a definition that is not found keeps the page's terminal and its Back link to the filtered catalog", async () => {
        definitionResponse = NOT_FOUND
        openApp(`${base}/item-definitions/d1`)
        await screen.findByRole("heading", { level: 1, name: "Edit item definition" })
        expect(await screen.findByRole("link", { name: "Back to item definitions" })).toHaveAttribute(
            "href",
            `${base}/item-definitions`,
        )
        expect(trail()).toEqual(["Items", "Item definitions", "Edit item definition"])
    })

    it("a confirmed save leaves the breadcrumb and the task alone and sends the write once", async () => {
        server.on("POST", `${AUTH}/item-definitions/d1/update`, { body: definition({ row_version: 3, name: "Moonblade pattern" }) })
        const app = openApp(`${base}/item-definitions`)
        fireEvent.click(await screen.findByRole("link", { name: "Edit Moonblade pattern" }))
        const description = await screen.findByLabelText(/^Description/)
        fireEvent.change(description, { target: { value: "Glows brighter" } })
        fireEvent.click(screen.getByRole("button", { name: /^Save/ }))
        await waitFor(() => expect(notGet().filter((call) => call.path.endsWith("/update"))).toHaveLength(1))
        expect(entryState(app)?.task).toMatchObject({ root: "items" })
        expect(app.router.state.location.pathname).toBe(`${base}/item-definitions/d1`)
        expect(trail()).toEqual(["Items", "Item definitions", "Moonblade pattern"])
    })
})

describe("Items and definitions: authorization and reads", () => {
    it("a reader without canon.edit gets the permission notice and no authoring request", async () => {
        openApp(`${base}/items`, [])
        expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/)
        // The page's own list read (the server refuses it) and nothing else: no item, no definitions.
        expect(authoringReads().map((call) => call.path)).toEqual([`${AUTH}/items`])
        expect(screen.queryByRole("link", { name: "Item definitions" })).toBeNull()
    })

    it("an item route without canon.edit sends no item request and shows no breadcrumb", async () => {
        openApp(`${base}/items/i1`, [])
        expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/)
        expect(authoringReads()).toEqual([])
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
    })

    it("a campaign GM with no world role gets the inventory but not the catalog, and the catalog is never read", async () => {
        openApp(`${base}/items`, ["canon.edit"], { world_capabilities: ["world.view"] })
        await screen.findByRole("link", { name: "Moonblade" })
        expect(screen.queryByRole("link", { name: "Item definitions" })).toBeNull()
        expect(server.callsTo("GET", `${AUTH}/item-definitions`)).toHaveLength(0)
        cleanupRoute()
    })

    it("the catalog without a world role says so and sends no definitions request", async () => {
        openApp(`${base}/item-definitions/d1`, ["canon.edit"], { world_capabilities: ["world.view"] })
        expect(await screen.findByRole("alert")).toHaveTextContent(/need a world role/)
        expect(trail()).toEqual(["Items", "Item definitions", "Edit item definition"])
        expect(server.callsTo("GET", /item-definitions/)).toHaveLength(0)
    })

    it("opening an item or a definition adds no broad request and selects no perspective", async () => {
        const app = openApp(`${base}/items`)
        fireEvent.click(await screen.findByRole("link", { name: "Moonblade" }))
        await itemHeading()
        await screen.findByRole("heading", { level: 2, name: /Give or place/ })
        const paths = server.calls.map((call) => call.path.split("?")[0])
        // The item's own authorized reads and the world's time pickers; no character, party, quest,
        // knowledge, session or World search read was added by opening it.
        const added = paths.slice(paths.indexOf(`${AUTH}/items/i1`))
        expect(added.filter((path) => /\/(quests|knowledge|sessions|parties)|\/world\/search|\/characters\//.test(path))).toEqual([])
        expect(app.router.state.location.search).not.toContain("character_id")
        expect(notGet()).toEqual([])
    })
})

describe("Items and definitions: labels and states", () => {
    it("a late answer to a read started under the old authority never names the item; a re-read under the new one does", async () => {
        const parked: Array<(response: MockResponse) => void> = []
        itemGate = () => new Promise<MockResponse>((resolve) => parked.push(resolve))
        const app = openApp(`${base}/items`)
        fireEvent.click(await screen.findByRole("link", { name: "Moonblade" }))
        await waitFor(() => expect(parked).toHaveLength(1))
        // The authority changes under the mounted page (a refreshed bootstrap with other capabilities).
        const current = vi.mocked(useSessionBootstrap)()
        vi.mocked(useSessionBootstrap).mockReturnValue({
            ...current,
            state: {
                status: "authenticated",
                bootstrap: bootstrapFor(["access.manage", "canon.edit", "extra.capability"]),
            },
        })
        await act(() => app.router.navigate(`${base}/items/i1?r=1`, { replace: true, state: app.router.state.location.state }))
        await act(async () => {
            parked[0]!({ body: itemView({ name: "Old Name" }) })
        })
        // On to the edit page, whose own read is still out: the old answer's name was never registered.
        const carried = {
            task: task("items", [
                { route: "items.list", params: { campaignId: "mundivita" } },
                { route: "items.detail", params: { campaignId: "mundivita", itemId: "i1" } },
            ]),
        }
        await act(() => app.router.navigate(`${base}/items/i1/edit`, { state: carried }))
        await waitFor(() => expect(parked.length).toBeGreaterThanOrEqual(2))
        await waitFor(() => expect(trail()).toEqual(["Items", "Item", "Edit"]))
        expect(screen.queryByText("Old Name", { selector: "nav *" })).toBeNull()
        await act(async () => {
            parked.slice(1).forEach((resolve) => resolve({ body: itemView({ name: "New Name" }) }))
        })
        await waitFor(() => expect(trail()).toEqual(["Items", "New Name", "Edit"]))
    })

    it("the edit page's item crumb shows the name the workspace read, and the generic noun before any read", async () => {
        const app = openApp(`${base}/items`)
        await screen.findByRole("link", { name: "Moonblade" })
        // Entered straight at the edit page with the task: nothing has read the item yet.
        let release: (response: MockResponse) => void = () => undefined
        server.on("GET", `${AUTH}/items/i2`, () => new Promise<MockResponse>((resolve) => (release = resolve)))
        await act(async () => {
            await app.router.navigate(`${base}/items/i2/edit`, {
                state: { task: task("items", [{ route: "items.list", params: { campaignId: "mundivita" } }, { route: "items.detail", params: { campaignId: "mundivita", itemId: "i2" } }]) },
            })
        })
        await waitFor(() => expect(trail()).toEqual(["Items", "Item", "Edit"]))
        await act(async () => {
            release({ body: itemView({ item_instance_id: "i2", name: "Sunblade" }) })
        })
        await waitFor(() => expect(trail()).toEqual(["Items", "Sunblade", "Edit"]))
        expect(JSON.stringify(entryState(app))).not.toContain("Sunblade")
    })

    it("a refused edit read leaves the generic noun, never a held name", async () => {
        const app = openApp(`${base}/items`)
        fireEvent.click(await screen.findByRole("link", { name: "Moonblade" }))
        await itemHeading()
        fireEvent.click(stageLink(1))
        itemResponse = NOT_FOUND
        fireEvent.click(await screen.findByRole("link", { name: "Edit item" }))
        await waitFor(() => expect(trail()).toEqual(["Items", "Item", "Edit"]))
        expect(app.router.state.location.pathname).toBe(`${base}/items/i1/edit`)
    })

    it("an unavailable item says so with no breadcrumb and a failed read retries as a read", async () => {
        itemResponse = NOT_FOUND
        openApp(`${base}/items/i1`)
        expect(await screen.findByRole("heading", { name: "Item unavailable" })).toBeInTheDocument()
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
    })

    it("a server error on the item shows a retry that only reads", async () => {
        itemResponse = { status: 500, body: { error: { code: "server_error", message: "m", correlation_id: "c" } } }
        openApp(`${base}/items/i1`)
        const retry = await screen.findByRole("button", { name: "Try again" })
        itemResponse = { body: itemView() }
        fireEvent.click(retry)
        await itemHeading()
        expect(notGet()).toEqual([])
        expect(trail()).toEqual(["Items", "Moonblade"])
    })

    it("shows the inventory's loading and error states without a breadcrumb", async () => {
        server.on("GET", `${AUTH}/items`, { status: 500, body: { error: { code: "server_error", message: "m", correlation_id: "c" } } })
        openApp(`${base}/items`)
        expect(await screen.findByRole("heading", { level: 1, name: "Item inventory" })).toBeInTheDocument()
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
    })
})

// The server mock is rebuilt before every test; nothing needs undoing, but a test that opened the app
// with a narrowed campaign states that it did so on purpose.
function cleanupRoute() {
    expect(authoringReads().some((call) => /item-definitions/.test(call.path))).toBe(false)
}
