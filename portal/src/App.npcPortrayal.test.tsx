import { fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const PORTRAYAL = "/campaigns/mundivita/authoring/npcs/npc-1/portrayal"
const LEVEL = "/campaigns/mundivita/authoring/npcs/npc-1/detail-level"

const view = (over: Record<string, unknown> = {}) => ({
  npc_id: "npc-1",
  name: "Mira",
  detail_level: "minor",
  detail_levels: [
    { value: "minor", label: "Minor" },
    { value: "major", label: "Major" },
  ],
  row_version: 3,
  canon_status: "canon",
  lifecycle_status: "active",
  current_version: 1,
  shown_version: 1,
  fields: { voice: "Quiet" },
  field_labels: [{ name: "voice", label: "Voice" }],
  limits: { field_max_length: 500, note_max_length: 200 },
  versions: [{ version_number: 1, created_at: "2026-01-01T00:00:00Z", change_note: null }],
  can_edit: true,
  ...over,
})

let server: MockServer

beforeEach(() => {
  server = installCampaignShellMocks()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("NPC portrayal page", () => {
  it("reports a saved version whose re-read fails, keeps the draft, holds writes, and recovers by reading only", async () => {
    let current = view()
    let readFails = false
    server.on("GET", PORTRAYAL, () => (readFails ? { status: 500, body: {} } : { body: current }))
    server.on("POST", PORTRAYAL, () => {
      current = view({ current_version: 2, fields: { voice: "Gruff" } })
      readFails = true
      return { body: current }
    })
    openApp("/app/mundivita/characters/npc-1/portrayal")
    const voice = await screen.findByLabelText("Voice")
    fireEvent.change(voice, { target: { value: "Gruff" } })
    fireEvent.click(screen.getByRole("button", { name: "Save new version" }))

    expect(
      await screen.findByText(/Portrayal saved as a new version\. The latest portrayal could not be loaded/),
    ).toBeInTheDocument()
    const live = screen.getByTestId("authoring-announcer")
    expect(live).toHaveTextContent("Saved, but the latest data could not be loaded.")
    expect(live).not.toHaveTextContent(/^Portrayal saved/)
    // The page and the typed text stay; a second save would send the version this page still holds.
    expect(screen.getByLabelText("Voice")).toHaveValue("Gruff")
    expect(screen.getByRole("button", { name: "Save new version" })).toBeDisabled()
    expect(server.callsTo("POST", PORTRAYAL)).toHaveLength(1)

    readFails = false
    fireEvent.click(screen.getByRole("button", { name: "Try again" }))
    await waitFor(() => expect(screen.getByRole("button", { name: "Save new version" })).toBeEnabled())
    await waitFor(() => expect(live).toHaveTextContent("Portrayal saved as a new version"))
    expect(screen.queryByText(/could not be loaded/)).toBeNull()
    expect(server.callsTo("POST", PORTRAYAL)).toHaveLength(1)
  })

  it("reports a saved detail level whose re-read fails and does not announce it as done", async () => {
    let current = view()
    let readFails = false
    server.on("GET", PORTRAYAL, () => (readFails ? { status: 500, body: {} } : { body: current }))
    server.on("POST", LEVEL, () => {
      current = view({ detail_level: "major", row_version: 4 })
      readFails = true
      return { body: current }
    })
    openApp("/app/mundivita/characters/npc-1/portrayal")
    fireEvent.change(await screen.findByRole("combobox", { name: /Detail level/ }), { target: { value: "major" } })
    fireEvent.click(screen.getByRole("button", { name: "Save detail level" }))

    expect(await screen.findByText(/Detail level saved\. The latest portrayal could not be loaded/)).toBeInTheDocument()
    expect(screen.getByTestId("authoring-announcer")).not.toHaveTextContent(/^Detail level saved/)
    expect(server.callsTo("POST", LEVEL)[0]!.body).toEqual({ expected_row_version: 3, detail_level: "major" })

    readFails = false
    fireEvent.click(screen.getByRole("button", { name: "Try again" }))
    await waitFor(() => expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Detail level saved"))
    expect(server.callsTo("POST", LEVEL)).toHaveLength(1)
  })
})
