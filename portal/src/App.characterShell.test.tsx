import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { RouterProvider, createMemoryRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import App from "./App"
import { RouteSessionProvider } from "./context/RouteSessionProvider"
import { characterSheetFixture } from "./fixtures/characterSheet"
import { useSessionBootstrap } from "./hooks/useSessionBootstrap"
import { SessionRoster } from "./components/sessionRun/SessionRoster"
import { TaskBreadcrumb } from "./components/navigation/TaskBreadcrumb"
import { ThemeProvider } from "./themes/ThemeProvider"
import { bootstrapFor, installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockResponse, MockServer } from "./test/authoringHarness"
import { FULL_RECORD_AUTHORING } from "./test/recordAuthoring"

// P02-6: the character shell. One character record is reached from Characters, Parties, a session
// and World, and the task it was opened in follows it through the record's sections, its other route,
// and its builds, portrayal and edit pages. These run the whole App over a memory data router (jsdom):
// they prove destinations, requests, history and rendered authorized content, not real-browser
// keyboard, focus, zoom or screen-reader behavior.

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
    recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const base = "/app/mundivita"
const API = "/campaigns/mundivita"
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

function character(id: string, name: string, sections: object = FULL, kind = "player_character") {
    return {
        character_id: id,
        name,
        character_kind: kind,
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
        sections,
        authoring: FULL_RECORD_AUTHORING,
    }
}
const INVENTORY = [
    {
        item_instance_id: "i1",
        name: "Longsword",
        display_name: "Longsword",
        quantity: 1,
        condition_percentage: null,
        is_equipped: true,
        is_destroyed: false,
    },
]

let server: MockServer

function installCharacter(id: string, name: string, sections: object = FULL) {
    server.on("GET", `${API}/characters/${id}`, { body: character(id, name, sections) })
    server.on("GET", `${API}/characters/${id}/sheet`, {
        body: { ...characterSheetFixture, character_id: id, name },
    })
    server.on("GET", `${API}/characters/${id}/relationships`, {
        body: { character_id: id, as_of: null, truncated: false, items: [] },
    })
    server.on("GET", `${API}/characters/${id}/inventory`, { body: INVENTORY })
    server.on("GET", `${API}/characters/${id}/parties`, { body: { character_id: id, can_open: true, items: [] } })
}

const party = {
    party_id: "p1",
    name: "The Company",
    description: null,
    lifecycle_status: "active",
    row_version: 2,
    available_actions: ["update", "archive"],
}

beforeEach(() => {
    server = installCampaignShellMocks()
    installCharacter("pc-1", "Aldric")
    server.on("GET", `${API}/parties/p1/members`, {
        body: {
            as_of: "Year 2",
            clock_unset: false,
            party,
            members: [
                {
                    party_membership_id: "m-1",
                    character_id: "pc-1",
                    character_name: "Aldric",
                    joined_at: "Year 1",
                    left_at: null,
                    joined_reason: null,
                    left_reason: null,
                    is_current: true,
                    period_status: "in_effect",
                },
            ],
        },
    })
    server.on("GET", `${API}/parties/p1`, { body: party })
    server.on("GET", `${API}/parties/p1/inventory`, { body: { party_id: "p1", members: [] } })
    server.on("GET", `${API}/parties`, { body: { can_create: true, items: [party] } })
    server.on("GET", /\/campaigns\/mundivita\/world-times/, { body: { items: [], next_cursor: null } })
    server.on("GET", `${API}/calendars`, { body: { calendars: [] } })
})

afterEach(() => {
    vi.unstubAllGlobals()
})

type Opened = ReturnType<typeof openApp>
type EntryState = {
    task?: { root: string; scope: unknown; trail: Array<{ route: string }>; list?: { route: string; search: string } }
    ctx?: unknown
    charactersReturn?: string
    worldSearch?: string
}
const entryState = (app: Pick<Opened, "router">) => app.router.state.location.state as EntryState | null
const breadcrumb = () => within(screen.getByRole("navigation", { name: "Breadcrumb" }))
const trail = () => breadcrumb().getAllByRole("listitem").map((item) => item.textContent)
const trailLinks = () => breadcrumb().getAllByRole("link").map((link) => link.getAttribute("href"))
const sections = () => within(screen.getByRole("navigation", { name: "Character sections" }))
const ready = () => screen.findByRole("navigation", { name: "Character sections" })
const reads = (path: string) => server.calls.filter((call) => call.method === "GET" && call.path === `${API}${path}`)

describe("each supported origin, followed by the record's own sections", () => {
    it("Parties: the GM's members page opens the record in the Parties task, through every section and its other route", async () => {
        const app = openApp(`${base}/parties/p1`)
        fireEvent.click(await screen.findByRole("link", { name: "Aldric" }))
        await ready()
        await waitFor(() => expect(trail()).toEqual(["Parties", "The Company", "Aldric"]))
        expect(trailLinks()).toEqual([`${base}/parties`, `${base}/parties/p1`])
        expect(entryState(app)?.task).toMatchObject({ root: "parties", scope: { campaignId: "mundivita" } })

        // Each section is a history entry of the same task and the same trail; the crumb is unchanged.
        fireEvent.click(sections().getByRole("link", { name: "Inventory" }))
        await screen.findByRole("link", { name: "Longsword" })
        expect(app.router.state.location.search).toBe("?section=inventory")
        expect(entryState(app)?.task).toMatchObject({ root: "parties" })
        expect(entryState(app)?.task?.trail.map((entry) => entry.route)).toEqual(["parties.list", "parties.detail"])
        expect(trail()).toEqual(["Parties", "The Company", "Aldric"])

        fireEvent.click(sections().getByRole("link", { name: "Parties" }))
        await screen.findByRole("heading", { level: 2, name: "Parties" })
        expect(trail()).toEqual(["Parties", "The Company", "Aldric"])

        // "Open in World" is the one explicit new task: World replaces the Parties trail.
        fireEvent.click(screen.getByRole("link", { name: "Open in World" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/world/character/pc-1`))
        expect(entryState(app)?.task).toEqual({ v: 1, root: "world", scope: { campaignId: "mundivita" }, trail: [] })
    })

    it("Parties: Back to the party restores the Parties trail on the entry it came from", async () => {
        const app = openApp(`${base}/parties/p1`)
        fireEvent.click(await screen.findByRole("link", { name: "Aldric" }))
        await ready()
        fireEvent.click(sections().getByRole("link", { name: "Inventory" }))
        await screen.findByRole("link", { name: "Longsword" })
        fireEvent.click(breadcrumb().getByRole("link", { name: "The Company" }))
        await screen.findByRole("heading", { level: 1, name: "The Company" })
        expect(app.router.state.location.pathname).toBe(`${base}/parties/p1`)
        expect(entryState(app)?.task).toMatchObject({ root: "parties" })
        expect(trail()).toEqual(["Parties", "The Company"])
    })

    it("World: a character opened from the World browser keeps World and its list through the sheet and back", async () => {
        const app = openApp(`${base}/world?category=character`, ["campaign.view"], NO_PERSPECTIVE)
        await act(async () => {
            await app.router.navigate(`${base}/world/character/pc-1`, { state: { worldSearch: "?category=character" } })
        })
        await ready()
        expect(trail()).toEqual(["World", "Aldric"])
        expect(trailLinks()).toEqual([`${base}/world?category=character`])
        fireEvent.click(sections().getByRole("link", { name: "Sheet" }))
        await screen.findByRole("heading", { level: 1, name: "Aldric" })
        expect(app.router.state.location.pathname).toBe(`${base}/characters/pc-1`)
        // The World task is kept on the Characters route: it is not turned into a Characters task.
        expect(entryState(app)?.task).toMatchObject({ root: "world" })
        expect(trail()).toEqual(["World", "Aldric"])
        expect(trailLinks()).toEqual([`${base}/world?category=character`])
    })

    it("Session: a participant opened from a session roster keeps Sessions as the task root", async () => {
        const participant = {
            session_participant_id: "sp-1",
            character_id: "pc-1",
            character_name: "Aldric",
            character_kind: "player_character" as const,
            participation_role: "player_character" as const,
            added_at: "2026-01-01T00:00:00Z",
            removed_at: null,
        }
        const router = createMemoryRouter(
            [
                {
                    path: "/app/:campaignId/sessions/:sessionId",
                    element: <SessionRoster campaignId="mundivita" participants={[participant]} />,
                },
                { path: "/app/:campaignId/characters/:characterId", element: <TaskBreadcrumb current="Aldric" /> },
            ],
            { initialEntries: [`${base}/sessions/s1`] },
        )
        render(<RouterProvider router={router} />)
        fireEvent.click(screen.getByRole("link", { name: "Aldric" }))
        await waitFor(() => expect(router.state.location.pathname).toBe(`${base}/characters/pc-1`))
        expect((router.state.location.state as EntryState).task).toMatchObject({
            root: "sessions",
            scope: { campaignId: "mundivita" },
        })
        expect(trail()).toEqual(["Sessions", "Session", "Aldric"])
        expect(trailLinks()).toEqual([`${base}/sessions`, `${base}/sessions/s1`])
    })

    it("Infobox: choosing a perspective opens its record in a new Characters task, at a settled section", async () => {
        installCharacter("character-ixamarra", "Ixamarra")
        const app = openApp(`${base}/quests`, ["campaign.view"])
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/quests`))
        fireEvent.click(screen.getByRole("link", { name: /Ixamarra/ }))
        await ready()
        expect(app.router.state.location.pathname).toBe(`${base}/characters/character-ixamarra`)
        expect(entryState(app)?.task).toMatchObject({ root: "characters" })
    })
})

describe("viewed character versus selected perspective", () => {
    it("viewing another character, through its sections and routes, never changes the selection", async () => {
        const app = openApp(`${base}/characters/pc-1`, ["campaign.view"])
        await ready()
        const selector = screen.getByRole("combobox", { name: "Character perspective" })
        const before = (selector as HTMLSelectElement).value
        const selectedReads = reads("/characters/character-ixamarra").length
        fireEvent.click(sections().getByRole("link", { name: "Inventory" }))
        await screen.findByRole("link", { name: "Longsword" })
        fireEvent.click(sections().getByRole("link", { name: "Details" }))
        await screen.findByRole("heading", { level: 1, name: "Aldric" })
        expect((screen.getByRole("combobox", { name: "Character perspective" }) as HTMLSelectElement).value).toBe(before)
        expect(app.router.state.location.pathname).toBe(`${base}/world/character/pc-1`)
        expect(server.calls.filter((call) => call.method !== "GET")).toEqual([])
        // The record asked for the viewed character only; the Infobox's own read of the selected one is unchanged.
        expect(reads("/characters/character-ixamarra")).toHaveLength(selectedReads)
    })
})

describe("inventory-only access", () => {
    it("reads only the inventory: no character read, no section row, and no link to the record", async () => {
        server.on("GET", `${API}/characters/pc-1`, FORBIDDEN)
        const app = openApp(`${base}/characters/pc-1/inventory`, ["campaign.view"], NO_PERSPECTIVE)
        expect(await screen.findByRole("link", { name: "Longsword" })).toBeInTheDocument()
        expect(reads("/characters/pc-1")).toHaveLength(0)
        expect(reads("/characters/pc-1/sheet")).toHaveLength(0)
        expect(reads("/characters/pc-1/relationships")).toHaveLength(0)
        expect(reads("/characters/pc-1/inventory")).toHaveLength(1)
        expect(screen.queryByRole("navigation", { name: "Character sections" })).toBeNull()
        // The trail is the task's, without an ancestor that would offer the record as if it were theirs.
        expect(trail()).toEqual(["Characters", "Inventory"])
        expect(trailLinks()).toEqual([`${base}/characters/all`])
        expect(breadcrumb().getByText("Inventory")).toHaveAttribute("aria-current", "page")
        expect(app.router.state.location.pathname).toBe(`${base}/characters/pc-1/inventory`)
    })

    it("keeps the origin it was opened in", async () => {
        server.on("GET", `${API}/characters/pc-1`, FORBIDDEN)
        const app = openApp(`${base}/parties/p1`)
        await screen.findByRole("link", { name: "Aldric" })
        // No in-app link leads here (the reader is given the address); an entry carrying a valid task, as a
        // link inside the Parties task would, keeps it.
        const task = { v: 1, root: "parties", scope: { campaignId: "mundivita" }, trail: [{ route: "parties.list", params: { campaignId: "mundivita" } }] }
        await act(async () => {
            await app.router.navigate(`${base}/characters/pc-1/inventory`, { state: { task } })
        })
        await screen.findByRole("link", { name: "Longsword" })
        expect(reads("/characters/pc-1")).toHaveLength(0)
        expect(trail()).toEqual(["Parties", "Inventory"])
    })
})

describe("direct entry, history and malformed task state", () => {
    it("gives the defaults after a direct entry and carries no task into the section links", async () => {
        const app = openApp(`${base}/characters/pc-1`, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        expect(trail()).toEqual(["Characters", "Aldric"])
        expect(trailLinks()).toEqual([`${base}/characters/all`])
        fireEvent.click(sections().getByRole("link", { name: "Inventory" }))
        await screen.findByRole("link", { name: "Longsword" })
        // No evidence of an origin: nothing is invented for the next entry.
        expect(entryState(app)?.task).toBeUndefined()
    })

    it.each([
        ["a task for another campaign", { task: { v: 1, root: "parties", scope: { campaignId: "other" }, trail: [] } }],
        ["an unknown root", { task: { v: 1, root: "nowhere", scope: { campaignId: "mundivita" }, trail: [] } }],
        ["a URL in the trail", { task: { v: 1, root: "parties", scope: { campaignId: "mundivita" }, trail: [{ route: "parties.detail", params: { partyId: "https://evil.example/" } }] } }],
        ["a non-object", "task"],
        ["a crafted charactersReturn", { charactersReturn: "/app/other/characters/all" }],
    ])("ignores %s and uses the defaults", async (_name, crafted) => {
        const app = openApp(`${base}/characters/pc-1`, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        await act(async () => {
            await app.router.navigate(`${base}/characters/pc-1`, { state: crafted })
        })
        await ready()
        expect(trail()).toEqual(["Characters", "Aldric"])
        expect(trailLinks()).toEqual([`${base}/characters/all`])
    })

    it("restores the same trail after a reload of the entry and after Back and Forward", async () => {
        const task = {
            v: 1,
            root: "parties",
            scope: { campaignId: "mundivita" },
            trail: [
                { route: "parties.list", params: { campaignId: "mundivita" } },
                { route: "parties.detail", params: { campaignId: "mundivita", partyId: "p1" } },
            ],
        }
        // A reload: a new router seeded with the entry's state, as the browser restores history.state.
        vi.mocked(useSessionBootstrap).mockReturnValue({
            state: { status: "authenticated", bootstrap: bootstrapFor(["campaign.view"], NO_PERSPECTIVE) },
            reload: vi.fn(),
            refresh: vi.fn(),
        })
        const router = createMemoryRouter(
            [
                {
                    path: "*",
                    element: (
                        <ThemeProvider>
                            <RouteSessionProvider>
                                <App />
                            </RouteSessionProvider>
                        </ThemeProvider>
                    ),
                },
            ],
            { initialEntries: [{ pathname: `${base}/characters/pc-1`, search: "?section=inventory", state: { task } }] },
        )
        render(<RouterProvider router={router} />)
        await screen.findByRole("link", { name: "Longsword" })
        // Names appear only from a read in this tab: the party was not read here, so its noun stands.
        expect(trail()).toEqual(["Parties", "Party", "Aldric"])

        await act(() => router.navigate(`${base}/characters/pc-1?section=relationships`, { state: router.state.location.state }))
        await screen.findByRole("heading", { name: /^Relationships/ })
        await act(() => router.navigate(-1))
        await screen.findByRole("link", { name: "Longsword" })
        expect(trail()).toEqual(["Parties", "Party", "Aldric"])
        await act(() => router.navigate(1))
        await screen.findByRole("heading", { name: /^Relationships/ })
        expect(trail()).toEqual(["Parties", "Party", "Aldric"])
    })

    it("an unknown or withheld ?section= is normalized to the main section with the task kept, by replacing the entry", async () => {
        const app = openApp(`${base}/characters/pc-1`, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        const task = { v: 1, root: "parties", scope: { campaignId: "mundivita" }, trail: [] }
        await act(async () => {
            await app.router.navigate(`${base}/characters/pc-1?section=nonsense`, { state: { task } })
        })
        await waitFor(() => expect(app.router.state.location.search).toBe("?section=sheet"))
        expect(entryState(app)?.task).toMatchObject({ root: "parties" })
        expect(app.router.state.historyAction).toBe("REPLACE")
        expect(sections().getByRole("link", { name: "Sheet" })).toHaveAttribute("aria-current", "page")
        // The normalization replaced the nonsense entry: Back leaves it rather than returning to it.
        await act(() => app.router.navigate(-1))
        expect(app.router.state.location.search).not.toContain("nonsense")
    })
})

describe("breadcrumb names are authorized, owned by the read that supplied them, and dropped on refusal", () => {
    it("names the character in the trail of its builds page from the builds read, and nothing from the URL or history", async () => {
        server.on("GET", `${API}/authoring/characters/pc-1/builds`, {
            body: {
                character: { character_id: "pc-1", name: "Aldric", kind: "player_character" },
                state: { initialized: true, current_hit_points: 9, maximum_hit_points: 12 },
                active_build_id: null,
                builds: [],
            },
        })
        const app = openApp(`${base}/characters/pc-1`)
        await ready()
        fireEvent.click(await screen.findByRole("link", { name: "Builds and starting state" }))
        await screen.findByRole("heading", { level: 1, name: "Builds" })
        await waitFor(() => expect(trail()).toEqual(["Characters", "Aldric", "Builds"]))
        expect(trailLinks()).toEqual([`${base}/characters/all`, `${base}/characters/pc-1`])
        expect(JSON.stringify(entryState(app) ?? null)).not.toContain("Aldric")
        expect(window.location.href).not.toContain("Aldric")
    })

    it("shows the generic noun, not a name, when the character read is refused", async () => {
        server.on("GET", `${API}/characters/pc-1`, NOT_FOUND)
        openApp(`${base}/characters/pc-1`, ["campaign.view"], NO_PERSPECTIVE)
        await screen.findByRole("heading", { name: "Character unavailable" })
        expect(trail()).toEqual(["Characters", "Character"])
    })

    it("a late answer to a read started under the old authority never names the character; a re-read under the new one does", async () => {
        const parked: Array<(response: MockResponse) => void> = []
        server.on("GET", `${API}/characters/pc-1`, () => new Promise<MockResponse>((resolve) => parked.push(resolve)))
        const app = openApp(`${base}/characters/pc-1`, ["campaign.view"], NO_PERSPECTIVE)
        await waitFor(() => expect(parked).toHaveLength(1))
        // The authority changes under the mounted page (a refreshed bootstrap with other capabilities).
        const current = vi.mocked(useSessionBootstrap)()
        vi.mocked(useSessionBootstrap).mockReturnValue({
            ...current,
            state: { status: "authenticated", bootstrap: bootstrapFor(["campaign.view", "extra.capability"], NO_PERSPECTIVE) },
        })
        await act(() => app.router.navigate(`${base}/characters/pc-1?r=1`, { replace: true }))
        await act(async () => {
            parked[0]!({ body: character("pc-1", "Old Name") })
        })
        await ready()
        expect(trail()).toEqual(["Characters", "Character"])
        expect(screen.queryByText("Old Name", { selector: "nav *" })).toBeNull()
    })
})

describe("editors' character pages keep the task and their guards", () => {
    const BUILD_OPTIONS = {
        limits: {
            label_max_length: 200,
            ability_score_min: 1,
            ability_score_max: 30,
            class_level_min: 1,
            class_level_max: 20,
            target_label_max_length: 200,
            max_hit_points: 10000,
        },
        unsupported: [],
        spells: [],
        abilities: [{ id: "ab-str", name: "Strength", code: "strength" }],
        classes: [{ id: "cl-fighter", name: "Fighter", code: "fighter", hit_die: 10 }],
        subclasses: [],
        skills: [],
        proficiency_types: [],
        features: [],
    }
    beforeEach(() => {
        server.on("GET", `${API}/authoring/characters/pc-1/builds`, {
            body: {
                character: { character_id: "pc-1", name: "Aldric", kind: "player_character" },
                state: { initialized: true, current_hit_points: 9, maximum_hit_points: 12 },
                active_build_id: null,
                builds: [],
            },
        })
        server.on("GET", `${API}/authoring/character-build-options`, { body: BUILD_OPTIONS })
    })

    it("Parties > record > builds > New build: the trail grows by one page at a time, and Cancel returns inside the task", async () => {
        const app = openApp(`${base}/parties/p1`)
        fireEvent.click(await screen.findByRole("link", { name: "Aldric" }))
        await ready()
        fireEvent.click(await screen.findByRole("link", { name: "Builds and starting state" }))
        await screen.findByRole("heading", { level: 1, name: "Builds" })
        await waitFor(() => expect(trail()).toEqual(["Parties", "The Company", "Aldric", "Builds"]))
        fireEvent.click(screen.getByRole("link", { name: "New build" }))
        await screen.findByRole("heading", { level: 1, name: "New build" })
        await waitFor(() => expect(trail()).toEqual(["Parties", "The Company", "Aldric", "Builds", "New build"]))
        fireEvent.click(await screen.findByRole("button", { name: "Cancel" }))
        await screen.findByRole("heading", { level: 1, name: "Builds" })
        expect(app.router.state.location.pathname).toBe(`${base}/characters/pc-1/builds`)
        expect(entryState(app)?.task).toMatchObject({ root: "parties" })
        expect(trail()).toEqual(["Parties", "The Company", "Aldric", "Builds"])
    })

    it("a breadcrumb link from a dirty new-build form asks first: Stay keeps the draft and the task, Leave goes", async () => {
        const app = openApp(`${base}/characters/pc-1`)
        await ready()
        fireEvent.click(await screen.findByRole("link", { name: "Builds and starting state" }))
        fireEvent.click(await screen.findByRole("link", { name: "New build" }))
        await screen.findByRole("heading", { level: 1, name: "New build" })
        fireEvent.change(await screen.findByLabelText(/Label/), { target: { value: "Level 3" } })
        const key = app.router.state.location.key
        fireEvent.click(breadcrumb().getByRole("link", { name: "Aldric" }))
        const dialog = await screen.findByRole("dialog", { name: "Discard this new build?" })
        expect(app.router.state.location.key).toBe(key)
        fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
        await waitFor(() => expect(screen.queryByRole("dialog", { name: "Discard this new build?" })).toBeNull())
        expect(app.router.state.location.pathname).toBe(`${base}/characters/pc-1/builds/new`)
        expect(screen.getByLabelText(/Label/)).toHaveValue("Level 3")
        expect(entryState(app)?.task?.trail.map((entry) => entry.route)).toEqual([
            "characters.browse",
            "characters.detail",
            "characters.builds",
        ])

        fireEvent.click(breadcrumb().getByRole("link", { name: "Aldric" }))
        fireEvent.click(await screen.findByRole("button", { name: "Discard" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/characters/pc-1`))
        await ready()
        expect(server.calls.filter((call) => call.method !== "GET")).toEqual([])
    })

    it("Edit opens inside the task and Cancel returns to the record it was opened from", async () => {
        server.on("GET", `${API}/authoring/player-characters/pc-1`, NOT_FOUND)
        server.on("GET", `${API}/authoring/npcs/pc-1`, NOT_FOUND)
        const app = openApp(`${base}/parties/p1`)
        fireEvent.click(await screen.findByRole("link", { name: "Aldric" }))
        await ready()
        fireEvent.click(screen.getByRole("link", { name: "Edit" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/characters/pc-1/edit`))
        expect(entryState(app)?.task).toMatchObject({ root: "parties" })
        await waitFor(() => expect(trail()).toEqual(["Parties", "The Company", "Aldric", "Edit"]))
    })
})

describe("New PC stays discoverable from the selected-character entry point (PD-8 pending)", () => {
    const OPTIONS = {
        can_create: true,
        species: [{ species_id: "sp-human", name: "Human", ruleset_name: "D&D 5e" }],
        sizes: [{ code: "medium", label: "Medium" }],
        limits: { name_max_length: 200, summary_max_length: 4000, text_max_length: 4000, change_note_max_length: 1000 },
    }
    // Character ids are UUIDs; the create pages accept only such a Characters address as a return.
    const UUID = "0f8fad5b-d9cb-469f-a165-0c0b0d6c1b3e"
    const SELECTED = {
        character_perspectives: [{ character_id: UUID, character_name: "Ixamarra", authorized_parties: [] }],
        selected_character_id: UUID,
    }
    beforeEach(() => {
        installCharacter(UUID, "Ixamarra")
        server.on("GET", `${API}/authoring/player-characters/options`, { body: OPTIONS })
    })

    it("/characters redirects to the selected record, which offers New PC to an editor with the record as its return", async () => {
        const app = openApp(`${base}/characters`, ["access.manage", "canon.edit"], SELECTED)
        await ready()
        expect(app.router.state.location.pathname).toBe(`${base}/characters/${UUID}`)
        expect(app.router.state.historyAction).toBe("REPLACE")
        const link = within(screen.getByRole("navigation", { name: "Create character" })).getByRole("link", { name: "New PC" })
        expect(link).toHaveAttribute("href", `${base}/characters/pc/new`)
        // The shared record navigation is unchanged beside it.
        expect(screen.getByRole("navigation", { name: "Character sections" })).toBeInTheDocument()

        fireEvent.click(link)
        await screen.findByRole("heading", { level: 1, name: "New player character" })
        expect(
            (app.router.state.location.state as EntryState).charactersReturn,
        ).toBe(`${base}/characters/${UUID}`)
        // The page's breadcrumb is the Characters task's root; Cancel is what honors the record return.
        expect(within(screen.getByRole("main")).getByRole("link", { name: "Characters" })).toHaveAttribute(
            "href",
            `${base}/characters/all`,
        )
        // Cancel returns to the record it was offered on.
        fireEvent.click(await screen.findByRole("button", { name: "Cancel" }))
        await ready()
        expect(app.router.state.location.pathname).toBe(`${base}/characters/${UUID}`)
        expect(server.calls.filter((call) => call.method !== "GET")).toEqual([])
    })

    it("carries the section the person was on, as a validated return", async () => {
        installCharacter(UUID, "Ixamarra")
        const app = openApp(`${base}/characters/${UUID}?section=inventory`, ["access.manage", "canon.edit"], SELECTED)
        await screen.findByRole("link", { name: "Longsword" })
        fireEvent.click(screen.getByRole("link", { name: "New PC" }))
        await screen.findByRole("heading", { level: 1, name: "New player character" })
        expect((app.router.state.location.state as EntryState).charactersReturn).toBe(
            `${base}/characters/${UUID}?section=inventory`,
        )
    })

    it("is not offered without canon.edit, on the record or after the redirect", async () => {
        openApp(`${base}/characters`, ["campaign.view"], SELECTED)
        await ready()
        expect(screen.queryByRole("navigation", { name: "Create character" })).toBeNull()
        expect(screen.queryByRole("link", { name: "New PC" })).toBeNull()
    })

    it("is still offered on /characters/all", async () => {
        openApp(`${base}/characters/all`)
        expect(await screen.findByRole("link", { name: "New PC" })).toHaveAttribute("href", `${base}/characters/pc/new`)
    })

    it.each([[["campaign.view"]], [["campaign.view", "canon.edit"]]])(
        "the inventory-only page reads only the inventory and offers no create control (%j)",
        async (capabilities) => {
            server.on("GET", `${API}/characters/pc-1`, FORBIDDEN)
            openApp(`${base}/characters/pc-1/inventory`, capabilities, NO_PERSPECTIVE)
            expect(await screen.findByRole("link", { name: "Longsword" })).toBeInTheDocument()
            expect(screen.queryByRole("link", { name: "New PC" })).toBeNull()
            expect(screen.queryByRole("navigation", { name: "Create character" })).toBeNull()
            expect(reads("/characters/pc-1")).toHaveLength(0)
            expect(reads("/characters/pc-1/sheet")).toHaveLength(0)
            expect(reads("/characters/pc-1/inventory")).toHaveLength(1)
        },
    )
})
