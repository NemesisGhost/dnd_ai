import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { useSessionBootstrap } from "./hooks/useSessionBootstrap"
import { bootstrapFor, installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockResponse, MockServer } from "./test/authoringHarness"
import { characterSheetFixture } from "./fixtures/characterSheet"
import { FULL_RECORD_AUTHORING } from "./test/recordAuthoring"

// P02-7a: Sessions and Run. The Sessions task flows through the list, a session, its Run page, the
// encounter pages, an event and a character, and the same shared breadcrumb, validated task and link
// state carry it. These run the whole App over a memory data router (jsdom): they prove destinations,
// requests, history and rendered authorized content, not real-browser keyboard, focus, zoom or
// screen-reader behavior.

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
    recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const base = "/app/mundivita"
const API = "/campaigns/mundivita"
const S = `${API}/sessions/s1`
const NOT_FOUND: MockResponse = {
    status: 404,
    body: { error: { code: "not_found", message: "m", correlation_id: "c" } },
}
const FORBIDDEN: MockResponse = {
    status: 403,
    body: { error: { code: "forbidden", message: "m", correlation_id: "c" } },
}
const NO_PERSPECTIVE = { character_perspectives: [], selected_character_id: null }
const FULL = { details: true, sheet: true, relationships: true, inventory: true, parties: true }
const VIEWER = ["campaign.view"]

const participant = (id: string, characterId: string, name: string, extra: object = {}) => ({
    session_participant_id: id,
    character_id: characterId,
    character_name: name,
    character_kind: "player_character" as const,
    participation_role: "player_character" as const,
    added_at: "2026-10-12T19:00:00Z",
    removed_at: null,
    ...extra,
})

function session(extra: Record<string, unknown> = {}) {
    return {
        session_id: "s1",
        session_number: 1,
        title: "The Hollow Road",
        status_code: "active",
        started_at: "2026-10-12T19:30:00Z",
        ended_at: null,
        summary: "Recap",
        start_world_time_id: null,
        end_world_time_id: null,
        scheduled_for: null,
        play_status: "in_progress",
        row_version: 3,
        available_actions: ["update", "manage_participants", "log", "end", "archive"],
        participants: [participant("sp-1", "c1", "Cael")],
        participant_role_options: { player_character: ["player_character", "guest"], npc: ["npc", "guest"] },
        events: [],
        ...extra,
    }
}
const listItem = (extra: Record<string, unknown> = {}) => {
    const { participants: _participants, events: _events, ...rest } = session(extra)
    void _participants
    void _events
    return rest
}

function character(id: string, name: string) {
    return {
        character_id: id,
        name,
        character_kind: "player_character",
        species_code: "human",
        size_category: "medium",
        current_hit_points: 9,
        maximum_hit_points: 12,
        temporary_hit_points: 0,
        exhaustion_level: 0,
        death_save_successes: 0,
        death_save_failures: 0,
        current_location_id: null,
        active_encounter_id: null,
        conditions: [],
        resources: [],
        sections: FULL,
        authoring: FULL_RECORD_AUTHORING,
    }
}

const TIME = (id: string, display: string) => ({
    world_time_id: id,
    calendar_id: null,
    year: null,
    month_number: null,
    day: null,
    hour: null,
    minute: null,
    label: display,
    precision: "narrative",
    sort_key: 1,
    display,
})

const explanation = {
    event_id: "ev1",
    family: "party_member_joined",
    in_world_time: "Year 1",
    recorded_at: "2026-10-25T03:04:05+00:00",
    subject: { state: "named", kind: "character", entity_id: "c1", name: "Cael", openable: true },
    party: null,
    build_detail: null,
    previous_build: null,
    new_build: null,
    previous_time: null,
    new_time: null,
    advance_origin: null,
    member_explanation: null,
    travel: null,
    session: { session_id: "s1", session_number: 1, title: "The Hollow Road" },
    relations: [],
}
const eventView = {
    event_id: "ev1",
    name: "Cael joined",
    event_type_code: "party_member_joined",
    status: "recorded",
    world_time_id: "t1",
    world_time: "Year 1",
    session_id: "s1",
    details: null,
    participants: [],
    effects: [],
    correction: null,
    corrects_event_id: null,
    explanation,
}
const logged = {
    event_id: "ev1",
    name: "Cael joined",
    summary: null,
    event_type_code: "party_member_joined",
    event_status_code: "recorded",
    world_time_id: "t1",
    details: null,
}

const encounter = (status = "pending") => ({
    encounter_id: "en1",
    session_id: "s1",
    status,
    can_prepare: status === "pending",
    summary: "Ambush",
    location_id: null,
    location_name: null,
    world_time_id: "t1",
    current_round: 0,
    resulting_event_id: null,
    rounds: [],
    participants: [],
})

let server: MockServer
let sessionBody: Record<string, unknown>

beforeEach(() => {
    sessionBody = session()
    server = installCampaignShellMocks()
    server.on("GET", API + "/sessions", () => ({ body: [listItem()] }))
    server.on("GET", S, () => ({ body: sessionBody }))
    server.on("GET", `${API}/clock`, {
        body: { current: { world_time_id: "t1", display: "Year 1" }, row_version: 1, inherited: false, last_event_id: "e1" },
    })
    server.on("GET", /\/campaigns\/mundivita\/world-times/, {
        body: { items: [TIME("t2", "Year 2"), TIME("t1", "Year 1")], next_cursor: null },
    })
    server.on("GET", `${API}/calendars`, { body: { calendars: [] } })
    server.on("GET", `${API}/authoring/encounters?session_id=s1`, () => ({
        body: { items: [{ encounter_id: "en1", status: "pending", summary: "Ambush", location_name: null, participant_count: 0 }] },
    }))
    server.on("GET", `${API}/authoring/encounters/options`, {
        body: {
            action_kinds: [],
            outcomes: [],
            sides: [{ value: "party", label: "Party" }],
            limits: { summary_max_length: 4000, initiative_min: -100, initiative_max: 1000, max_participants: 50 },
        },
    })
    server.on("GET", `${API}/authoring/encounters/en1`, () => ({ body: encounter() }))
    server.on("GET", `${API}/characters/c1`, { body: character("c1", "Cael") })
    server.on("GET", `${API}/characters/c1/sheet`, { body: { ...characterSheetFixture, character_id: "c1", name: "Cael" } })
    server.on("GET", `${API}/characters/c1/inventory`, { body: [] })
    server.on("GET", `${API}/characters/c1/relationships`, {
        body: { character_id: "c1", as_of: null, truncated: false, items: [] },
    })
    server.on("GET", `${API}/characters/c1/parties`, { body: { character_id: "c1", can_open: true, items: [] } })
    server.on("GET", `${API}/events/ev1`, { body: eventView })
    server.on("GET", `${API}/events/ev1/correction-preview`, {
        body: { event_id: "ev1", status: "recorded", can_correct: false, is_correction: false, effects: [] },
    })
})

afterEach(() => {
    vi.unstubAllGlobals()
})

type Opened = ReturnType<typeof openApp>
type EntryState = {
    task?: { root: string; scope: unknown; trail: Array<{ route: string }> }
    ctx?: unknown
    announce?: string
}
const entryState = (app: Pick<Opened, "router">) => app.router.state.location.state as EntryState | null
const breadcrumb = () => within(screen.getByRole("navigation", { name: "Breadcrumb" }))
const trail = () => breadcrumb().getAllByRole("listitem").map((item) => item.textContent)
const trailLinks = () => breadcrumb().getAllByRole("link").map((link) => link.getAttribute("href"))
const reads = (path: string) => server.calls.filter((call) => call.method === "GET" && call.path === `${API}${path}`)
const notGet = () => server.calls.filter((call) => call.method !== "GET")

async function runPage(app: Pick<Opened, "router">) {
    await screen.findByRole("heading", { level: 1, name: "Run: The Hollow Road" })
    await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/sessions/s1/run`))
}

describe("Sessions root, session and Run", () => {
    it("the list is the top of the task, and a session opened from it is a step of it", async () => {
        const app = openApp(`${base}/sessions`)
        fireEvent.click(await screen.findByRole("link", { name: "The Hollow Road" }))
        await screen.findByRole("heading", { level: 1, name: "The Hollow Road" })
        expect(entryState(app)?.task).toMatchObject({ root: "sessions", scope: { campaignId: "mundivita" } })
        expect(trail()).toEqual(["Sessions", "The Hollow Road"])
        expect(trailLinks()).toEqual([`${base}/sessions`])
        // The current page is text with aria-current, never a link.
        expect(breadcrumb().getByText("The Hollow Road")).toHaveAttribute("aria-current", "page")
        // Ancestors carry the task cut back to them: the root's own page is still the top of the task.
        fireEvent.click(breadcrumb().getByRole("link", { name: "Sessions" }))
        await screen.findByRole("heading", { level: 1, name: "Sessions" })
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
        expect(entryState(app)?.task).toMatchObject({ root: "sessions", trail: [] })
    })

    it("Run is a step under the session: from the session, and from the list's own Run link", async () => {
        const app = openApp(`${base}/sessions/s1`)
        fireEvent.click(await screen.findByRole("link", { name: "Change participants in Run session" }))
        await runPage(app)
        expect(trail()).toEqual(["Sessions", "The Hollow Road", "Run session"])
        expect(trailLinks()).toEqual([`${base}/sessions`, `${base}/sessions/s1`])
        expect(breadcrumb().getByText("Run session")).toHaveAttribute("aria-current", "page")
        expect(breadcrumb().queryByRole("link", { name: "Run session" })).toBeNull()
        expect(JSON.stringify(entryState(app))).not.toContain("Hollow")

        // The list skips the session, but Run keeps its documented parent.
        await act(async () => {
            await app.router.navigate(`${base}/sessions`)
        })
        fireEvent.click(await screen.findByRole("link", { name: "Run The Hollow Road" }))
        await runPage(app)
        expect(trail()).toEqual(["Sessions", "The Hollow Road", "Run session"])
        expect(entryState(app)?.task?.trail.map((entry) => entry.route)).toEqual(["sessions.list", "sessions.detail"])
    })

    it("a breadcrumb ancestor goes to the session with the task cut back, and the Run page's sections keep the task", async () => {
        const app = openApp(`${base}/sessions/s1`)
        fireEvent.click(await screen.findByRole("link", { name: "Change participants in Run session" }))
        await runPage(app)
        const runKey = app.router.state.location.key
        fireEvent.click(screen.getByRole("link", { name: /2\. Run session/ }))
        await waitFor(() => expect(app.router.state.location.search).toBe("?section=log"))
        expect(app.router.state.location.key).not.toBe(runKey)
        expect(entryState(app)?.task?.trail.map((entry) => entry.route)).toEqual(["sessions.list", "sessions.detail"])
        expect(trail()).toEqual(["Sessions", "The Hollow Road", "Run session"])
        fireEvent.click(screen.getByRole("link", { name: /3\. Wrap up/ }))
        await waitFor(() => expect(app.router.state.location.search).toBe("?section=review"))
        expect(trail()).toEqual(["Sessions", "The Hollow Road", "Run session"])

        fireEvent.click(breadcrumb().getByRole("link", { name: "The Hollow Road" }))
        await screen.findByRole("heading", { level: 1, name: "The Hollow Road" })
        expect(app.router.state.location.pathname).toBe(`${base}/sessions/s1`)
        expect(trail()).toEqual(["Sessions", "The Hollow Road"])
        expect(notGet()).toEqual([])
    })

    it("a direct entry gets the documented hierarchy, and sections added to the address keep it", async () => {
        const app = openApp(`${base}/sessions/s1/run`)
        await runPage(app)
        await waitFor(() => expect(app.router.state.location.search).toBe("?section=log"))
        expect(trail()).toEqual(["Sessions", "The Hollow Road", "Run session"])
        expect(trailLinks()).toEqual([`${base}/sessions`, `${base}/sessions/s1`])
        // No evidence of an origin: nothing is invented for the next entry.
        fireEvent.click(screen.getByRole("link", { name: /Travel/ }))
        expect(entryState(app)?.task).toBeUndefined()
    })

    it.each([
        ["a task for another campaign", { task: { v: 1, root: "sessions", scope: { campaignId: "other" }, trail: [] } }],
        ["a root the route does not allow", { task: { v: 1, root: "access", scope: { campaignId: "mundivita" }, trail: [] } }],
        ["an unknown root", { task: { v: 1, root: "nowhere", scope: { campaignId: "mundivita" }, trail: [] } }],
        [
            "a URL in the trail",
            { task: { v: 1, root: "sessions", scope: { campaignId: "mundivita" }, trail: [{ route: "sessions.detail", params: { sessionId: "https://evil.example/" } }] } },
        ],
        ["a non-object", "task"],
    ])("ignores %s and uses the defaults", async (_name, crafted) => {
        const app = openApp(`${base}/sessions/s1/run`)
        await runPage(app)
        await act(async () => {
            await app.router.navigate(`${base}/sessions/s1/run?section=log`, { state: crafted })
        })
        await runPage(app)
        expect(trail()).toEqual(["Sessions", "The Hollow Road", "Run session"])
        expect(trailLinks()).toEqual([`${base}/sessions`, `${base}/sessions/s1`])
    })

    it("restores the trail on Back and Forward", async () => {
        const app = openApp(`${base}/sessions/s1`)
        fireEvent.click(await screen.findByRole("link", { name: "Change participants in Run session" }))
        await runPage(app)
        fireEvent.click(breadcrumb().getByRole("link", { name: "The Hollow Road" }))
        await screen.findByRole("heading", { level: 1, name: "The Hollow Road" })
        await act(async () => {
            await app.router.navigate(-1)
        })
        await runPage(app)
        expect(trail()).toEqual(["Sessions", "The Hollow Road", "Run session"])
        expect(entryState(app)?.task).toMatchObject({ root: "sessions" })
    })
})

describe("a character opened from a session", () => {
    it("Run > Cael keeps the Sessions task through the record's sections and its other route", async () => {
        const app = openApp(`${base}/sessions/s1`)
        fireEvent.click(await screen.findByRole("link", { name: "Change participants in Run session" }))
        await runPage(app)
        const selector = screen.getByRole("combobox", { name: "Character perspective" }) as HTMLSelectElement
        const before = selector.value
        const selectedReads = reads("/characters/character-ixamarra").length
        fireEvent.click(await screen.findByRole("link", { name: "Cael" }))
        await screen.findByRole("navigation", { name: "Character sections" })
        await waitFor(() => expect(trail()).toEqual(["Sessions", "The Hollow Road", "Run session", "Cael"]))
        expect(trailLinks()).toEqual([`${base}/sessions`, `${base}/sessions/s1`, `${base}/sessions/s1/run`])
        expect(entryState(app)?.task).toMatchObject({ root: "sessions", scope: { campaignId: "mundivita" } })

        const sections = within(screen.getByRole("navigation", { name: "Character sections" }))
        fireEvent.click(sections.getByRole("link", { name: "Inventory" }))
        await waitFor(() => expect(app.router.state.location.search).toBe("?section=inventory"))
        expect(entryState(app)?.task).toMatchObject({ root: "sessions" })
        expect(trail()).toEqual(["Sessions", "The Hollow Road", "Run session", "Cael"])
        // Viewing a linked character never changes the selected perspective, and reads nothing for it.
        expect((screen.getByRole("combobox", { name: "Character perspective" }) as HTMLSelectElement).value).toBe(before)
        expect(reads("/characters/character-ixamarra")).toHaveLength(selectedReads)
        expect(notGet()).toEqual([])

        // The Run ancestor returns to the Run page, still in the task.
        fireEvent.click(breadcrumb().getByRole("link", { name: "Run session" }))
        await runPage(app)
        expect(trail()).toEqual(["Sessions", "The Hollow Road", "Run session"])
    })

    it("names the session in the trail only from a session read, never in history or the address", async () => {
        const app = openApp(`${base}/sessions/s1/run?section=participants`, ["access.manage", "canon.edit"], NO_PERSPECTIVE)
        await runPage(app)
        fireEvent.click(await screen.findByRole("link", { name: "Cael" }))
        await waitFor(() => expect(trail()).toEqual(["Sessions", "The Hollow Road", "Run session", "Cael"]))
        expect(JSON.stringify(entryState(app))).not.toContain("Hollow")
        expect(window.location.href).not.toContain("Hollow")
    })

    it("a member sees the roster their session read allows and no Run control", async () => {
        sessionBody = session({
            available_actions: undefined,
            participants: [
                participant("sp-1", "c1", "Cael", { can_open_character: true }),
                participant("sp-2", "c2", "Ghost", { can_open_character: false }),
            ],
        })
        server.on("GET", API + "/sessions", { body: [listItem({ available_actions: null })] })
        const app = openApp(`${base}/sessions`, VIEWER, NO_PERSPECTIVE)
        expect(screen.queryByRole("link", { name: /^Run / })).toBeNull()
        fireEvent.click(await screen.findByRole("link", { name: "The Hollow Road" }))
        await screen.findByRole("heading", { level: 1, name: "The Hollow Road" })
        expect(screen.queryByRole("link", { name: /Run session/ })).toBeNull()
        expect(screen.queryByRole("link", { name: "Ghost" })).toBeNull()
        expect(screen.getByText(/Ghost/)).toBeInTheDocument()
        fireEvent.click(screen.getByRole("link", { name: "Cael" }))
        await screen.findByRole("navigation", { name: "Character sections" })
        await waitFor(() => expect(trail()).toEqual(["Sessions", "The Hollow Road", "Cael"]))
        expect(entryState(app)?.task).toMatchObject({ root: "sessions" })
        // Only what the member's own pages read: the list, the session and the viewed character.
        const paths = server.calls.filter((call) => call.method === "GET").map((call) => call.path)
        expect(paths.filter((path) => path.includes("/characters/") && !path.includes("/characters/c1"))).toEqual([])
        expect(paths.filter((path) => path.includes("/authoring/"))).toEqual([])
        expect(paths.filter((path) => path.includes("/events/"))).toEqual([])
    })

    it("a member on the Run address gets the permission message and a trail that discloses nothing more", async () => {
        sessionBody = session({ available_actions: undefined })
        openApp(`${base}/sessions/s1/run`, VIEWER, NO_PERSPECTIVE)
        expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission to run sessions/)
        // The name arrives with the member's own (member-shaped) session read; nothing else is asked.
        await waitFor(() => expect(trail()).toEqual(["Sessions", "The Hollow Road", "Run session"]))
        expect(server.calls.filter((call) => call.path.includes("/authoring/"))).toEqual([])
    })
})

describe("events opened from a session", () => {
    it("the log's event opens in the Sessions task, with its character, session and return links inside it", async () => {
        sessionBody = session({ events: [logged], explanations: [explanation] })
        const app = openApp(`${base}/sessions/s1/run?section=review`)
        await runPage(app)
        const reviewLog = within(await screen.findByRole("list", { name: "Recorded entries" }))
        fireEvent.click(reviewLog.getByRole("link", { name: "Cael joined" }))
        await screen.findByRole("heading", { level: 1, name: "Cael joined" })
        await waitFor(() => expect(trail()).toEqual(["Sessions", "The Hollow Road", "Run session", "Cael joined"]))
        expect(trailLinks()).toEqual([`${base}/sessions`, `${base}/sessions/s1`, `${base}/sessions/s1/run`])
        expect(entryState(app)?.task).toMatchObject({ root: "sessions" })

        // The explanation's character link is a step of the same task.
        fireEvent.click(await screen.findByRole("link", { name: "Cael" }))
        await screen.findByRole("navigation", { name: "Character sections" })
        expect(app.router.state.location.pathname).toBe(`${base}/characters/c1`)
        expect(entryState(app)?.task).toMatchObject({ root: "sessions" })
        await waitFor(() => expect(trail()[0]).toBe("Sessions"))
        expect(trail().at(-1)).toBe("Cael")
        expect(trail()).toContain("Cael joined")

        // Back to the event and then to the session it belongs to, still inside the task.
        fireEvent.click(breadcrumb().getByRole("link", { name: "Cael joined" }))
        await screen.findByRole("heading", { level: 1, name: "Cael joined" })
        fireEvent.click(screen.getByRole("link", { name: "its session" }))
        await screen.findByRole("heading", { level: 1, name: "The Hollow Road" })
        expect(entryState(app)?.task).toMatchObject({ root: "sessions" })
        expect(trail()[0]).toBe("Sessions")
        expect(notGet()).toEqual([])
    })

    it("the Run page's plain log entry link also carries the task", async () => {
        sessionBody = session({ events: [{ ...logged, event_type_code: "session_narrative" }], explanations: [] })
        const app = openApp(`${base}/sessions/s1/run?section=log`)
        await runPage(app)
        const log = within(await screen.findByRole("list", { name: "Session log" }))
        fireEvent.click(log.getByRole("link", { name: "Cael joined" }))
        await screen.findByRole("heading", { level: 1, name: "Cael joined" })
        expect(entryState(app)?.task).toMatchObject({ root: "sessions" })
    })

    it("a direct entry keeps the page's own Campaign Home link and gives its links no invented origin", async () => {
        const app = openApp(`${base}/events/ev1`)
        await screen.findByRole("heading", { level: 1, name: "Cael joined" })
        expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
        expect(screen.getByRole("link", { name: "Campaign Home" })).toHaveAttribute("href", base)
        fireEvent.click(screen.getByRole("link", { name: "its session" }))
        await screen.findByRole("heading", { level: 1, name: "The Hollow Road" })
        expect(entryState(app)?.task).toBeUndefined()
        expect(trail()).toEqual(["Sessions", "The Hollow Road"])
    })

    it.each([
        ["not found", NOT_FOUND],
        ["forbidden", FORBIDDEN],
    ])("an event that is %s says so without a trail or a name", async (_name, response) => {
        server.on("GET", `${API}/events/ev1`, response)
        server.on("GET", `${API}/events/ev1/correction-preview`, response)
        openApp(`${base}/events/ev1`)
        await screen.findByRole("heading", { level: 1, name: "Event" })
        expect(await screen.findByRole("alert")).toBeInTheDocument()
        expect(screen.queryByText("Cael joined")).toBeNull()
    })
})

describe("encounters and the Run page", () => {
    it("Run > encounter keeps the task, returns to the stage it belongs to, and Prepare replaces the form with the encounter", async () => {
        const app = openApp(`${base}/sessions/s1/run?section=encounter-prep`)
        await runPage(app)
        fireEvent.click(await screen.findByRole("link", { name: /Ambush/ }))
        await screen.findByRole("heading", { level: 1, name: "Encounter" })
        expect(app.router.state.location.pathname).toBe(`${base}/sessions/s1/encounters/en1`)
        expect(entryState(app)?.task).toMatchObject({ root: "sessions" })
        await waitFor(() => expect(trail()).toEqual(["Sessions", "The Hollow Road", "Run session", "Encounter"]))
        expect(breadcrumb().getByRole("link", { name: "Run session" })).toHaveAttribute(
            "href",
            `${base}/sessions/s1/run?section=encounter-prep`,
        )

        fireEvent.click(breadcrumb().getByRole("link", { name: "Run session" }))
        await runPage(app)
        expect(app.router.state.location.search).toBe("?section=encounter-prep")
        fireEvent.click(await screen.findByRole("link", { name: "Prepare an encounter" }))
        await screen.findByRole("heading", { level: 1, name: "Prepare an encounter" })
        expect(trail()).toEqual(["Sessions", "The Hollow Road", "Run session", "Prepare an encounter"])
    })

    it("a prepared encounter replaces the form in the same task, as one history entry", async () => {
        server.on("GET", `${API}/authoring/encounters/en2`, () => ({ body: { ...encounter(), encounter_id: "en2" } }))
        server.on("POST", `${API}/encounters/prepare`, { status: 201, body: { ...encounter(), encounter_id: "en2" } })
        const app = openApp(`${base}/sessions/s1/run?section=encounter-prep`)
        await runPage(app)
        fireEvent.click(await screen.findByRole("link", { name: "Prepare an encounter" }))
        const form = await screen.findByRole("form", { name: "Prepare an encounter" })
        const length = window.history.length
        fireEvent.click(within(form).getByRole("button", { name: "Prepare encounter" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/sessions/s1/encounters/en2`))
        expect(window.history.length).toBe(length)
        expect(entryState(app)?.task).toMatchObject({ root: "sessions" })
        await waitFor(() => expect(trail()).toEqual(["Sessions", "The Hollow Road", "Run session", "Encounter"]))
        expect(server.callsTo("POST", /./)).toHaveLength(1)
    })

    it("a direct entry to an encounter gets Sessions > session > Run session > Encounter, back to its stage", async () => {
        openApp(`${base}/sessions/s1/encounters/en1`)
        await screen.findByRole("heading", { level: 1, name: "Encounter" })
        await waitFor(() => expect(trail()).toEqual(["Sessions", "The Hollow Road", "Run session", "Encounter"]))
        expect(trailLinks()).toEqual([
            `${base}/sessions`,
            `${base}/sessions/s1`,
            `${base}/sessions/s1/run?section=encounter-prep`,
        ])
    })
})

describe("loading, unavailable and error states", () => {
    it("the session page is non-disclosing when the session is refused, and a late answer fills nothing", async () => {
        server.on("GET", S, NOT_FOUND)
        openApp(`${base}/sessions/s1`)
        expect(await screen.findByRole("heading", { name: "Session unavailable" })).toBeInTheDocument()
        expect(screen.queryByText("The Hollow Road")).toBeNull()
    })

    it("an error shows a retry, and a successful retry shows the trail with the name", async () => {
        let calls = 0
        server.on("GET", S, () => {
            calls += 1
            return calls === 1 ? { status: 500, body: { error: { code: "boom", message: "m", correlation_id: "c" } } } : { body: sessionBody }
        })
        openApp(`${base}/sessions/s1`)
        fireEvent.click(await screen.findByRole("button", { name: "Try again" }))
        await screen.findByRole("heading", { level: 1, name: "The Hollow Road" })
        expect(trail()).toEqual(["Sessions", "The Hollow Road"])
    })

    it("the Run page keeps the generic noun in its trail while the session is loading, unavailable or forbidden", async () => {
        const parked: Array<(response: MockResponse) => void> = []
        server.on("GET", S, () => new Promise<MockResponse>((resolve) => parked.push(resolve)))
        openApp(`${base}/sessions/s1/run`)
        await waitFor(() => expect(parked.length).toBeGreaterThan(0))
        expect(screen.getByRole("status")).toHaveTextContent("Loading session")
        expect(trail()).toEqual(["Sessions", "Session", "Run session"])
        await act(async () => {
            parked.forEach((resolve) => resolve(FORBIDDEN))
        })
        expect(await screen.findByRole("alert")).toBeInTheDocument()
        expect(trail()).toEqual(["Sessions", "Session", "Run session"])
    })
})

describe("authority changes under a mounted page", () => {
    it("a late answer to a read started under the old authority never names the session; a re-read under the new one does", async () => {
        const parked: Array<(response: MockResponse) => void> = []
        server.on("GET", S, () => new Promise<MockResponse>((resolve) => parked.push(resolve)))
        const app = openApp(`${base}/sessions/s1/run`, ["access.manage", "canon.edit"], NO_PERSPECTIVE)
        await waitFor(() => expect(parked).toHaveLength(1))
        // The authority changes under the mounted page (a refreshed bootstrap with other capabilities).
        const current = vi.mocked(useSessionBootstrap)()
        vi.mocked(useSessionBootstrap).mockReturnValue({
            ...current,
            state: {
                status: "authenticated",
                bootstrap: bootstrapFor(["access.manage", "canon.edit", "extra.capability"], NO_PERSPECTIVE),
            },
        })
        await act(() => app.router.navigate(`${base}/sessions/s1/run?r=1`, { replace: true }))
        await act(async () => {
            parked[0]!({ body: session({ title: "Old Name" }) })
        })
        await screen.findByRole("heading", { level: 1 })
        expect(trail()).toEqual(["Sessions", "Session", "Run session"])
        expect(screen.queryByText("Old Name", { selector: "nav *" })).toBeNull()
    })

    it("permission loss drops the Run controls and keeps the page's non-disclosing state", async () => {
        const app = openApp(`${base}/sessions/s1/run`, ["access.manage", "canon.edit"], NO_PERSPECTIVE)
        await runPage(app)
        const current = vi.mocked(useSessionBootstrap)()
        vi.mocked(useSessionBootstrap).mockReturnValue({
            ...current,
            state: { status: "authenticated", bootstrap: bootstrapFor(VIEWER, NO_PERSPECTIVE) },
        })
        await act(() => app.router.navigate(`${base}/sessions/s1/run?section=log`, { replace: true }))
        expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission to run sessions/)
        expect(notGet()).toEqual([])
    })
})

describe("guards on the session page", () => {
    it("a breadcrumb link from a dirty session asks first: Stay keeps the draft and the task, Leave goes without a write", async () => {
        const app = openApp(`${base}/sessions`)
        fireEvent.click(await screen.findByRole("link", { name: "The Hollow Road" }))
        const title = await screen.findByLabelText("Title")
        fireEvent.change(title, { target: { value: "Draft" } })
        const key = app.router.state.location.key
        fireEvent.click(breadcrumb().getByRole("link", { name: "Sessions" }))
        const dialog = await screen.findByRole("dialog", { name: "Discard your changes?" })
        expect(app.router.state.location.key).toBe(key)
        fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
        await waitFor(() => expect(screen.queryByRole("dialog", { name: "Discard your changes?" })).toBeNull())
        expect(screen.getByLabelText("Title")).toHaveValue("Draft")
        expect(app.router.state.location.pathname).toBe(`${base}/sessions/s1`)
        expect(entryState(app)?.task).toMatchObject({ root: "sessions" })
        expect(trail()).toEqual(["Sessions", "The Hollow Road"])

        fireEvent.click(breadcrumb().getByRole("link", { name: "Sessions" }))
        fireEvent.click(within(await screen.findByRole("dialog", { name: "Discard your changes?" })).getByRole("button", { name: "Discard" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/sessions`))
        await screen.findByRole("heading", { level: 1, name: "Sessions" })
        expect(notGet()).toEqual([])
    })

    it("Run from a dirty session is the same question, and the draft is only held while it stands", async () => {
        const app = openApp(`${base}/sessions/s1`)
        fireEvent.change(await screen.findByLabelText("Title"), { target: { value: "Draft" } })
        fireEvent.click(screen.getByRole("link", { name: "Change participants in Run session" }))
        const dialog = await screen.findByRole("dialog", { name: "Discard your changes?" })
        fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
        expect(app.router.state.location.pathname).toBe(`${base}/sessions/s1`)
        expect(screen.getByLabelText("Title")).toHaveValue("Draft")
        fireEvent.click(screen.getByRole("link", { name: "Change participants in Run session" }))
        fireEvent.click(within(await screen.findByRole("dialog", { name: "Discard your changes?" })).getByRole("button", { name: "Discard" }))
        await runPage(app)
        expect(trail()).toEqual(["Sessions", "The Hollow Road", "Run session"])
        expect(notGet()).toEqual([])
    })

    it("Schedule a session: Cancel returns to the list inside the task and a save replaces the form once", async () => {
        server.on("POST", API + "/sessions", { status: 201, body: { session_id: "s2", row_version: 1, changed: true } })
        const app = openApp(`${base}/sessions`)
        fireEvent.click(await screen.findByRole("link", { name: "Schedule a session" }))
        await screen.findByRole("heading", { level: 1, name: "Schedule a session" })
        expect(trail()).toEqual(["Sessions", "Schedule a session"])
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        await screen.findByRole("heading", { level: 1, name: "Sessions" })
        expect(app.router.state.location.pathname).toBe(`${base}/sessions`)
        expect(entryState(app)?.task).toMatchObject({ root: "sessions", trail: [] })

        fireEvent.click(await screen.findByRole("link", { name: "Schedule a session" }))
        fireEvent.change(await screen.findByLabelText("Title"), { target: { value: "Next" } })
        fireEvent.click(screen.getByRole("button", { name: "Schedule session" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/sessions`))
        expect(entryState(app)?.task).toMatchObject({ root: "sessions" })
        expect(entryState(app)?.announce).toBe("Session scheduled")
        expect(server.callsTo("POST", API + "/sessions")).toHaveLength(1)
    })
})
