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
  character_id: "n1",
  name: "Mira",
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

  it("gives an editor the NPC Edit link and lifecycle panel on a character's detail", async () => {
    openApp("/app/mundivita/world/character/n1")
    expect(await screen.findByRole("link", { name: "Edit NPC" })).toHaveAttribute(
      "href",
      "/app/mundivita/characters/n1/edit",
    )
    expect(await screen.findByRole("heading", { name: "Lifecycle" })).toBeInTheDocument()
  })

  it("gives a player neither and sends no authoring request", async () => {
    openApp("/app/mundivita/world/character/n1", ["campaign.view"])
    await screen.findByRole("heading", { level: 1, name: "Mira" })
    expect(screen.queryByRole("link", { name: "Edit NPC" })).toBeNull()
    expect(screen.queryByRole("heading", { name: "Lifecycle" })).toBeNull()
    expect(server.calls.some((c) => c.path.includes("/authoring/"))).toBe(false)
    expect(server.calls.some((c) => c.path.includes("/lifecycle"))).toBe(false)
  })

  it("offers New character to editors only", async () => {
    const editor = openApp("/app/mundivita/world")
    expect(await screen.findByRole("link", { name: "New character" })).toHaveAttribute(
      "href",
      "/app/mundivita/characters/new",
    )
    editor.unmount()
    openApp("/app/mundivita/world", ["campaign.view"])
    await screen.findByRole("heading", { level: 1, name: "World" })
    expect(screen.queryByRole("link", { name: "New character" })).toBeNull()
  })
})
