import { fireEvent, screen, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"
import { FULL_RECORD_AUTHORING } from "./test/recordAuthoring"
import { installRecordReads } from "./test/worldWorkspaceMocks"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const OPTIONS = {
  can_create: true,
  species: [{ species_id: "sp-human", name: "Human", ruleset_name: "D&D 5e" }],
  sizes: [{ code: "medium", label: "Medium" }],
  limits: {
    name_max_length: 200,
    summary_max_length: 4000,
    text_max_length: 4000,
    change_note_max_length: 1000,
  },
}
const VIEW = {
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
}
const CHARACTER = {
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
}

let server: MockServer

beforeEach(() => {
  server = installCampaignShellMocks()
  server.on("GET", "/campaigns/mundivita/authoring/npcs/options", { body: OPTIONS })
  server.on("GET", "/campaigns/mundivita/authoring/npcs/n1", { body: VIEW })
  server.on("GET", "/campaigns/mundivita/authoring/player-characters/options", { body: OPTIONS })
  // A player-character read is a 404 for an NPC.
  server.on("GET", "/campaigns/mundivita/authoring/player-characters/n1", {
    status: 404,
    body: { error: { code: "not_found", message: "m", correlation_id: "c" } },
  })
  server.on("GET", "/campaigns/mundivita/characters/n1", { body: CHARACTER })
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
  // The editors' workspace also reads the record's revisions, provenance and the world's sources.
  installRecordReads(server, { campaignId: "mundivita", entityId: "n1", entityTypeCode: "npc" })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("NPC authoring routes", () => {
  it.each([
    ["/app/mundivita/characters/npc/new", "New NPC"],
    ["/app/mundivita/characters/n1/edit", "Edit NPC"],
  ])("%s loads directly with one main and one h1", async (path, heading) => {
    openApp(path)
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument()
    expect(screen.getAllByRole("main")).toHaveLength(1)
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
    expect(screen.queryByText(/Unexpected Application Error/i)).toBeNull()
  })

  it("gives an editor the NPC Edit link on a character's workspace, opened at its details", async () => {
    openApp("/app/mundivita/world/character/n1")
    expect(await screen.findByRole("link", { name: "Edit NPC" })).toHaveAttribute(
      "href",
      "/app/mundivita/characters/n1/edit",
    )
    expect(await screen.findByRole("heading", { level: 2, name: "Details" })).toBeInTheDocument()
  })

  it("links the character sheet from a character's workspace instead of embedding it", async () => {
    openApp("/app/mundivita/world/character/n1")
    expect(await screen.findByRole("link", { name: "Open character sheet" })).toHaveAttribute(
      "href",
      "/app/mundivita/characters/n1",
    )
  })

  it("offers the lifecycle steps in the Publication section", async () => {
    openApp("/app/mundivita/world/character/n1?section=publication")
    expect(await screen.findByRole("heading", { level: 2, name: "Publication" })).toBeInTheDocument()
    expect(await screen.findByRole("button", { name: "Submit for review" })).toBeInTheDocument()
  })

  it("gives a player neither and sends no authoring request", async () => {
    openApp("/app/mundivita/world/character/n1", ["campaign.view"])
    await screen.findByRole("heading", { level: 1, name: "Mira" })
    expect(screen.queryByRole("link", { name: "Edit NPC" })).toBeNull()
    expect(screen.queryByRole("heading", { name: "Lifecycle" })).toBeNull()
    expect(server.calls.some((c) => c.path.includes("/authoring/"))).toBe(false)
    expect(server.calls.some((c) => c.path.includes("/lifecycle"))).toBe(false)
  })

  it("offers New NPC in World only when People is selected, to editors only", async () => {
    const editor = openApp("/app/mundivita/world?category=character")
    expect(await screen.findByRole("link", { name: "New NPC" })).toHaveAttribute(
      "href",
      "/app/mundivita/characters/npc/new",
    )
    expect(screen.queryByRole("link", { name: "New character" })).toBeNull()
    editor.unmount()
    const other = openApp("/app/mundivita/world?category=location")
    expect(await screen.findByRole("link", { name: "New location" })).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "New NPC" })).toBeNull()
    other.unmount()
    const all = openApp("/app/mundivita/world")
    expect(await screen.findByRole("link", { name: "New location" })).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "New NPC" })).toBeNull()
    all.unmount()
    openApp("/app/mundivita/world?category=character", ["campaign.view"])
    await screen.findByRole("heading", { level: 1, name: "Campaign World" })
    expect(screen.queryByRole("link", { name: "New NPC" })).toBeNull()
  })

  it("opens NPC creation directly from People, and Cancel and the breadcrumb return to People", async () => {
    const app = openApp("/app/mundivita/world?category=character&q=mira&hidden=1")
    fireEvent.click(await screen.findByRole("link", { name: "New NPC" }))
    expect(await screen.findByRole("heading", { level: 1, name: "New NPC" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "World" })).toHaveAttribute(
      "href",
      "/app/mundivita/world?category=character&q=mira&hidden=1",
    )
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }))
    await screen.findByRole("heading", { level: 1, name: "Campaign World" })
    expect(app.router.state.location.pathname).toBe("/app/mundivita/world")
    expect(app.router.state.location.search).toBe("?category=character&q=mira&hidden=1")
  })

  it("creates the NPC from People and its workspace's Back to World lands on People", async () => {
    server.on("POST", "/campaigns/mundivita/authoring/npcs", {
      body: { npc_id: "n1", row_version: 1, created: true, changed: true },
    })
    openApp("/app/mundivita/world?category=character&q=mira")
    fireEvent.click(await screen.findByRole("link", { name: "New NPC" }))
    fireEvent.change(await screen.findByRole("textbox", { name: /Name/ }), { target: { value: "Mira" } })
    fireEvent.change(screen.getByRole("combobox", { name: /Species/ }), { target: { value: "sp-human" } })
    fireEvent.change(screen.getByRole("combobox", { name: /Size/ }), { target: { value: "medium" } })
    fireEvent.click(screen.getByRole("button", { name: "Create NPC" }))
    await vi.waitFor(() =>
      expect(server.callsTo("POST", "/campaigns/mundivita/authoring/npcs")).toHaveLength(1),
    )
    // Created as an NPC, through the NPC endpoint (never the player-character one).
    expect(server.callsTo("POST", "/campaigns/mundivita/authoring/player-characters")).toHaveLength(0)
    expect(await screen.findByRole("link", { name: /Back to World/ })).toHaveAttribute(
      "href",
      "/app/mundivita/world?category=character&q=mira",
    )
  })

  it("ignores a crafted worldSearch that is not a query string", async () => {
    const app = openApp("/app/mundivita/characters/npc/new")
    await screen.findByRole("heading", { level: 1, name: "New NPC" })
    void app.router.navigate("/app/mundivita/characters/npc/new", {
      state: { worldSearch: "https://evil.example/" },
    })
    await vi.waitFor(() =>
      expect(screen.getByRole("link", { name: "World" })).toHaveAttribute("href", "/app/mundivita/world"),
    )
  })

  it("offers New PC on the Characters page to editors, even with no character selected", async () => {
    const editor = openApp("/app/mundivita/characters")
    expect(await screen.findByRole("link", { name: "New PC" })).toHaveAttribute(
      "href",
      "/app/mundivita/characters/pc/new",
    )
    expect(screen.queryByRole("link", { name: "New character" })).toBeNull()
    expect(screen.queryByRole("link", { name: "New NPC" })).toBeNull()
    editor.unmount()
    openApp("/app/mundivita/characters", ["campaign.view"])
    await screen.findByRole("navigation", { name: "Characters views" })
    expect(screen.queryByRole("link", { name: "New PC" })).toBeNull()
  })

  it("opens player-character creation directly from Characters and returns there with its filters", async () => {
    const app = openApp("/app/mundivita/characters/all?type=npc&q=mi")
    fireEvent.click(await screen.findByRole("link", { name: "New PC" }))
    expect(
      await screen.findByRole("heading", { level: 1, name: "New player character" }),
    ).toBeInTheDocument()
    expect(within(screen.getByRole("main")).getByRole("link", { name: "Characters" })).toHaveAttribute(
      "href",
      "/app/mundivita/characters/all?type=npc&q=mi",
    )
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }))
    await screen.findByRole("navigation", { name: "Characters views" })
    expect(app.router.state.location.pathname).toBe("/app/mundivita/characters/all")
    expect(app.router.state.location.search).toBe("?type=npc&q=mi")
  })

  it("keeps the World breadcrumb on creation pages opened without a Characters or World context", async () => {
    openApp("/app/mundivita/characters/pc/new")
    await screen.findByRole("heading", { level: 1, name: "New player character" })
    expect(screen.getByRole("link", { name: "World" })).toHaveAttribute("href", "/app/mundivita/world")
  })

  it("keeps the direct creation routes subject to the server's permission answer", async () => {
    server.on("GET", "/campaigns/mundivita/authoring/npcs/options", {
      body: { ...OPTIONS, can_create: false },
    })
    openApp("/app/mundivita/characters/npc/new", ["campaign.view"])
    expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/)
  })
})
