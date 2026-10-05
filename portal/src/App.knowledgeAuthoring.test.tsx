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
  knowledge_types: [{ value: "secret", label: "Secret" }],
  truth_statuses: [{ value: "true", label: "True" }],
  sensitivities: [{ value: "secret", label: "Secret" }],
  limits: { statement_max_length: 4000, change_note_max_length: 1000 },
}
const VIEW = {
  knowledge_item_id: "k1",
  statement: "The duke is a vampire.",
  knowledge_type: "secret",
  truth_status: "true",
  sensitivity: "secret",
  subject: null,
  in_use: false,
  canon_status: "draft",
  lifecycle_status: "active",
  row_version: 1,
  available_actions: ["update"],
  blocked_actions: [],
  field_locks: [],
}

let server: MockServer

beforeEach(() => {
  server = installCampaignShellMocks()
  server.on("GET", "/campaigns/mundivita/authoring/knowledge/options", { body: OPTIONS })
  server.on("GET", "/campaigns/mundivita/authoring/knowledge/k1", { body: VIEW })
  server.on("GET", /\/entities\/k1\/lifecycle$/, { status: 404 })
  server.on("GET", /^\/campaigns\/mundivita\/knowledge(\?.*)?$/, {
    body: { items: [], next_cursor: null },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("knowledge authoring routes", () => {
  it.each([
    ["/app/mundivita/knowledge/new", "New knowledge claim"],
    ["/app/mundivita/knowledge/k1/edit", "Edit knowledge claim"],
  ])("%s loads directly with one main and one h1", async (path, heading) => {
    openApp(path)
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument()
    expect(screen.getAllByRole("main")).toHaveLength(1)
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
    expect(screen.queryByText(/Unexpected Application Error/i)).toBeNull()
    // "new" is never treated as a knowledge item id.
    expect(server.calls.some((c) => c.path.endsWith("/knowledge/new"))).toBe(false)
  })

  it("gives editors a New claim link on the Knowledge screen", async () => {
    openApp("/app/mundivita/knowledge")
    expect(await screen.findByRole("link", { name: "New claim" })).toHaveAttribute(
      "href",
      "/app/mundivita/knowledge/new",
    )
  })

  it("offers players no New claim link and sends no authoring request", async () => {
    openApp("/app/mundivita/knowledge", ["campaign.view"])
    await screen.findByRole("heading", { level: 1, name: "Knowledge" })
    expect(screen.queryByRole("link", { name: "New claim" })).toBeNull()
    expect(server.calls.some((c) => c.path.includes("/authoring/"))).toBe(false)
  })
})
