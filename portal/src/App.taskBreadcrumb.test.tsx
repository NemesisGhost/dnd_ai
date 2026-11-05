import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { bootstrapFor, installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockResponse, MockServer } from "./test/authoringHarness"
import { useSessionBootstrap } from "./hooks/useSessionBootstrap"
import { FULL_RECORD_AUTHORING } from "./test/recordAuthoring"
import { installRecordReads } from "./test/worldWorkspaceMocks"

// P02-2: the shared task breadcrumb on the real Parties and New-character pages, and the Navbar
// starting a task. These run the whole App over a memory data router (jsdom): they prove behavior and
// destinations, not real-browser keyboard, focus, zoom or screen-reader behavior.

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const LIST = "/campaigns/mundivita/parties"
const base = "/app/mundivita"
const NOT_FOUND = {
  status: 404,
  body: { error: { code: "not_found", message: "m", correlation_id: "c" } },
}
const FORBIDDEN = {
  status: 403,
  body: { error: { code: "forbidden", message: "m", correlation_id: "c" } },
}

const party = (id: string, name: string) => ({
  party_id: id,
  name,
  description: null,
  lifecycle_status: "active",
  row_version: 2,
  available_actions: ["update", "archive"],
})

const member = (id: string, name: string) => ({
  party_membership_id: `m-${id}`,
  character_id: id,
  character_name: name,
  joined_at: "Year 1",
  left_at: null,
  joined_reason: null,
  left_reason: null,
  is_current: true,
  period_status: "in_effect",
})

const OPTIONS = {
  can_create: true,
  species: [{ species_id: "sp-human", name: "Human", ruleset_name: "D&D 5e" }],
  sizes: [{ code: "medium", label: "Medium" }],
  limits: { name_max_length: 200, summary_max_length: 4000, text_max_length: 4000, change_note_max_length: 1000 },
}

let server: MockServer

// The page's own content, not the Navbar (which also has Parties, Characters and World links).
const main = () => within(screen.getByRole("main"))
const trail = () =>
  within(screen.getByRole("navigation", { name: "Breadcrumb" }))
    .getAllByRole("listitem")
    .map((item) => item.textContent)
const state = (app: { router: { state: { location: { state: unknown } } } }) =>
  app.router.state.location.state as { task?: { root: string; scope: unknown; trail: Array<{ route: string }> }; ctx?: unknown }

beforeEach(() => {
  server = installCampaignShellMocks()
  server.on("GET", /\/campaigns\/mundivita\/parties(\?.*)?$/, {
    body: { can_create: true, items: [party("p1", "The Company")] },
  })
  server.on("GET", `${LIST}/p1`, { body: party("p1", "The Company") })
  server.on("GET", `${LIST}/p1/members`, {
    body: { as_of: "Year 2", clock_unset: false, party: party("p1", "The Company"), members: [member("c1", "Aldric")] },
  })
  server.on("GET", `${LIST}/p1/roster`, {
    body: {
      party: party("p1", "The Company"),
      member_count: 1,
      members: [{ character_id: "c1", character_name: "Aldric" }],
    },
  })
  server.on("GET", `${LIST}/p1/inventory`, { body: { party_id: "p1", members: [] } })
  server.on("GET", /\/campaigns\/mundivita\/world-times/, { body: { items: [], next_cursor: null } })
  server.on("GET", "/campaigns/mundivita/calendars", { body: { calendars: [] } })
  server.on("GET", /\/campaigns\/mundivita\/characters\/c1/, NOT_FOUND)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("Parties family: the breadcrumb follows the task the person started", () => {
  it("follows the path taken: list > Edit is Parties > Edit, with real links and a marked current page", async () => {
    const app = openApp(`${base}/parties`)
    fireEvent.click(await screen.findByRole("link", { name: "Edit The Company" }))
    await screen.findByRole("heading", { level: 1, name: "Edit party" })
    // The person did not open the party first, so the party is not in the trail (no inferred containment).
    await waitFor(() => expect(trail()).toEqual(["Parties", "Edit"]))

    const nav = screen.getByRole("navigation", { name: "Breadcrumb" })
    expect(within(nav).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual([`${base}/parties`])
    expect(nav.querySelector("[aria-current='page']")?.textContent).toBe("Edit")
    expect(within(nav).queryByRole("link", { name: "Campaign Home" })).toBeNull()
    expect(state(app).task).toMatchObject({ root: "parties", scope: { campaignId: "mundivita" } })
    expect(state(app).task?.trail.map((entry) => entry.route)).toEqual(["parties.list"])

    // Completed navigation: the crumb returns to the list, still the Parties task.
    fireEvent.click(within(nav).getByRole("link", { name: "Parties" }))
    await screen.findByRole("heading", { level: 1, name: "Parties" })
    expect(app.router.state.location.pathname).toBe(`${base}/parties`)
    expect(state(app).task).toMatchObject({ root: "parties", trail: [] })
  })

  it("list > party > a member keeps the Parties task, and Back and Forward restore each entry's trail", async () => {
    const app = openApp(`${base}/parties`)
    fireEvent.click(await screen.findByRole("link", { name: "Members of The Company" }))
    await screen.findByRole("heading", { level: 1, name: "The Company" })
    await waitFor(() => expect(trail()).toEqual(["Parties", "The Company"]))
    fireEvent.click(await screen.findByRole("link", { name: "Aldric" }))
    await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/characters/c1`))
    const forwardState = state(app)
    await act(() => app.router.navigate(-1))
    await screen.findByRole("heading", { level: 1, name: "The Company" })
    await waitFor(() => expect(trail()).toEqual(["Parties", "The Company"]))
    expect(state(app).task?.trail.map((entry) => entry.route)).toEqual(["parties.list"])
    await act(() => app.router.navigate(1))
    await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/characters/c1`))
    expect(state(app).task).toEqual(forwardState.task)
    await act(() => app.router.navigate(-2))
    await screen.findByRole("heading", { level: 1, name: "Parties" })
    expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
  })

  it("gives the defaults after a direct entry, naming the party from the page's own read and nothing else", async () => {
    openApp(`${base}/parties/p1/edit`)
    await screen.findByRole("heading", { level: 1, name: "Edit party" })
    await waitFor(() => expect(trail()).toEqual(["Parties", "The Company", "Edit"]))
    // The name came from the read the page makes anyway: no extra request for a label.
    expect(server.callsTo("GET", `${LIST}/p1`)).toHaveLength(1)
    expect(server.callsTo("GET", `${LIST}/p1/members`)).toHaveLength(0)
  })

  it("shows a generic noun, not a name, when the page's read is refused or missing", async () => {
    server.on("GET", `${LIST}/p1`, NOT_FOUND)
    openApp(`${base}/parties/p1/edit`)
    await screen.findByRole("heading", { level: 1, name: "Edit party" })
    await waitFor(() => expect(trail()).toEqual(["Parties", "Party", "Edit"]))
    expect(screen.queryByText("The Company")).toBeNull()
  })

  it("does not reuse a name after the read that supplied it is refused", async () => {
    server.on("GET", `${LIST}/p1/members`, FORBIDDEN)
    server.on("GET", `${LIST}/p1`, FORBIDDEN)
    openApp(`${base}/parties/p1/edit`)
    await screen.findByRole("heading", { level: 1, name: "Edit party" })
    await waitFor(() => expect(trail()).toEqual(["Parties", "Party", "Edit"]))
  })

  it("shows the roster page for a viewer as Parties > party, with no management controls", async () => {
    openApp(`${base}/parties/p1`, ["campaign.view"])
    await screen.findByRole("heading", { level: 1, name: "The Company" })
    expect(trail()).toEqual(["Parties", "The Company"])
    expect(main().getByRole("link", { name: "Parties" })).toHaveAttribute("href", `${base}/parties`)
    // Roster names stay plain text for viewers (PD-9 waits for the discovery contract).
    expect(main().queryByRole("link", { name: "Aldric" })).toBeNull()
  })

  it("New party and Edit party keep returning to Parties, and the list itself has no breadcrumb", async () => {
    openApp(`${base}/parties`)
    await screen.findByRole("heading", { level: 1, name: "Parties" })
    expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
    fireEvent.click(await screen.findByRole("link", { name: "New party" }))
    await screen.findByRole("heading", { level: 1, name: "New party" })
    expect(trail()).toEqual(["Parties", "New party"])
    expect(main().getByRole("link", { name: "Parties" })).toHaveAttribute("href", `${base}/parties`)
  })

  it("links a member's name on the editors' members page to their record, inside the Parties task", async () => {
    const app = openApp(`${base}/parties`)
    fireEvent.click(await screen.findByRole("link", { name: "Members of The Company" }))
    await screen.findByRole("heading", { level: 1, name: "The Company" })
    const link = await screen.findByRole("link", { name: "Aldric" })
    expect(link).toHaveAttribute("href", `${base}/characters/c1`)
    fireEvent.click(link)
    await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/characters/c1`))
    expect(state(app).task).toMatchObject({ root: "parties", scope: { campaignId: "mundivita" } })
    expect(state(app).task?.trail.map((entry) => entry.route)).toEqual(["parties.list", "parties.detail"])
  })
})

describe("the Navbar starts a task, applied only when the navigation is accepted", () => {
  const navbar = () => within(screen.getByRole("navigation", { name: "Main" }))

  beforeEach(() => {
    server.on("GET", /\/campaigns\/mundivita\/(quests|sessions|knowledge|characters)(\/|\?|$)/, NOT_FOUND)
  })

  it.each([
    ["Parties", `${base}/parties`, "parties"],
    ["Quests", `${base}/quests`, "quests"],
    ["Sessions", `${base}/sessions`, "sessions"],
    // Characters is a split control: its main control opens the selected perspective's record shell.
    ["Characters: open Ixamarra", `${base}/characters/character-ixamarra`, "characters"],
  ])("%s starts a task rooted there, with no trail and no list state", async (name, path, root) => {
    const app = openApp(`${base}/parties/p1/members`.replace("/members", ""))
    await screen.findByRole("heading", { level: 1, name: "The Company" })
    fireEvent.click(navbar().getByRole("link", { name }))
    await waitFor(() => expect(app.router.state.location.pathname).toBe(path))
    expect(state(app).task).toEqual({ v: 1, root, scope: { campaignId: "mundivita" }, trail: [] })
  })

  it("Campaign Home starts a campaign task", async () => {
    const app = openApp(`${base}/parties`)
    await screen.findByRole("heading", { level: 1, name: "Parties" })
    fireEvent.click(navbar().getByRole("link", { name: /^Campaign: open / }))
    await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/home`))
    expect(state(app).task).toMatchObject({ root: "campaign", trail: [] })
  })

  it("a destination outside any campaign or world starts no task", async () => {
    const app = openApp(`${base}/parties`)
    await screen.findByRole("heading", { level: 1, name: "Parties" })
    fireEvent.click(navbar().getByRole("button", { name: "Show world menu" }))
    fireEvent.click(navbar().getByRole("link", { name: "All worlds" }))
    await waitFor(() => expect(app.router.state.location.pathname).toBe("/worlds"))
    expect(state(app)?.task).toBeUndefined()
  })

  it("blocked by unsaved work: Stay changes nothing, Leave starts the new task and keeps the perspective", async () => {
    const app = openApp(`${base}/parties`)
    fireEvent.click(await screen.findByRole("link", { name: "New party" }))
    const name = await screen.findByLabelText(/Name/)
    fireEvent.change(name, { target: { value: "The Crew" } })
    const before = app.router.state.location
    expect(state(app).task).toMatchObject({ root: "parties" })
    expect(state(app).task?.trail.map((entry) => entry.route)).toEqual(["parties.list"])

    fireEvent.click(navbar().getByRole("link", { name: "Quests" }))
    const dialog = await screen.findByRole("dialog", { name: "Discard your changes?" })
    // Nothing has been committed behind the question: same entry, same task, same draft.
    expect(app.router.state.location.key).toBe(before.key)
    expect(app.router.state.location.pathname).toBe(`${base}/parties/new`)
    expect(state(app).task).toMatchObject({ root: "parties" })

    fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Discard your changes?" })).toBeNull())
    expect(app.router.state.location.key).toBe(before.key)
    expect(app.router.state.location.pathname).toBe(`${base}/parties/new`)
    expect(state(app).task).toMatchObject({ root: "parties" })
    expect(state(app).task?.trail.map((entry) => entry.route)).toEqual(["parties.list"])
    expect(screen.getByLabelText(/Name/)).toHaveValue("The Crew")
    expect(trail()).toEqual(["Parties", "New party"])

    fireEvent.click(navbar().getByRole("link", { name: "Quests" }))
    const again = await screen.findByRole("dialog", { name: "Discard your changes?" })
    fireEvent.click(within(again).getByRole("button", { name: "Discard" }))
    await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/quests`))
    expect(state(app).task).toEqual({ v: 1, root: "quests", scope: { campaignId: "mundivita" }, trail: [] })
    // The accepted entry is stamped with the unchanged perspective (P02-0a), beside the new task.
    await waitFor(() => expect(state(app).ctx).toMatchObject({ v: 1, characterId: "character-ixamarra" }))
    expect(state(app).task?.root).toBe("quests")
  })

  it("a breadcrumb link is guarded like any departure, and Stay keeps the draft and the task", async () => {
    const app = openApp(`${base}/parties`)
    fireEvent.click(await screen.findByRole("link", { name: "New party" }))
    fireEvent.change(await screen.findByLabelText(/Name/), { target: { value: "The Crew" } })
    const key = app.router.state.location.key
    fireEvent.click(main().getByRole("link", { name: "Parties" }))
    const dialog = await screen.findByRole("dialog", { name: "Discard your changes?" })
    expect(app.router.state.location.key).toBe(key)
    fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Discard your changes?" })).toBeNull())
    expect(app.router.state.location.pathname).toBe(`${base}/parties/new`)
    expect(screen.getByLabelText(/Name/)).toHaveValue("The Crew")
    expect(state(app).task?.trail.map((entry) => entry.route)).toEqual(["parties.list"])
  })
})

// The label of a party in a breadcrumb belongs to the authority generation under which the read that
// supplied it STARTED. These drive the real Edit party page (it reads the party itself and shows its name
// as an ancestor crumb) with deferred answers while it stays mounted across authority changes.
describe("Parties breadcrumb names: read ownership on the real Edit page", () => {
  const EDIT = `${base}/parties/p1/edit`
  const CAPS = ["access.manage", "canon.edit"]
  let parked: Array<(response: MockResponse) => Promise<void>>

  // An authority change that leaves the page mounted: a refreshed bootstrap with different capabilities
  // (the label authority input), then a query-only REPLACE so the layout re-renders with it.
  async function setAuthority(app: ReturnType<typeof openApp>, extra: string[]) {
    const current = vi.mocked(useSessionBootstrap)()
    vi.mocked(useSessionBootstrap).mockReturnValue({
      ...current,
      state: { status: "authenticated", bootstrap: bootstrapFor([...CAPS, ...extra]) },
    })
    await act(() => app.router.navigate(`${EDIT}?r=${Math.random()}`, { replace: true }))
  }

  const answer = (index: number, name: string) =>
    act(async () => {
      await parked[index]!({ body: party("p1", name) })
    })

  beforeEach(() => {
    parked = []
    server.on("GET", `${LIST}/p1`, () => {
      return new Promise<MockResponse>((resolve) => {
        parked.push(async (response) => resolve(response))
      })
    })
    server.on("POST", `${LIST}/p1/update`, {
      status: 409,
      body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
    })
  })

  const crumbText = () => within(screen.getByRole("navigation", { name: "Breadcrumb" })).getAllByRole("listitem").map((li) => li.textContent)

  // Saving a change gets a stale-write answer; "Load latest version" is the page's own re-read.
  async function reloadLatest() {
    fireEvent.change(await screen.findByLabelText(/Name/), { target: { value: "Edited" } })
    fireEvent.click(screen.getByRole("button", { name: "Save party" }))
    fireEvent.click(await screen.findByRole("button", { name: "Load latest version" }))
    await waitFor(() => expect(parked.length).toBeGreaterThan(1))
  }

  it("an answer to a read started under the old authority never names the party; the page's own re-read under the new one does", async () => {
    const app = openApp(EDIT, CAPS)
    await waitFor(() => expect(parked).toHaveLength(1))
    await setAuthority(app, ["extra.capability"])
    await answer(0, "Old Name")
    await screen.findByLabelText(/Name/)
    expect(crumbText()).toEqual(["Parties", "Party", "Edit"])
    expect(screen.queryByText("Old Name", { selector: "nav *" })).toBeNull()

    await reloadLatest()
    await answer(1, "New Name")
    await waitFor(() => expect(crumbText()).toEqual(["Parties", "New Name", "Edit"]))
    expect(JSON.stringify(app.router.state.location.state ?? null)).not.toContain("Name")
  })

  it("A to B to A: the first generation's answer stays stale", async () => {
    const app = openApp(EDIT, CAPS)
    await waitFor(() => expect(parked).toHaveLength(1))
    await setAuthority(app, ["extra.capability"])
    await setAuthority(app, [])
    await answer(0, "First Generation")
    await screen.findByLabelText(/Name/)
    expect(crumbText()).toEqual(["Parties", "Party", "Edit"])
  })

  it("a refused re-read drops the name, and an older answer cannot bring it back", async () => {
    openApp(EDIT, CAPS)
    await waitFor(() => expect(parked).toHaveLength(1))
    await answer(0, "The Company")
    await waitFor(() => expect(crumbText()).toEqual(["Parties", "The Company", "Edit"]))
    await reloadLatest()
    await act(async () => {
      await parked[1]!({ status: 404, body: { error: { code: "not_found", message: "m", correlation_id: "c" } } })
    })
    await waitFor(() => expect(crumbText()).toEqual(["Parties", "Party", "Edit"]))
    expect(screen.queryByText("The Company")).toBeNull()
  })
})

describe("New-character family", () => {
  beforeEach(() => {
    server.on("GET", "/campaigns/mundivita/authoring/npcs/options", { body: OPTIONS })
    server.on("GET", "/campaigns/mundivita/authoring/player-characters/options", { body: OPTIONS })
  })

  it("direct entry to the chooser gives the Characters default", async () => {
    openApp(`${base}/characters/new`, ["canon.edit"])
    await screen.findByRole("heading", { level: 1, name: "New character" })
    expect(trail()).toEqual(["Characters", "New character"])
    expect(main().getByRole("link", { name: "Characters" })).toHaveAttribute("href", `${base}/characters/all`)
  })

  it("from Characters with filters: Characters > New PC, and the crumb returns to the same filtered view", async () => {
    const FROM = `${base}/characters/all?type=npc&q=mira`
    server.on("GET", /\/campaigns\/mundivita\/characters(\/all)?(\?.*)?$/, { body: { items: [], next_cursor: null } })
    const app = openApp("/app/mundivita/characters/all?type=npc&q=mira")
    fireEvent.click(await screen.findByRole("link", { name: "New PC" }))
    await screen.findByRole("heading", { level: 1, name: "New player character" })
    await waitFor(() => expect(trail()).toEqual(["Characters", "New PC"]))
    expect(main().getByRole("link", { name: "Characters" })).toHaveAttribute("href", FROM)
    expect(state(app).task).toMatchObject({ root: "characters", list: { route: "characters.browse", search: "?type=npc&q=mira" } })
    expect(app.router.state.location.state).not.toHaveProperty("charactersReturn")
    fireEvent.click(main().getByRole("link", { name: "Characters" }))
    await waitFor(() =>
      expect(app.router.state.location.pathname + app.router.state.location.search).toBe(
        "/app/mundivita/characters/all?type=npc&q=mira",
      ),
    )
  })

  it("through the chooser the trail keeps the chooser, and only the task is forwarded", async () => {
    const FROM = `${base}/characters/all?type=npc`
    const app = openApp(`${base}/characters/new`, ["canon.edit"])
    await screen.findByRole("heading", { level: 1, name: "New character" })
    await act(() => app.router.navigate(`${base}/characters/new`, { state: { charactersReturn: FROM } }))
    await waitFor(() => expect(main().getByRole("link", { name: "Characters" })).toHaveAttribute("href", FROM))
    fireEvent.click(main().getByRole("link", { name: "New NPC" }))
    await screen.findByRole("heading", { level: 1, name: "New NPC" })
    await waitFor(() => expect(trail()).toEqual(["Characters", "New character", "New NPC"]))
    expect(app.router.state.location.state).not.toHaveProperty("charactersReturn")
    expect(state(app).task).toMatchObject({ root: "characters" })
    expect(main().getByRole("link", { name: "New character" })).toHaveAttribute("href", `${base}/characters/new`)
  })

  it("after a direct entry the create pages keep their existing World fallback", async () => {
    openApp(`${base}/characters/npc/new`, ["canon.edit"])
    await screen.findByRole("heading", { level: 1, name: "New NPC" })
    expect(main().getByRole("link", { name: "World" })).toHaveAttribute("href", `${base}/world`)
    expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull()
  })

  it("from World People the crumb is World with the same filters; created, the record takes the page's place in the task", async () => {
    server.on("GET", "/campaigns/mundivita/authoring/npcs/n1", {
      body: {
        npc_id: "n1",
        name: "Mira",
        summary: null,
        species: { species_id: "sp-human", name: "Human" },
        size: { code: "medium", label: "Medium" },
        origin: null,
        background: null,
        appearance: null,
        notes: null,
        canon_status: "draft",
        lifecycle_status: "active",
        row_version: 2,
        available_actions: ["update"],
        blocked_actions: [],
        field_locks: [],
      },
    })
    server.on("GET", "/campaigns/mundivita/characters/n1", {
      body: {
        authoring: FULL_RECORD_AUTHORING,
        character_id: "n1",
        name: "Mira",
        character_kind: "npc",
        species_code: "human",
        size_category: "medium",
        current_hit_points: null,
        maximum_hit_points: null,
        temporary_hit_points: null,
        exhaustion_level: null,
        death_save_successes: null,
        death_save_failures: null,
        current_location_id: null,
        active_encounter_id: null,
        conditions: null,
        resources: null,
      },
    })
    server.on("GET", "/campaigns/mundivita/entities/n1/lifecycle", {
      body: {
        entity_id: "n1",
        entity_type_code: "npc",
        canonical_name: "Mira",
        canon_status: "draft",
        lifecycle_status: "active",
        row_version: 2,
        lifecycle_managed: true,
        superseded_by: null,
        available_actions: ["submit_for_review"],
        blocked_actions: [],
      },
    })
    installRecordReads(server, { campaignId: "mundivita", entityId: "n1", entityTypeCode: "npc" })
    server.on("POST", "/campaigns/mundivita/authoring/npcs", {
      body: { npc_id: "n1", row_version: 1, created: true, changed: true },
    })

    const app = openApp("/app/mundivita/world?category=character&q=mira", ["access.manage", "canon.edit"])
    fireEvent.click(await screen.findByRole("link", { name: "New NPC" }))
    await screen.findByRole("heading", { level: 1, name: "New NPC" })
    await waitFor(() => expect(trail()).toEqual(["World", "New NPC"]))
    expect(main().getByRole("link", { name: "World" })).toHaveAttribute(
      "href",
      `${base}/world?category=character&q=mira`,
    )
    const createdFrom = app.router.state.location.key

    fireEvent.change(await screen.findByRole("textbox", { name: /Name/ }), { target: { value: "Mira" } })
    fireEvent.change(screen.getByRole("combobox", { name: /Species/ }), { target: { value: "sp-human" } })
    fireEvent.change(screen.getByRole("combobox", { name: /Size/ }), { target: { value: "medium" } })
    fireEvent.click(screen.getByRole("button", { name: "Create NPC" }))
    await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/world/character/n1`))

    // Replaced, not pushed: the created page took the New NPC entry's place...
    expect(app.router.state.location.key).not.toBe(createdFrom)
    expect(app.router.state.historyAction).toBe("REPLACE")
    // ...with the same root and list state and no "New NPC" page in the trail (the browser the link came
    // from is the first entry, which the crumbs skip as the root's own page); the legacy key still rides.
    expect(state(app).task).toMatchObject({
      root: "world",
      scope: { campaignId: "mundivita" },
      trail: [{ route: "campaign.world", params: { campaignId: "mundivita" } }],
      list: { route: "campaign.world", search: "?category=character&q=mira" },
    })
    expect(app.router.state.location.state).not.toHaveProperty("worldSearch")
    expect(JSON.stringify(app.router.state.location.state)).not.toContain("Mira")
    // Back goes to the page before the create page: exactly one history entry was used.
    await act(() => app.router.navigate(-1))
    expect(app.router.state.location.pathname).toBe(`${base}/world`)
    expect(app.router.state.location.search).toBe("?category=character&q=mira")
  })
})
