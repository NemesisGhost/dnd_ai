import { screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"

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
const view = (canon: string) => ({
  player_character_id: "p1",
  name: "Aldric",
  summary: null,
  species: { species_id: "sp-human", name: "Human" },
  size: { code: "medium", label: "Medium" },
  origin: null,
  background: null,
  appearance: null,
  notes: null,
  canon_status: canon,
  lifecycle_status: "active",
  row_version: 2,
  available_actions: ["update"],
  blocked_actions: [],
  field_locks: [],
})
const CHARACTER = {
  character_id: "p1",
  name: "Aldric",
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
const NOT_FOUND = {
  status: 404,
  body: { error: { code: "not_found", message: "m", correlation_id: "c" } },
}

let server: MockServer

function mock(canon: string) {
  server = installCampaignShellMocks()
  server.on("GET", "/campaigns/mundivita/authoring/player-characters/options", { body: OPTIONS })
  server.on("GET", "/campaigns/mundivita/authoring/player-characters/p1", { body: view(canon) })
  // An NPC read is a 404 for a player character.
  server.on("GET", "/campaigns/mundivita/authoring/npcs/p1", NOT_FOUND)
  server.on("GET", "/campaigns/mundivita/characters/p1", { body: CHARACTER })
  server.on("GET", "/campaigns/mundivita/entities/p1/lifecycle", {
    body: {
      entity_id: "p1",
      entity_type_code: "player_character",
      canonical_name: "Aldric",
      canon_status: canon,
      lifecycle_status: "active",
      row_version: 2,
      lifecycle_managed: true,
      superseded_by: null,
      available_actions: [],
      blocked_actions: [],
    },
  })
}

beforeEach(() => mock("draft"))

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("player-character authoring routes", () => {
  it.each([
    ["/app/mundivita/characters/new", "New character"],
    ["/app/mundivita/characters/pc/new", "New player character"],
    ["/app/mundivita/characters/p1/edit", "Edit player character"],
  ])("%s loads directly with one main and one h1", async (path, heading) => {
    openApp(path)
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument()
    expect(screen.getAllByRole("main")).toHaveLength(1)
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
  })

  it("makes the author choose the kind explicitly", async () => {
    openApp("/app/mundivita/characters/new")
    expect(await screen.findByRole("link", { name: "New NPC" })).toHaveAttribute(
      "href",
      "/app/mundivita/characters/npc/new",
    )
    expect(screen.getByRole("link", { name: "New player character" })).toHaveAttribute(
      "href",
      "/app/mundivita/characters/pc/new",
    )
  })

  it("gives an editor the player-character Edit link and says a draft cannot be linked", async () => {
    openApp("/app/mundivita/world/character/p1")
    expect(await screen.findByRole("link", { name: "Edit player character" })).toHaveAttribute(
      "href",
      "/app/mundivita/characters/p1/edit",
    )
    expect(screen.queryByRole("link", { name: "Edit NPC" })).toBeNull()
    expect(await screen.findByText(/Publish this character before linking a player/)).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "Link a player" })).toBeNull()
  })

  it("links a published player character to Access with the character chosen", async () => {
    vi.unstubAllGlobals()
    mock("canon")
    openApp("/app/mundivita/world/character/p1")
    expect(await screen.findByRole("link", { name: "Link a player" })).toHaveAttribute(
      "href",
      "/app/mundivita/access?character=p1",
    )
  })

  it("offers the Link a player action only to people who can manage access", async () => {
    vi.unstubAllGlobals()
    mock("canon")
    openApp("/app/mundivita/world/character/p1", ["canon.edit"])
    await screen.findByRole("link", { name: "Edit player character" })
    expect(screen.queryByRole("link", { name: "Link a player" })).toBeNull()
  })

  it("gives a player no authoring controls and sends no authoring request", async () => {
    openApp("/app/mundivita/world/character/p1", ["campaign.view"])
    await screen.findByRole("heading", { level: 1, name: "Aldric" })
    expect(screen.queryByRole("link", { name: "Edit player character" })).toBeNull()
    expect(server.calls.some((c) => c.path.includes("/authoring/"))).toBe(false)
  })
})
