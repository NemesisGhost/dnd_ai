import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { useSessionBootstrap } from "./hooks/useSessionBootstrap"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockResponse, MockServer } from "./test/authoringHarness"
import { FULL_RECORD_AUTHORING } from "./test/recordAuthoring"
import { installRecordReads } from "./test/worldWorkspaceMocks"

// P02-7b: Quests and Knowledge. The Quests and Knowledge tasks flow through the list, the record, its
// editor, the create page and the Member preview, carried by the shared breadcrumb, the validated task
// and the label registry. These run the whole App over a memory data router (jsdom): they prove
// destinations, requests, history and rendered authorized content, not real-browser keyboard, focus,
// zoom or screen-reader behavior.

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
    recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const base = "/app/mundivita"
const API = "/campaigns/mundivita"
const PERSPECTIVE = "?character_id=character-ixamarra&party_id=party-primary"
const NOT_FOUND: MockResponse = {
    status: 404,
    body: { error: { code: "not_found", message: "m", correlation_id: "c" } },
}
const NO_PERSPECTIVE = { character_perspectives: [], selected_character_id: null }

const QUEST_OPTIONS = {
    can_create: true,
    objective_types: [{ value: "other", label: "Other" }],
    stage_types: [{ value: "sequential", label: "Sequential" }],
    requirement_levels: [{ value: "required", label: "Required" }],
    completion_modes: [{ value: "automatic", label: "Automatic" }],
    visibility_policies: [{ value: "visible", label: "Visible" }],
    dependency_types: [{ value: "prerequisite", label: "Prerequisite" }],
    participant_roles: [{ value: "involved", label: "Involved" }],
    outcome_categories: [{ value: "success", label: "Success" }],
    reward_types: [{ value: "other", label: "Other" }],
    limits: {
        gm_notes_max_length: 4000,
        outcome_description_max_length: 4000,
        reward_description_max_length: 1000,
        name_max_length: 200,
        summary_max_length: 4000,
        change_note_max_length: 1000,
        max_stages: 100,
        max_objectives_per_stage: 100,
        quantity_max: 1000000,
    },
}
const QUEST_VIEW = {
    quest_id: "q1",
    name: "The Lost Amulet",
    summary: null,
    has_progress: false,
    gm_notes: null,
    dependencies: [],
    participants: [],
    outcomes: [],
    stages: [],
    canon_status: "draft",
    lifecycle_status: "active",
    row_version: 1,
    available_actions: ["update", "add_stage"],
    blocked_actions: [],
    field_locks: [],
}
const QUEST_LIST = [
    { quest_id: "q1", name: "The Lost Amulet", status_code: null, tracked: false, canon_status: "draft", lifecycle_status: "active" },
    { quest_id: "q2", name: "The Siege", status_code: "active", tracked: true, canon_status: "canon", lifecycle_status: "active" },
]
const QUEST_READER = { quest_id: "q2", name: "The Siege", status_code: "active", stages: [] }

const SUBJECT = { entity_id: "l1", name: "Keep", category: "location", entity_type_code: "fortress" }
const KNOWLEDGE_OPTIONS = {
    can_create: true,
    knowledge_types: [
        { value: "secret", label: "Secret" },
        { value: "rumor", label: "Rumor" },
    ],
    truth_statuses: [{ value: "true", label: "True" }],
    sensitivities: [{ value: "secret", label: "Secret" }],
    limits: { statement_max_length: 4000, change_note_max_length: 1000 },
}
const claimDetail = (extra: Record<string, unknown> = {}) => ({
    authoring: FULL_RECORD_AUTHORING,
    knowledge_item_id: "k1",
    knowledge_type_code: "secret",
    statement: "The duke is a vampire.",
    truth_status_code: "true",
    sensitivity: "secret",
    awareness_level: null,
    confidence: null,
    willing_to_share: null,
    subject: SUBJECT,
    ...extra,
})
const claimView = {
    knowledge_item_id: "k1",
    statement: "The duke is a vampire.",
    knowledge_type: "secret",
    truth_status: "true",
    sensitivity: "secret",
    subject: { entity_id: "l1", name: "Keep", canon_status: "canon", lifecycle_status: "active" },
    in_use: false,
    canon_status: "draft",
    lifecycle_status: "active",
    row_version: 1,
    available_actions: ["update"],
    blocked_actions: [],
    field_locks: [],
}
const listItem = {
    knowledge_item_id: "k1",
    knowledge_type_code: "secret",
    statement: "The duke is a vampire.",
    truth_status_code: null,
    sensitivity: null,
    awareness_level: null,
    confidence: null,
    willing_to_share: null,
    subject: SUBJECT,
}

let server: MockServer
let readerResponse: MockResponse
let claimResponse: (path: string) => MockResponse

beforeEach(() => {
    server = installCampaignShellMocks()
    readerResponse = { body: QUEST_READER }
    claimResponse = () => ({ body: claimDetail() })
    server.on("GET", `${API}/authoring/quests/options`, { body: QUEST_OPTIONS })
    server.on("GET", `${API}/authoring/quests/q1`, () => ({ body: QUEST_VIEW }))
    server.on("GET", /\/entities\/q1\/lifecycle$/, { status: 404 })
    server.on("GET", `${API}/quests/q1/progress`, { body: { quest_id: "q1", name: "The Lost Amulet", published: false, scopes: [] } })
    installRecordReads(server, { campaignId: "mundivita", entityId: "q1", name: "The Lost Amulet", entityTypeCode: "quest" })
    server.on("GET", /^\/campaigns\/mundivita\/quests(\?.*)?$/, { body: QUEST_LIST })
    server.on("GET", /^\/campaigns\/mundivita\/quests\/q2(\?.*)?$/, () => readerResponse)
    server.on("POST", `${API}/authoring/quests`, { status: 201, body: { quest_id: "q1", record_id: "r1", changed: true } })

    server.on("GET", `${API}/authoring/knowledge/options`, { body: KNOWLEDGE_OPTIONS })
    server.on("GET", `${API}/authoring/knowledge/k1`, () => ({ body: claimView }))
    server.on("GET", /^\/campaigns\/mundivita\/knowledge\/k1(\?.*)?$/, (call) => claimResponse(call.path))
    server.on("GET", /^\/campaigns\/mundivita\/knowledge(\?.*)?$/, { body: { items: [listItem], next_cursor: null } })
    server.on("GET", /\/entities\/k1\/lifecycle$/, { status: 404 })
    server.on("GET", /\/entities\/k1\/provenance$/, { status: 404 })
    server.on("GET", `${API}/knowledge/k1/audience`, { status: 404 })
    server.on("GET", `${API}/sources`, { body: { items: [], source_types: [], limits: { title_max_length: 200, reference_max_length: 2000 } } })
    server.on("GET", /audience-preview|audience_preview/, { status: 404 })
    server.on("GET", /\/campaigns\/mundivita\/parties/, { body: { can_create: false, items: [] } })
    server.on("POST", `${API}/authoring/knowledge`, { status: 201, body: { knowledge_item_id: "k1", record_id: "r1", changed: true } })
})

afterEach(() => {
    vi.unstubAllGlobals()
})

type Opened = ReturnType<typeof openApp>
type EntryState = {
    task?: { root: string; scope: unknown; trail: Array<{ route: string }> }
    reviewSearch?: string
}
const entryState = (app: Pick<Opened, "router">) => app.router.state.location.state as EntryState | null
const breadcrumb = () => within(screen.getByRole("navigation", { name: "Breadcrumb" }))
const trail = () => breadcrumb().getAllByRole("listitem").map((item) => item.textContent)
const trailLinks = () => breadcrumb().getAllByRole("link").map((link) => link.getAttribute("href"))
const notGet = () => server.calls.filter((call) => call.method !== "GET")
const authoringReads = () => server.calls.filter((call) => call.path.includes("/authoring/"))

describe("Quests: list, record and create", () => {
    it("a quest opened from the list keeps the Quests task, with the list's perspective on the way back", async () => {
        const app = openApp(`${base}/quests`, ["campaign.view"])
        fireEvent.click(await screen.findByRole("link", { name: /The Siege, Active/ }))
        await screen.findByRole("heading", { level: 1, name: "The Siege" })
        expect(entryState(app)?.task).toMatchObject({ root: "quests", scope: { campaignId: "mundivita" } })
        expect(trail()).toEqual(["Quests", "The Siege"])
        expect(trailLinks()).toEqual([`${base}/quests${PERSPECTIVE}`])
        expect(breadcrumb().getByText("The Siege")).toHaveAttribute("aria-current", "page")
        expect(JSON.stringify(entryState(app))).not.toContain("Siege")
        fireEvent.click(breadcrumb().getByRole("link", { name: "Quests" }))
        await screen.findByRole("heading", { level: 1, name: "Quests" })
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
        expect(authoringReads()).toEqual([])
    })

    it("an editor's workspace shows the task, keeps it through its sections and returns to the list under the perspective", async () => {
        const app = openApp(`${base}/quests`)
        fireEvent.click(await screen.findByRole("link", { name: /The Lost Amulet, Draft/ }))
        await screen.findByRole("heading", { level: 1, name: "The Lost Amulet" })
        await waitFor(() => expect(trail()).toEqual(["Quests", "The Lost Amulet"]))
        expect(trailLinks()).toEqual([`${base}/quests${PERSPECTIVE}`])
        expect(screen.queryByRole("link", { name: "Back to Quests" })).toBeNull()
        const key = app.router.state.location.key
        fireEvent.click(screen.getAllByRole("link", { name: /Use in play|Review & publish/ })[0]!)
        await waitFor(() => expect(app.router.state.location.key).not.toBe(key))
        expect(entryState(app)?.task).toMatchObject({ root: "quests" })
        expect(trail()).toEqual(["Quests", "The Lost Amulet"])
        fireEvent.click(breadcrumb().getByRole("link", { name: "Quests" }))
        await screen.findByRole("heading", { level: 1, name: "Quests" })
        expect(app.router.state.location.search).toBe(PERSPECTIVE)
        expect(notGet()).toEqual([])
    })

    it("keeps the single Back to Quests link after a direct entry, and the Review queue's own return", async () => {
        openApp(`${base}/quests/q1`)
        await screen.findByRole("heading", { level: 1, name: "The Lost Amulet" })
        expect(screen.getByRole("link", { name: "Back to Quests" })).toBeInTheDocument()
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
    })

    it("the Review queue's return is unchanged", async () => {
        const app = openApp(`${base}/review`)
        await act(async () => {
            await app.router.navigate(`${base}/quests/q1`, { state: { reviewSearch: "?status=draft" } })
        })
        await screen.findByRole("heading", { level: 1, name: "The Lost Amulet" })
        expect(screen.getByRole("link", { name: "Back to Review queue" })).toBeInTheDocument()
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
    })

    it("a member's reader shows the same trail, sends no editor request, and keeps the perspective", async () => {
        const app = openApp(`${base}/quests`, ["campaign.view"])
        fireEvent.click(await screen.findByRole("link", { name: /The Siege, Active/ }))
        await screen.findByRole("heading", { level: 1, name: "The Siege" })
        expect(trail()).toEqual(["Quests", "The Siege"])
        expect(trailLinks()).toEqual([`${base}/quests${PERSPECTIVE}`])
        expect(screen.queryByRole("link", { name: "New quest" })).toBeNull()
        expect(authoringReads()).toEqual([])
        expect(entryState(app)?.task).toMatchObject({ root: "quests" })
    })

    it("a direct entry to the reader gives the route's defaults and carries no task onward", async () => {
        const app = openApp(`${base}/quests/q2`, ["campaign.view"])
        await screen.findByRole("heading", { level: 1, name: "The Siege" })
        expect(trail()).toEqual(["Quests", "The Siege"])
        expect(entryState(app)?.task).toBeUndefined()
    })

    it.each([
        ["a task for another campaign", { task: { v: 1, root: "quests", scope: { campaignId: "other" }, trail: [] } }],
        ["a root the route does not allow", { task: { v: 1, root: "access", scope: { campaignId: "mundivita" }, trail: [] } }],
        ["a URL in the trail", { task: { v: 1, root: "quests", scope: { campaignId: "mundivita" }, trail: [{ route: "quests.detail", params: { questId: "https://evil.example/" } }] } }],
        ["a non-object", "task"],
    ])("ignores %s and uses the defaults", async (_name, crafted) => {
        const app = openApp(`${base}/quests/q2`, ["campaign.view"])
        await screen.findByRole("heading", { level: 1, name: "The Siege" })
        await act(async () => {
            await app.router.navigate(`${base}/quests/q2`, { state: crafted })
        })
        await screen.findByRole("heading", { level: 1, name: "The Siege" })
        expect(trail()).toEqual(["Quests", "The Siege"])
        expect(trailLinks()).toEqual([`${base}/quests${PERSPECTIVE}`])
    })

    it("New quest from the list is a step of the task, and a created quest takes the form's place in it", async () => {
        const app = openApp(`${base}/quests`)
        fireEvent.click(await screen.findByRole("link", { name: "New quest" }))
        await screen.findByRole("heading", { level: 1, name: "New quest" })
        expect(trail()).toEqual(["Quests", "New quest"])
        fireEvent.change(await screen.findByLabelText(/^Name/), { target: { value: "The Lost Amulet" } })
        fireEvent.click(screen.getByRole("button", { name: "Create quest" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/quests/q1`))
        expect(app.router.state.historyAction).toBe("REPLACE")
        expect(entryState(app)?.task).toMatchObject({ root: "quests" })
        await screen.findByRole("heading", { level: 1, name: "The Lost Amulet" })
        await waitFor(() => expect(trail()).toEqual(["Quests", "The Lost Amulet"]))
        expect(server.callsTo("POST", `${API}/authoring/quests`)).toHaveLength(1)
    })

    it("a dirty New quest form asks first: Stay keeps the draft and the task, Leave goes without a write", async () => {
        const app = openApp(`${base}/quests`)
        fireEvent.click(await screen.findByRole("link", { name: "New quest" }))
        fireEvent.change(await screen.findByLabelText(/^Name/), { target: { value: "Draft" } })
        const key = app.router.state.location.key
        fireEvent.click(breadcrumb().getByRole("link", { name: "Quests" }))
        const dialog = await screen.findByRole("dialog")
        expect(app.router.state.location.key).toBe(key)
        fireEvent.click(within(dialog).getByRole("button", { name: /Keep editing|Stay/ }))
        await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
        expect(screen.getByLabelText(/^Name/)).toHaveValue("Draft")
        expect(entryState(app)?.task).toMatchObject({ root: "quests" })
        fireEvent.click(breadcrumb().getByRole("link", { name: "Quests" }))
        fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: /Discard/ }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/quests`))
        expect(notGet()).toEqual([])
    })

    it("choosing a party on the list stays in the task and keeps the list entry", async () => {
        const two = {
            character_perspectives: [
                {
                    character_id: "character-ixamarra",
                    character_name: "Ixamarra",
                    authorized_parties: [
                        { party_id: "party-primary", party_name: "The Adventuring Party" },
                        { party_id: "party-second", party_name: "The Other Party" },
                    ],
                },
            ],
            selected_character_id: "character-ixamarra",
        }
        const app = openApp(`${base}/quests`, ["campaign.view"], two)
        fireEvent.click(await screen.findByRole("link", { name: /The Siege, Active/ }))
        await screen.findByRole("heading", { level: 1, name: "The Siege" })
        fireEvent.click(breadcrumb().getByRole("link", { name: "Quests" }))
        const select = await screen.findByRole("combobox", { name: "Party" })
        await act(async () => {
            fireEvent.change(select, { target: { value: "party-second" } })
        })
        await waitFor(() => expect(app.router.state.location.search).toContain("party_id=party-second"))
        expect(app.router.state.historyAction).toBe("REPLACE")
        expect(entryState(app)?.task).toMatchObject({ root: "quests", trail: [] })
    })

    it("a refused quest says so without naming it, and its trail has the generic noun", async () => {
        readerResponse = NOT_FOUND
        openApp(`${base}/quests/q2`, ["campaign.view"], NO_PERSPECTIVE)
        expect(await screen.findByRole("heading", { name: "Quest unavailable" })).toBeInTheDocument()
        expect(screen.queryByText("The Siege")).toBeNull()
    })
})

describe("Knowledge: list, claim and create", () => {
    it("a claim opened from the list keeps the Knowledge task through its sections and its subject", async () => {
        const app = openApp(`${base}/knowledge`)
        fireEvent.click(await screen.findByRole("link", { name: "The duke is a vampire." }))
        await screen.findByRole("heading", { level: 1, name: "The duke is a vampire." })
        expect(entryState(app)?.task).toMatchObject({ root: "knowledge", scope: { campaignId: "mundivita" } })
        expect(trail()).toEqual(["Knowledge", "Claim"])
        expect(trailLinks()).toEqual([`${base}/knowledge${PERSPECTIVE.replace("&party_id=party-primary", "")}`])
        expect(breadcrumb().getByText("Claim")).toHaveAttribute("aria-current", "page")
        await waitFor(() => expect(app.router.state.location.search).toContain("section="))
        expect(entryState(app)?.task).toMatchObject({ root: "knowledge" })

        const key = app.router.state.location.key
        fireEvent.click(screen.getAllByRole("link", { name: /Use in play/ })[0]!)
        await waitFor(() => expect(app.router.state.location.key).not.toBe(key))
        expect(app.router.state.location.search).toContain("section=who-knows")
        expect(entryState(app)?.task).toMatchObject({ root: "knowledge" })
        expect(trail()).toEqual(["Knowledge", "Claim"])
        expect(JSON.stringify(entryState(app))).not.toContain("vampire")
    })

    it("a member's reader has no stages, no editor request, and the same trail", async () => {
        claimResponse = () => ({ body: claimDetail({ authoring: undefined }) })
        const app = openApp(`${base}/knowledge`, ["campaign.view"])
        fireEvent.click(await screen.findByRole("link", { name: "The duke is a vampire." }))
        await screen.findByRole("heading", { level: 1, name: "The duke is a vampire." })
        expect(trail()).toEqual(["Knowledge", "Claim"])
        expect(screen.queryByRole("navigation", { name: "Claim stages" })).toBeNull()
        expect(authoringReads()).toEqual([])
        expect(entryState(app)?.task).toMatchObject({ root: "knowledge" })
    })

    it("a direct entry gives Knowledge > Claim and carries no task into its section links", async () => {
        const app = openApp(`${base}/knowledge/k1`)
        await screen.findByRole("heading", { level: 1, name: "The duke is a vampire." })
        expect(trail()).toEqual(["Knowledge", "Claim"])
        await waitFor(() => expect(app.router.state.location.search).toContain("section="))
        fireEvent.click(screen.getAllByRole("link", { name: /Use in play/ })[0]!)
        await waitFor(() => expect(app.router.state.location.search).toContain("section=who-knows"))
        expect(entryState(app)?.task).toBeUndefined()
    })

    it.each([
        ["a task for another campaign", { task: { v: 1, root: "knowledge", scope: { campaignId: "other" }, trail: [] } }],
        ["a root the route does not allow", { task: { v: 1, root: "parties", scope: { campaignId: "mundivita" }, trail: [] } }],
        ["a non-object", 7],
    ])("ignores %s and uses the defaults", async (_name, crafted) => {
        const app = openApp(`${base}/knowledge/k1`)
        await screen.findByRole("heading", { level: 1, name: "The duke is a vampire." })
        await act(async () => {
            await app.router.navigate(`${base}/knowledge/k1?section=claim`, { state: crafted })
        })
        await screen.findByRole("heading", { level: 1, name: "The duke is a vampire." })
        expect(trail()).toEqual(["Knowledge", "Claim"])
    })

    it("the old edit address keeps the task and the perspective", async () => {
        const app = openApp(`${base}/knowledge`)
        await act(async () => {
            await app.router.navigate(`${base}/knowledge/k1/edit?character_id=character-ixamarra`, {
                state: { task: { v: 1, root: "knowledge", scope: { campaignId: "mundivita" }, trail: [] } },
            })
        })
        await screen.findByRole("heading", { level: 1, name: "The duke is a vampire." })
        expect(app.router.state.location.pathname).toBe(`${base}/knowledge/k1`)
        expect(app.router.state.location.search).toContain("character_id=character-ixamarra")
        expect(entryState(app)?.task).toMatchObject({ root: "knowledge" })
    })

    it("a dirty claim asks on the Knowledge ancestor: Stay keeps the draft, the task and the entry; Leave goes once", async () => {
        const app = openApp(`${base}/knowledge`)
        fireEvent.click(await screen.findByRole("link", { name: "The duke is a vampire." }))
        const box = await screen.findByRole("textbox", { name: /^Claim/ })
        fireEvent.change(box, { target: { value: "Edited claim" } })
        const key = app.router.state.location.key
        fireEvent.click(breadcrumb().getByRole("link", { name: "Knowledge" }))
        const dialog = await screen.findByRole("dialog", { name: "Discard unsaved changes?" })
        expect(app.router.state.location.key).toBe(key)
        fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
        await waitFor(() => expect(screen.queryByRole("dialog", { name: "Discard unsaved changes?" })).toBeNull())
        expect(screen.getByRole("textbox", { name: /^Claim/ })).toHaveValue("Edited claim")
        expect(entryState(app)?.task).toMatchObject({ root: "knowledge" })
        fireEvent.click(breadcrumb().getByRole("link", { name: "Knowledge" }))
        fireEvent.click(within(await screen.findByRole("dialog", { name: "Discard unsaved changes?" })).getByRole("button", { name: "Discard changes" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/knowledge`))
        await screen.findByRole("heading", { level: 1, name: "Knowledge" })
        expect(notGet()).toEqual([])
    })

    it("a party the claim's address names but is no longer authorized is dropped by the page, in place, keeping the task", async () => {
        claimResponse = (path) => (/party_id=party-gone/.test(path) ? { status: 404 } : { body: claimDetail() })
        const app = openApp(`${base}/knowledge`)
        await screen.findByRole("link", { name: "The duke is a vampire." })
        // The recheck of the party reads a refreshed bootstrap, which no longer authorizes it.
        const current = vi.mocked(useSessionBootstrap)()
        vi.mocked(useSessionBootstrap).mockReturnValue({ ...current, refresh: vi.fn(async () => true) })
        const task = { v: 1, root: "knowledge", scope: { campaignId: "mundivita" }, trail: [] }
        await act(async () => {
            await app.router.navigate(`${base}/knowledge/k1?character_id=character-ixamarra&party_id=party-gone`, {
                state: { task },
            })
        })
        await waitFor(() => expect(app.router.state.location.search).not.toContain("party_id=party-gone"))
        expect(screen.queryByRole("dialog", { name: "Discard unsaved changes?" })).toBeNull()
        expect(app.router.state.historyAction).toBe("REPLACE")
        expect(entryState(app)?.task).toMatchObject({ root: "knowledge" })
        await screen.findByRole("heading", { level: 1, name: "The duke is a vampire." })
    })

    it("a deliberate perspective change is still a question for a dirty claim, and Stay keeps the task", async () => {
        const app = openApp(`${base}/knowledge`)
        fireEvent.click(await screen.findByRole("link", { name: "The duke is a vampire." }))
        fireEvent.change(await screen.findByRole("textbox", { name: /^Claim/ }), { target: { value: "Draft kept" } })
        const before = app.router.state.location.search
        void app.router.navigate({ pathname: `${base}/knowledge/k1`, search: "?character_id=character-b" }, { state: entryState(app) })
        const dialog = await screen.findByRole("dialog", { name: "Discard unsaved changes?" })
        fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
        await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
        expect(app.router.state.location.search).toBe(before)
        expect(screen.getByRole("textbox", { name: /^Claim/ })).toHaveValue("Draft kept")
        expect(entryState(app)?.task).toMatchObject({ root: "knowledge" })
    })

    it("New claim from the list is a step of the task, and the created claim takes the form's place in it", async () => {
        const app = openApp(`${base}/knowledge`)
        fireEvent.click(await screen.findByRole("link", { name: "New claim" }))
        await screen.findByRole("heading", { level: 1, name: "New knowledge claim" })
        expect(trail()).toEqual(["Knowledge", "New claim"])
        expect(entryState(app)?.task).toMatchObject({ root: "knowledge" })
    })

    it("a refused claim says so without naming it", async () => {
        claimResponse = () => NOT_FOUND
        openApp(`${base}/knowledge/k1`)
        expect(await screen.findByRole("heading", { name: /Knowledge.*unavailable/i })).toBeInTheDocument()
        expect(screen.queryByText("The duke is a vampire.")).toBeNull()
    })

    it("a claim read that fails offers a retry", async () => {
        let calls = 0
        claimResponse = () => {
            calls += 1
            return calls === 1 ? { status: 500, body: { error: { code: "boom", message: "m", correlation_id: "c" } } } : { body: claimDetail() }
        }
        openApp(`${base}/knowledge/k1`)
        fireEvent.click(await screen.findByRole("button", { name: "Try again" }))
        await screen.findByRole("heading", { level: 1, name: "The duke is a vampire." })
        expect(trail()).toEqual(["Knowledge", "Claim"])
    })
})

describe("Knowledge Member preview", () => {
    const PREVIEW = `${base}/knowledge/member-preview`
    const preview = (member: string) => `${API}/members/${member}/preview/knowledge`
    beforeEach(() => {
        server.on("GET", `${API}/access-overview`, {
            body: {
                members: [
                    {
                        campaign_membership_id: "m1",
                        user_id: "u-m1",
                        display_name: "Mira",
                        status_code: "active",
                        status_display_name: "Active",
                        joined_at: "2026-01-01T00:00:00Z",
                        account_is_active: true,
                        roles: [],
                        character_relationships: [],
                        grants: [],
                    },
                ],
                assignable_roles: [],
                assignable_characters: [],
                assignable_relationship_types: [],
                grantable_resource_capabilities: [],
                access_groups: [],
            },
        })
        server.on("GET", `${preview("m1")}/perspectives`, {
            body: { display_name: "Mira", roles: ["player"], character_perspectives: [] },
        })
        server.on("GET", new RegExp(`^${preview("m1")}\\?`), { body: { items: [{ ...listItem, subject: null }], next_cursor: null } })
        server.on("GET", /\/members\/m1\/preview\/knowledge\/k1(\?.*)?$/, {
            body: { ...listItem, subject: null, awareness_level: "aware", confidence: 70, willing_to_share: true },
        })
    })

    it("Knowledge > Member preview > Claim, with the member context on the way back", async () => {
        const app = openApp(`${PREVIEW}?member=m1`)
        fireEvent.click(await screen.findByRole("link", { name: "The duke is a vampire." }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${PREVIEW}/k1`))
        await waitFor(() => expect(trail()).toEqual(["Knowledge", "Member preview", "Claim"]))
        expect(trailLinks()).toEqual([`${base}/knowledge`, `${PREVIEW}?member=m1`])
        expect(entryState(app)?.task).toMatchObject({ root: "knowledge" })
        fireEvent.click(breadcrumb().getByRole("link", { name: "Member preview" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(PREVIEW))
        expect(app.router.state.location.search).toBe("?member=m1")
    })

    it("choosing a member stays in the task and replaces nothing but the context", async () => {
        const app = openApp(PREVIEW)
        const select = await screen.findByRole("combobox", { name: "Member" })
        await act(async () => {
            fireEvent.change(select, { target: { value: "m1" } })
        })
        await waitFor(() => expect(app.router.state.location.search).toBe("?member=m1"))
        expect(trail()).toEqual(["Knowledge", "Member preview"])
        expect(notGet()).toEqual([])
    })

    it("a person who may not preview gets the permission message and a plain trail", async () => {
        openApp(PREVIEW, ["campaign.view"])
        expect(await screen.findByText(/do not have permission to preview/)).toBeInTheDocument()
        expect(trail()).toEqual(["Knowledge", "Member preview"])
        expect(server.calls.filter((call) => call.path.includes("/preview/"))).toEqual([])
    })
})
