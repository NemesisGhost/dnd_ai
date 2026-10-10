import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { QuestCard } from "./components/QuestCard"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const OPTIONS = {
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
const VIEW = {
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

let server: MockServer

beforeEach(() => {
  server = installCampaignShellMocks()
  server.on("GET", "/campaigns/mundivita/authoring/quests/options", { body: OPTIONS })
  server.on("GET", "/campaigns/mundivita/authoring/quests/q1", { body: VIEW })
  server.on("GET", /\/entities\/q1\/lifecycle$/, { status: 404 })
  server.on("GET", /^\/campaigns\/mundivita\/quests(\?.*)?$/, {
    body: [
      { quest_id: "q1", name: "The Lost Amulet", status_code: null, tracked: false, canon_status: "draft", lifecycle_status: "active" },
      { quest_id: "q2", name: "The Siege", status_code: "active", tracked: true, canon_status: "canon", lifecycle_status: "active" },
    ],
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("quest authoring routes", () => {
  it.each([
    ["/app/mundivita/quests/new", "New quest"],
    ["/app/mundivita/quests/q1/edit", "Edit quest"],
  ])("%s loads directly with one main and one h1", async (path, heading) => {
    openApp(path)
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument()
    expect(screen.getAllByRole("main")).toHaveLength(1)
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
    expect(screen.queryByText(/Unexpected Application Error/i)).toBeNull()
    // "new" is never treated as a quest id.
    expect(server.calls.some((c) => c.path.endsWith("/quests/new"))).toBe(false)
  })

  it("gives editors a New quest link and sends an untracked draft's card to its editor", async () => {
    openApp("/app/mundivita/quests")
    expect(await screen.findByRole("link", { name: "New quest" })).toHaveAttribute(
      "href",
      "/app/mundivita/quests/new",
    )
    expect(screen.getByRole("link", { name: /The Lost Amulet, Draft · Not started/ })).toHaveAttribute(
      "href",
      "/app/mundivita/quests/q1/edit",
    )
    // A tracked quest's detail link carries the list's party perspective.
    expect(screen.getByRole("link", { name: /The Siege, Active/ })).toHaveAttribute(
      "href",
      "/app/mundivita/quests/q2?character_id=character-ixamarra&party_id=party-primary",
    )
  })

  it("offers players no New quest link", async () => {
    openApp("/app/mundivita/quests", ["campaign.view"])
    await screen.findByRole("heading", { level: 1, name: "Quests" })
    expect(screen.queryByRole("link", { name: "New quest" })).toBeNull()
    expect(server.calls.some((c) => c.path.includes("/authoring/"))).toBe(false)
  })
})

describe("QuestCard", () => {
  const render_ = (quest: Parameters<typeof QuestCard>[0]["quest"]) =>
    render(
      <MemoryRouter>
        <QuestCard campaignId="c1" quest={quest} />
      </MemoryRouter>,
    )

  it("renders a player's quest exactly as before", () => {
    render_({ quest_id: "q", name: "The Siege", status_code: "active" })
    expect(screen.getByRole("link", { name: "The Siege, Active" })).toHaveAttribute(
      "href",
      "/app/c1/quests/q",
    )
  })

  it("labels an archived or draft definition for an editor without hiding its progress", () => {
    render_({
      quest_id: "q",
      name: "Old plot",
      status_code: "completed",
      tracked: true,
      canon_status: "canon",
      lifecycle_status: "archived",
    })
    expect(screen.getByRole("link", { name: "Old plot, Archived · Completed" })).toBeInTheDocument()
  })
})
