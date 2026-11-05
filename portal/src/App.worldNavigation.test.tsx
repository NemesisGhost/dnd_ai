import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { useSessionBootstrap } from "./hooks/useSessionBootstrap"
import { WORLD_BODY, bootstrapFor, openApp } from "./test/campaignRoutes"
import { installMockServer } from "./test/authoringHarness"
import type { MockResponse, MockServer } from "./test/authoringHarness"
import { FULL_RECORD_AUTHORING } from "./test/recordAuthoring"
import { installRecordReads } from "./test/worldWorkspaceMocks"

// P02-7d: the World family. The World browser, the record workspaces and readers, the edit and create
// pages, the event page and the related-record links carry the shared task (breadcrumb, validated task,
// the older worldSearch / reviewSearch keys, the label registry). A place's containment ("Location path")
// is a fact about the record and is never part of the task trail. These run the whole App over a memory data
// router (jsdom): they prove destinations, carried state, requests and rendered authorized content, not
// real-browser keyboard, focus, zoom or screen-reader behavior.

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

const card = (id: string, category: string, name: string) => ({
    entity_id: id,
    category,
    entity_type_code: category === "location" ? "building" : category === "organization" ? "guild" : "event",
    name,
    summary: null,
})

const locationDetail = (over: object = {}) => ({
    authoring: FULL_RECORD_AUTHORING,
    location_id: "l1",
    name: "Old Mill",
    summary: "A quiet mill.",
    location_type_code: "building",
    parent_location_id: null,
    breadcrumbs: [],
    population: null,
    building_use: null,
    danger_level: null,
    is_searched: null,
    is_destroyed: null,
    alarm_level: null,
    condition_notes: null,
    ...over,
})

const organizationDetail = (over: object = {}) => ({
    authoring: FULL_RECORD_AUTHORING,
    organization_id: "o1",
    name: "The Guild",
    summary: "Merchants.",
    kind_code: "business",
    organization_type_code: "guild",
    status_code: null,
    public_description: null,
    parent: null,
    headquarters: { entity_id: "l1", name: "Old Mill" },
    religion: null,
    ...over,
})

const lifecycle = (id: string, type: string, name: string) => ({
    entity_id: id,
    entity_type_code: type,
    canonical_name: name,
    canon_status: "draft",
    lifecycle_status: "active",
    row_version: 2,
    lifecycle_managed: true,
    superseded_by: null,
    available_actions: ["submit_for_review", "archive"],
    blocked_actions: [],
})

const LOCATION_OPTIONS = {
    can_create: true,
    categories: [{ code: "building", label: "Building", fields: [] }],
    limits: { name_max_length: 200, summary_max_length: 4000, change_note_max_length: 1000 },
}
const locationView = (over: object = {}) => ({
    location_id: "l1",
    name: "Old Mill",
    summary: "A quiet mill.",
    category: { code: "building", label: "Building" },
    parent: null,
    population: null,
    building_use: null,
    canon_status: "draft",
    lifecycle_status: "active",
    row_version: 3,
    available_actions: ["update", "archive"],
    blocked_actions: [],
    field_locks: [],
    ...over,
})

let server: MockServer
let searchResponse: MockResponse
let locationGate: () => MockResponse | Promise<MockResponse>

// The shell-level requests every campaign page makes, with a World browse the test controls (the first
// registered handler wins, so it is registered before the rest).
function installServer() {
    const mock = installMockServer()
    mock.on("GET", /^\/campaigns\/mundivita\/world\/search/, () => searchResponse)
    mock.on("GET", /^\/campaigns\/mundivita\/summary/, { body: {} })
    mock.on("GET", /^\/worlds\?/, { body: { items: [], next_cursor: null } })
    mock.on("GET", "/worlds/world-mundivita", { body: WORLD_BODY })
    mock.on("GET", /^\/campaigns\/mundivita\/characters\/[^/]+\/parties$/, {
        body: { character_id: "any", can_open: false, items: [] },
    })
    return mock
}

beforeEach(() => {
    server = installServer()
    searchResponse = {
        body: {
            items: [card("l1", "location", "Old Mill"), card("o1", "organization", "The Guild"), card("e1", "event", "The Fall")],
            next_cursor: null,
        },
    }
    locationGate = () => ({ body: locationDetail() })
    server.on("GET", `${API}/world/locations/l1`, () => locationGate())
    server.on("GET", `${API}/world/organizations/o1`, { body: organizationDetail() })
    server.on("GET", `${API}/entities/l1/lifecycle`, { body: lifecycle("l1", "location", "Old Mill") })
    server.on("GET", `${API}/entities/o1/lifecycle`, { body: lifecycle("o1", "organization", "The Guild") })
    installRecordReads(server, { campaignId: "mundivita", entityId: "l1", name: "Old Mill" })
    installRecordReads(server, { campaignId: "mundivita", entityId: "o1", name: "The Guild" })
    server.on("GET", `${API}/world/events/e1`, {
        body: {
            event_id: "e1",
            name: "The Fall",
            summary: null,
            event_type_code: "battle",
            event_status_code: "recorded",
            world_time_id: "t1",
            details: null,
            session_id: null,
            participants: [],
            locations: [],
            explanation: null,
        },
    })
    server.on("GET", `${AUTH}/locations/l1`, { body: locationView() })
    server.on("GET", `${AUTH}/locations/options`, { body: LOCATION_OPTIONS })
    server.on("GET", /parent-options/, { body: { items: [], next_cursor: null } })
    server.on("POST", `${AUTH}/locations`, {
        status: 201,
        body: { ...locationView({ location_id: "l2", name: "Hollow" }), changed: true },
    })
})

afterEach(() => {
    vi.unstubAllGlobals()
})

type Opened = ReturnType<typeof openApp>
type EntryState = {
    task?: { root: string; scope: unknown; trail: Array<{ route: string }>; list?: { route: string; search: string } }
    worldSearch?: string
    reviewSearch?: string
    announce?: string
}
const entryState = (app: Pick<Opened, "router">) => app.router.state.location.state as EntryState | null
const breadcrumb = () => within(screen.getByRole("navigation", { name: "Breadcrumb" }))
const trail = () => breadcrumb().getAllByRole("listitem").map((item) => item.textContent)
const trailLinks = () => breadcrumb().getAllByRole("link").map((link) => link.getAttribute("href"))
const notGet = () => server.calls.filter((call) => call.method !== "GET")
const authoringReads = () => server.calls.filter((call) => call.path.includes("/authoring/") || call.path.includes("/lifecycle"))
const FILTERED = "?category=location&q=mill"

async function openRecordFromBrowser(entry = `${base}/world${FILTERED}`, name = "Old Mill") {
    const app = openApp(entry)
    fireEvent.click(await screen.findByRole("link", { name: new RegExp(name) }))
    await screen.findByRole("heading", { level: 1, name })
    // The workspace fills in its missing ?section= once its lifecycle read has answered; a link followed
    // before that is raced by the page's own normalization (observed, and recorded in the audit).
    await waitFor(() => expect(app.router.state.location.search).toContain("section="))
    return app
}

describe("World browser to record: task origin", () => {
    it("a record opened from the filtered browser keeps World's task, the filters and no name in the entry state", async () => {
        const app = await openRecordFromBrowser()
        expect(app.router.state.location.pathname).toBe(`${base}/world/location/l1`)
        expect(entryState(app)?.task).toMatchObject({
            root: "world",
            scope: { campaignId: "mundivita" },
            list: { route: "campaign.world", search: FILTERED },
        })
        // The list rides in the task alone: no older key is written beside it.
        expect(entryState(app)).not.toHaveProperty("worldSearch")
        expect(JSON.stringify(entryState(app))).not.toContain("Old Mill")
        expect(trail()).toEqual(["World", "Old Mill"])
        expect(trailLinks()).toEqual([`${base}/world${FILTERED}`])
        expect(breadcrumb().getByText("Old Mill")).toHaveAttribute("aria-current", "page")
        expect(screen.queryByRole("link", { name: "Back to World" })).toBeNull()
        fireEvent.click(breadcrumb().getByRole("link", { name: "World" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/world`))
        expect(app.router.state.location.search).toBe(FILTERED)
    })

    it("the section the workspace fills in and the section links keep the task", async () => {
        const app = await openRecordFromBrowser()
        const key = app.router.state.location.key
        fireEvent.click(await screen.findByRole("link", { name: "Sources" }))
        await waitFor(() => expect(app.router.state.location.search).toBe("?section=sources"))
        expect(app.router.state.location.key).not.toBe(key)
        expect(entryState(app)?.task).toMatchObject({ root: "world", list: { search: FILTERED } })
        expect(trail()).toEqual(["World", "Old Mill"])
        await act(async () => {
            await app.router.navigate(-1)
        })
        expect(entryState(app)?.task).toMatchObject({ root: "world" })
    })

    it("a direct entry keeps the back link it always had and links carry no origin", async () => {
        const app = openApp(`${base}/world/location/l1?section=details`)
        const back = await screen.findByRole("link", { name: "Back to World" })
        expect(back).toHaveAttribute("href", `${base}/world`)
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
        fireEvent.click(await screen.findByRole("link", { name: "Sources" }))
        await waitFor(() => expect(app.router.state.location.search).toBe("?section=sources"))
        expect(entryState(app)?.task).toBeUndefined()
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
    })

    it("state that fails validation (a foreign campaign, an unknown root, a crafted trail) is ignored", async () => {
        const app = openApp(`${base}/world`)
        const crafted = [
            { v: 1, root: "world", scope: { campaignId: "other" }, trail: [] },
            { v: 1, root: "nowhere", scope: { campaignId: "mundivita" }, trail: [] },
            { v: 1, root: "world", scope: { campaignId: "mundivita" }, trail: [{ route: "http://evil", params: {} }] },
        ]
        for (const task of crafted) {
            await act(async () => {
                await app.router.navigate(`${base}/world/location/l1?section=details`, { state: { task } })
            })
            await screen.findByRole("link", { name: "Back to World" })
            expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
        }
    })

    it("a legacy worldSearch key adapts to World's task, a query the browser does not produce does not", async () => {
        const app = openApp(`${base}/world`)
        await act(async () => {
            await app.router.navigate(`${base}/world/location/l1?section=details`, {
                state: { worldSearch: "?category=location&q=fort" },
            })
        })
        await screen.findByRole("heading", { level: 1, name: "Old Mill" })
        expect(trailLinks()).toEqual([`${base}/world?category=location&q=fort`])
        await act(async () => {
            await app.router.navigate(`${base}/world/location/l1?section=details`, {
                state: { worldSearch: "?returnTo=https://evil" },
            })
        })
        await screen.findByRole("link", { name: "Back to World" })
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
    })

    it("a record opened from the Review queue keeps the Review task and its filters, with no older key beside it", async () => {
        server.on("GET", /\/campaigns\/mundivita\/review-queue/, {
            body: {
                items: [
                    {
                        entity_id: "l1",
                        name: "Old Mill",
                        entity_type_code: "settlement",
                        category: "location",
                        canon_status: "draft",
                        lifecycle_status: "active",
                        row_version: 2,
                        updated_at: "2026-01-02T10:00:00Z",
                        last_change_by: "Gina",
                        last_change_by_me: false,
                    },
                ],
                next_cursor: null,
                status: "draft",
                statuses: [{ value: "draft", label: "Drafts" }],
                types: ["settlement"],
                counts: { draft: 1 },
            },
        })
        const app = openApp(`${base}/review?status=draft`, ["access.manage", "canon.edit"])
        fireEvent.click(await screen.findByRole("link", { name: "Old Mill" }))
        await screen.findByRole("heading", { level: 1, name: "Old Mill" })
        expect(entryState(app)?.task).toMatchObject({ root: "review", list: { route: "review.queue", search: "?status=draft" } })
        expect(entryState(app)).not.toHaveProperty("reviewSearch")
        expect(trail()).toEqual(["Review queue", "Old Mill"])
        expect(trailLinks()).toEqual([`${base}/review?status=draft`])
        expect(screen.queryByRole("link", { name: "Back to World" })).toBeNull()
    })

    it("a Review queue record entered with only the older key (an entry written before the task) still leads back to the queue", async () => {
        const app = openApp(`${base}/review?status=draft`)
        await act(async () => {
            await app.router.navigate(`${base}/world/location/l1?section=details`, {
                state: { reviewSearch: "?status=draft" },
            })
        })
        await screen.findByRole("heading", { level: 1, name: "Old Mill" })
        expect(trail()).toEqual(["Review queue", "Old Mill"])
        expect(trailLinks()).toEqual([`${base}/review?status=draft`])
        expect(screen.queryByRole("link", { name: "Back to World" })).toBeNull()
    })
})

describe("Containment is not task origin", () => {
    const area = () =>
        locationDetail({
            location_id: "l1",
            name: "Entry Hall",
            location_type_code: "building",
            parent_location_id: "d1",
            breadcrumbs: [{ location_id: "d1", name: "Crypt", location_type_code: "building" }],
        })

    it("a reader's Location path lists the containment and the breadcrumb lists only the task", async () => {
        locationGate = () => ({ body: area() })
        openApp(`${base}/world${FILTERED}`, ["access.manage"])
        fireEvent.click(await screen.findByRole("link", { name: /Old Mill/ }))
        await screen.findByRole("heading", { level: 1, name: "Entry Hall" })
        expect(trail()).toEqual(["World", "Entry Hall"])
        const path = screen.getByRole("list", { name: "Location path" })
        expect(within(path).getByText(/Crypt/)).toBeInTheDocument()
        expect(screen.getByRole("navigation", { name: "Breadcrumb" })).not.toContainElement(path)
        expect(within(screen.getByRole("navigation", { name: "Breadcrumb" })).queryByText(/Crypt/)).toBeNull()
        expect(authoringReads()).toEqual([])
    })

    it("a record reached through a visited trail is not given containment it does not have", async () => {
        const app = openApp(`${base}/world`)
        const trailOf = [
            { route: "world.record", params: { campaignId: "mundivita", category: "organization", entityId: "o1" } },
        ]
        await act(async () => {
            await app.router.navigate(`${base}/world/location/l1?section=details`, {
                state: { task: { v: 1, root: "world", scope: { campaignId: "mundivita" }, trail: trailOf } },
            })
        })
        await screen.findByRole("heading", { level: 1, name: "Old Mill" })
        // The organization is a step of the task, shown under the generic noun until a page has read its name;
        // the place's own (empty) containment is untouched.
        expect(trail()).toEqual(["World", "Record", "Old Mill"])
        expect(trailLinks()[1]).toBe(`${base}/world/organization/o1`)
        expect(screen.queryByRole("list", { name: "Location path" })).toBeNull()
    })
})

describe("Related records and edit pages", () => {
    it("an organization's headquarters link continues the task, and the breadcrumb names the organization once it is read", async () => {
        const app = openApp(`${base}/world${FILTERED}`)
        fireEvent.click(await screen.findByRole("link", { name: /The Guild/ }))
        await screen.findByRole("heading", { level: 1, name: "The Guild" })
        // Reach the Details section where the panels (and the headquarters link) are.
        const link = await screen.findByRole("link", { name: "Old Mill" })
        fireEvent.click(link)
        await screen.findByRole("heading", { level: 1, name: "Old Mill" })
        expect(app.router.state.location.pathname).toBe(`${base}/world/location/l1`)
        expect(entryState(app)?.task?.trail.map((entry) => entry.route)).toEqual(["campaign.world", "world.record"])
        await waitFor(() => expect(trail()).toEqual(["World", "The Guild", "Old Mill"]))
        expect(trailLinks()).toEqual([`${base}/world${FILTERED}`, `${base}/world/organization/o1`])
        expect(JSON.stringify(entryState(app))).not.toContain("The Guild")
        // Following the organization crumb returns to it with the task cut back to before it.
        fireEvent.click(breadcrumb().getByRole("link", { name: "The Guild" }))
        await screen.findByRole("heading", { level: 1, name: "The Guild" })
        expect(entryState(app)?.task?.trail.map((entry) => entry.route)).toEqual(["campaign.world"])
        expect(trail()).toEqual(["World", "The Guild"])
    })

    it("Edit continues World's task: the edit page names the record, Cancel returns to it inside the task", async () => {
        const app = await openRecordFromBrowser()
        fireEvent.click(await screen.findByRole("link", { name: "Edit location" }))
        await screen.findByRole("heading", { level: 1, name: "Edit location" })
        await waitFor(() => expect(trail()).toEqual(["World", "Old Mill", "Edit location"]))
        expect(trailLinks()).toEqual([`${base}/world${FILTERED}`, `${base}/world/location/l1`])
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        await screen.findByRole("heading", { level: 1, name: "Old Mill" })
        expect(app.router.state.location.pathname).toBe(`${base}/world/location/l1`)
        expect(app.router.state.location.search).toBe("?section=details")
        // The record's own task again: the edit page and the record are not in it, the browser the link came from is.
        expect(entryState(app)?.task).toMatchObject({ root: "world", list: { search: FILTERED } })
        expect(entryState(app)?.task?.trail.map((entry) => entry.route)).toEqual(["campaign.world"])
        expect(trail()).toEqual(["World", "Old Mill"])
        expect(notGet()).toEqual([])
    })

    it("a dirty edit page asks on a breadcrumb ancestor: Stay keeps the draft and the task, Leave goes without a write", async () => {
        const app = await openRecordFromBrowser()
        fireEvent.click(await screen.findByRole("link", { name: "Edit location" }))
        const name = await screen.findByLabelText(/^Name/)
        fireEvent.change(name, { target: { value: "Old Mill II" } })
        fireEvent.click(breadcrumb().getByRole("link", { name: "Old Mill" }))
        const dialog = await screen.findByRole("dialog")
        fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
        expect(app.router.state.location.pathname).toBe(`${base}/world/location/l1/edit`)
        expect(screen.getByLabelText(/^Name/)).toHaveValue("Old Mill II")
        expect(entryState(app)?.task).toMatchObject({ root: "world" })
        fireEvent.click(breadcrumb().getByRole("link", { name: "Old Mill" }))
        fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Discard changes" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/world/location/l1`))
        expect(notGet()).toEqual([])
    })

    it("the edit page's record crumb is the generic noun before any read and never a held name after a refusal", async () => {
        const app = openApp(`${base}/world${FILTERED}`)
        await screen.findByRole("link", { name: /Old Mill/ })
        let release: (response: MockResponse) => void = () => undefined
        server.on("GET", `${AUTH}/locations/l9`, () => new Promise<MockResponse>((resolve) => (release = resolve)))
        const carried = {
            task: {
                v: 1,
                root: "world",
                scope: { campaignId: "mundivita" },
                trail: [{ route: "world.record", params: { campaignId: "mundivita", category: "location", entityId: "l9" } }],
            },
        }
        await act(async () => {
            await app.router.navigate(`${base}/world/location/l9/edit`, { state: carried })
        })
        await waitFor(() => expect(trail()).toEqual(["World", "Record", "Edit location"]))
        await act(async () => {
            release({ body: locationView({ location_id: "l9", name: "Sunken Keep" }) })
        })
        await waitFor(() => expect(trail()).toEqual(["World", "Sunken Keep", "Edit location"]))
        expect(JSON.stringify(entryState(app))).not.toContain("Sunken Keep")
        server.on("GET", `${AUTH}/locations/l8`, NOT_FOUND)
        await act(async () => {
            await app.router.navigate(`${base}/world/location/l8/edit`, {
                state: { task: { ...carried.task, trail: [{ route: "world.record", params: { campaignId: "mundivita", category: "location", entityId: "l8" } }] } },
            })
        })
        await waitFor(() => expect(trail()).toEqual(["World", "Record", "Edit location"]))
    })

    it("an edit page entered with only the older keys keeps its single World / record links", async () => {
        const app = openApp(`${base}/world`)
        await act(async () => {
            await app.router.navigate(`${base}/world/location/l1/edit`, {
                state: {
                    worldSearch: FILTERED,
                    returnTo: { pathname: `${base}/world/location/l1`, search: "?section=details" },
                },
            })
        })
        const heading = await screen.findByRole("heading", { level: 1, name: "Edit location" })
        expect(heading).toBeInTheDocument()
        await waitFor(() => expect(screen.getByRole("link", { name: "Old Mill" })).toHaveAttribute("href", `${base}/world/location/l1?section=details`))
        expect(screen.getByRole("link", { name: "World" })).toHaveAttribute("href", `${base}/world${FILTERED}`)
    })
})

describe("Items reached from a character", () => {
    it("a World item opened inside the Characters task shows that task, not World's", async () => {
        server.on("GET", `${API}/world/items/i1`, {
            body: {
                item_instance_id: "i1",
                name: "Moonblade",
                summary: null,
                origin_notes: null,
                item_definition_id: "d1",
                quantity: 1,
                condition_percentage: null,
                charges_current: null,
                charges_maximum: null,
                is_equipped: false,
                is_destroyed: false,
            },
        })
        const app = openApp(`${base}/characters/all`, ["access.manage"])
        await screen.findByRole("heading", { level: 1, name: /Characters/ })
        await act(async () => {
            await app.router.navigate(`${base}/world/item/i1`, {
                state: {
                    task: {
                        v: 1,
                        root: "characters",
                        scope: { campaignId: "mundivita" },
                        trail: [{ route: "characters.detail", params: { campaignId: "mundivita", characterId: "n1" } }],
                    },
                },
            })
        })
        await screen.findByRole("heading", { level: 1, name: "Moonblade" })
        expect(trail()).toEqual(["Characters", "Character", "Moonblade"])
        expect(trailLinks()).toEqual([`${base}/characters/all`, `${base}/characters/n1`])
        expect(screen.queryByRole("link", { name: "Back to World" })).toBeNull()
        expect(authoringReads()).toEqual([])
    })
})

describe("Create", () => {
    it("New location continues the task; the created place replaces the form inside it and Back skips the form", async () => {
        const app = openApp(`${base}/world${FILTERED}`)
        fireEvent.click(await screen.findByRole("link", { name: "New location" }))
        await screen.findByRole("heading", { level: 1, name: "New location" })
        expect(trail()).toEqual(["World", "New location"])
        expect(trailLinks()).toEqual([`${base}/world${FILTERED}`])
        fireEvent.change(await screen.findByLabelText(/^Name/), { target: { value: "Hollow" } })
        fireEvent.change(screen.getByRole("combobox", { name: /Category/ }), { target: { value: "building" } })
        fireEvent.click(screen.getByRole("button", { name: "Create location" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/world/location/l2`))
        expect(app.router.state.historyAction).toBe("REPLACE")
        expect(entryState(app)?.task).toMatchObject({ root: "world", list: { search: FILTERED } })
        expect(entryState(app)?.task?.trail.map((entry) => entry.route)).toEqual(["campaign.world"])
        expect(entryState(app)?.announce).toBe("Location created as a draft")
        expect(notGet()).toHaveLength(1)
        await act(async () => {
            await app.router.navigate(-1)
        })
        expect(app.router.state.location.pathname).toBe(`${base}/world`)
        expect(app.router.state.location.search).toBe(FILTERED)
    })

    it("a dirty New location form asks on a breadcrumb ancestor: Stay keeps the draft and the task, Leave goes without a write", async () => {
        const app = openApp(`${base}/world${FILTERED}`)
        fireEvent.click(await screen.findByRole("link", { name: "New location" }))
        const name = await screen.findByLabelText(/^Name/)
        fireEvent.change(name, { target: { value: "Draft" } })
        fireEvent.click(breadcrumb().getByRole("link", { name: "World" }))
        const dialog = await screen.findByRole("dialog")
        fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
        expect(app.router.state.location.pathname).toBe(`${base}/world/location/new`)
        expect(screen.getByLabelText(/^Name/)).toHaveValue("Draft")
        expect(entryState(app)?.task).toMatchObject({ root: "world" })
        fireEvent.click(breadcrumb().getByRole("link", { name: "World" }))
        fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Discard" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/world`))
        expect(app.router.state.location.search).toBe(FILTERED)
        expect(notGet()).toEqual([])
    })

    it("a direct entry to New location keeps its single World link", async () => {
        openApp(`${base}/world/location/new`)
        await screen.findByRole("heading", { level: 1, name: "New location" })
        expect(screen.getByRole("link", { name: "World" })).toHaveAttribute("href", `${base}/world`)
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
    })
})

describe("Events", () => {
    it("a World event opened from the browser keeps the task, and an editor's link to the event record continues it", async () => {
        server.on("GET", /\/campaigns\/mundivita\/events\//, NOT_FOUND)
        const app = openApp(`${base}/world${FILTERED}`)
        fireEvent.click(await screen.findByRole("link", { name: /The Fall/ }))
        await screen.findByRole("heading", { level: 1, name: "The Fall" })
        expect(trail()).toEqual(["World", "The Fall"])
        expect(trailLinks()).toEqual([`${base}/world${FILTERED}`])
        fireEvent.click(await screen.findByRole("link", { name: "Open the event record" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/events/e1`))
        expect(entryState(app)?.task).toMatchObject({ root: "world", list: { search: FILTERED } })
        expect(entryState(app)?.task?.trail.map((entry) => entry.route)).toEqual(["campaign.world", "world.record"])
        expect(notGet()).toEqual([])
    })

    it("a direct entry to a World event keeps the back link and an editor's event link carries nothing", async () => {
        server.on("GET", /\/campaigns\/mundivita\/events\//, NOT_FOUND)
        const app = openApp(`${base}/world/event/e1`)
        expect(await screen.findByRole("link", { name: "Back to World" })).toHaveAttribute("href", `${base}/world`)
        fireEvent.click(await screen.findByRole("link", { name: "Open the event record" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/events/e1`))
        expect(entryState(app)?.task).toBeUndefined()
    })
})

describe("Authorization, reads and states", () => {
    it("a reader without canon.edit gets the reader with the breadcrumb and sends no authoring, lifecycle or sources request", async () => {
        const app = openApp(`${base}/world${FILTERED}`, ["access.manage"])
        fireEvent.click(await screen.findByRole("link", { name: /Old Mill/ }))
        await screen.findByRole("heading", { level: 1, name: "Old Mill" })
        expect(trail()).toEqual(["World", "Old Mill"])
        expect(screen.queryByRole("link", { name: "Edit location" })).toBeNull()
        expect(authoringReads()).toEqual([])
        expect(server.calls.filter((call) => call.path.includes("/sources"))).toEqual([])
        expect(app.router.state.location.search).not.toContain("character_id")
    })

    it("opening a record adds no broad request and selects no perspective", async () => {
        const app = openApp(`${base}/world${FILTERED}`)
        fireEvent.click(await screen.findByRole("link", { name: /Old Mill/ }))
        await screen.findByRole("heading", { level: 1, name: "Old Mill" })
        const paths = server.calls.map((call) => call.path.split("?")[0])
        const added = paths.slice(paths.indexOf(`${API}/world/locations/l1`))
        expect(added.filter((path) => /\/(quests|knowledge|sessions|parties)|\/characters\/|\/world\/search/.test(path))).toEqual([])
        expect(app.router.state.location.search).not.toContain("character_id")
        expect(notGet()).toEqual([])
    })

    it("an unavailable record says so with its back link, no breadcrumb and no name", async () => {
        locationGate = () => NOT_FOUND
        openApp(`${base}/world${FILTERED}`)
        fireEvent.click(await screen.findByRole("link", { name: /Old Mill/ }))
        await screen.findByRole("heading", { level: 1, name: "Location unavailable" })
        expect(screen.getByRole("link", { name: "Back to World" })).toHaveAttribute("href", `${base}/world${FILTERED}`)
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
    })

    it("a late answer to a read started under the old authority never names the record; a re-read under the new one does", async () => {
        const parked: Array<(response: MockResponse) => void> = []
        locationGate = () => new Promise<MockResponse>((resolve) => parked.push(resolve))
        const app = openApp(`${base}/world${FILTERED}`)
        fireEvent.click(await screen.findByRole("link", { name: /Old Mill/ }))
        await waitFor(() => expect(parked).toHaveLength(1))
        const current = vi.mocked(useSessionBootstrap)()
        vi.mocked(useSessionBootstrap).mockReturnValue({
            ...current,
            state: {
                status: "authenticated",
                bootstrap: bootstrapFor(["access.manage", "canon.edit", "extra.capability"]),
            },
        })
        await act(() => app.router.navigate(`${base}/world/location/l1?r=1`, { replace: true, state: app.router.state.location.state }))
        await act(async () => {
            parked[0]!({ body: locationDetail({ name: "Old Name" }) })
        })
        const carried = {
            task: {
                v: 1,
                root: "world",
                scope: { campaignId: "mundivita" },
                trail: [{ route: "world.record", params: { campaignId: "mundivita", category: "location", entityId: "l1" } }],
            },
        }
        let release: (response: MockResponse) => void = () => undefined
        server.on("GET", `${AUTH}/locations/l1`, () => new Promise<MockResponse>((resolve) => (release = resolve)))
        await act(() => app.router.navigate(`${base}/world/location/l1/edit`, { state: carried }))
        await waitFor(() => expect(trail()).toEqual(["World", "Record", "Edit location"]))
        expect(screen.queryByText("Old Name", { selector: "nav *" })).toBeNull()
        await act(async () => {
            release({ body: locationView({ name: "New Name" }) })
        })
        await waitFor(() => expect(trail()).toEqual(["World", "New Name", "Edit location"]))
    })

    it("a server error on the record shows a retry that only reads", async () => {
        locationGate = () => ({ status: 500, body: { error: { code: "server_error", message: "m", correlation_id: "c" } } })
        openApp(`${base}/world${FILTERED}`)
        fireEvent.click(await screen.findByRole("link", { name: /Old Mill/ }))
        await screen.findByRole("heading", { level: 1, name: "Location information unavailable" })
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
        locationGate = () => ({ body: locationDetail() })
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        await screen.findByRole("heading", { level: 1, name: "Old Mill" })
        expect(notGet()).toEqual([])
    })
})

// P02-7d correction: a lone `returnTo` is a page's own Back address. It is not evidence of a task origin,
// so it must neither turn into a breadcrumb nor be forwarded as a synthesized task.
describe("returnTo is a back address, not a task origin", () => {
    const RETURN = { pathname: `${base}/characters/c1`, search: "?section=notes" }
    const ownTask = {
        v: 1,
        root: "world",
        scope: { campaignId: "mundivita" },
        trail: [],
        list: { route: "campaign.world", search: FILTERED },
    }

    it("a record entered with only returnTo keeps its single back link and forwards no task", async () => {
        const app = openApp(`${base}/world`)
        await act(async () => {
            await app.router.navigate(`${base}/world/location/l1?section=details`, { state: { returnTo: RETURN } })
        })
        const back = await screen.findByRole("link", { name: "Back to World" })
        expect(back).toHaveAttribute("href", `${base}/world`)
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
        fireEvent.click(await screen.findByRole("link", { name: "Sources" }))
        await waitFor(() => expect(app.router.state.location.search).toBe("?section=sources"))
        expect(entryState(app)?.task).toBeUndefined()
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
        expect(screen.getByRole("link", { name: "Back to World" })).toBeInTheDocument()
    })

    it("a related-record link from a returnTo-only entry carries no task", async () => {
        server.on("GET", `${API}/world/organizations/o1`, { body: organizationDetail() })
        const app = openApp(`${base}/world`)
        await act(async () => {
            await app.router.navigate(`${base}/world/organization/o1?section=details`, { state: { returnTo: RETURN } })
        })
        await screen.findByRole("heading", { level: 1, name: "The Guild" })
        fireEvent.click(await screen.findByRole("link", { name: /Old Mill/ }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/world/location/l1`))
        expect(entryState(app)?.task).toBeUndefined()
    })

    it("worldSearch / reviewSearch beside a returnTo still adapt to their task", async () => {
        const app = openApp(`${base}/world`)
        await act(async () => {
            await app.router.navigate(`${base}/world/location/l1?section=details`, {
                state: { worldSearch: FILTERED, returnTo: RETURN },
            })
        })
        await screen.findByRole("heading", { level: 1, name: "Old Mill" })
        expect(trail()).toEqual(["World", "Old Mill"])
        expect(trailLinks()).toEqual([`${base}/world${FILTERED}`])
        await act(async () => {
            await app.router.navigate(`${base}/world/location/l1?section=details`, {
                state: { reviewSearch: "?status=draft", returnTo: RETURN },
            })
        })
        await waitFor(() => expect(trail()).toEqual(["Review queue", "Old Mill"]))
    })

    it("an explicit task keeps precedence over a returnTo beside it", async () => {
        const app = openApp(`${base}/world`)
        await act(async () => {
            await app.router.navigate(`${base}/world/location/l1?section=details`, {
                state: { task: ownTask, returnTo: RETURN },
            })
        })
        await screen.findByRole("heading", { level: 1, name: "Old Mill" })
        expect(trail()).toEqual(["World", "Old Mill"])
        expect(trailLinks()).toEqual([`${base}/world${FILTERED}`])
    })

    it("a malformed or foreign returnTo fails safely to the single back link", async () => {
        const app = openApp(`${base}/world`)
        const bad = [
            { pathname: "//evil.example/x", search: "" },
            { pathname: "/app/other/characters/c1", search: "" },
            { pathname: 7, search: null },
            "https://evil.example",
        ]
        for (const returnTo of bad) {
            await act(async () => {
                await app.router.navigate(`${base}/world/location/l1?section=details`, { state: { returnTo } })
            })
            await screen.findByRole("link", { name: "Back to World" })
            expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
        }
    })
})
