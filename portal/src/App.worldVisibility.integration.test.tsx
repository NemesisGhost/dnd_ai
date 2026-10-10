import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import App from "./App"
import { RouteSessionProvider } from "./context/RouteSessionProvider"
import { sessionBootstrapFixture } from "./fixtures/sessionBootstrap"
import { useSessionBootstrap } from "./hooks/useSessionBootstrap"
import { installMockServer } from "./test/authoringHarness"
import type { MockServer } from "./test/authoringHarness"
import { ThemeProvider } from "./themes/ThemeProvider"
import type { SessionBootstrap } from "./types/bootstrap"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

// The observed account (Phase13E Dev Player A), as the corrected server now
// describes it:
// - explicit world_owner of "test 1" (a legacy, pre-ADR-0018 world);
// - a player (campaign.view) in Campaign A, on a different world it holds no
//   world role on;
// - an active but roleless Campaign B membership, its last-visited campaign —
//   which the bootstrap no longer lists, selects, or echoes as a preference.
const OWNER = ["campaign.create", "timeline.manage", "world.manage", "world.view"]

const bootstrap: SessionBootstrap = {
  ...sessionBootstrapFixture,
  user: { user_id: "player-a", display_name: "Phase13E Dev Player A" },
  is_platform_administrator: false,
  global_capabilities: [],
  startup_campaign_id: "camp-a",
  campaign_preferences: {
    startup_mode: "resume_last_visited",
    preferred_campaign_id: null,
    last_visited_campaign_id: null,
  },
  campaigns: [
    {
      campaign_id: "camp-a",
      campaign_name: "Phase13C Campaign A",
      world_id: "world-hosted",
      world_name: "Phase13C Dev World",
      timeline_id: "timeline-a",
      timeline_name: "Phase13C Timeline A",
      roles: ["player"],
      character_perspectives: [],
      selected_character_id: null,
      capabilities: ["campaign.view"],
    },
  ],
}

const ownedWorld = {
  world_id: "world-owned",
  name: "test 1",
  description: null,
  lifecycle_status: "active",
  row_version: 1,
  primary_timeline_id: "timeline-owned",
  capabilities: OWNER,
  default_ruleset_id: null,
  allowed_rulesets: [],
  timelines: [],
  managed_campaigns: [],
  available_actions: ["update", "archive", "create_timeline", "create_campaign", "create_calendar"],
  blocked_actions: [],
}

let server: MockServer

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ThemeProvider>
        <RouteSessionProvider>
          <App />
        </RouteSessionProvider>
      </ThemeProvider>
    </MemoryRouter>,
  )
}

function worldOptions(): string[] {
  return within(screen.getByRole("combobox", { name: "World" }))
    .getAllByRole("option")
    .map((option) => option.textContent ?? "")
}

beforeEach(() => {
  vi.mocked(useSessionBootstrap).mockReturnValue({
    state: { status: "authenticated", bootstrap },
    reload: vi.fn(),
    refresh: vi.fn(),
  })
  server = installMockServer()
  server.on("GET", /^\/worlds\?status=/, {
    body: {
      items: [{ ...ownedWorld, timelines: undefined }],
      next_cursor: null,
    },
  })
  server.on("GET", "/worlds/world-owned", { body: ownedWorld })
  // No world role on the campaign's world: the same non-disclosing 404 as
  // any unknown world.
  server.on("GET", "/worlds/world-hosted", { status: 404, body: {} })
  server.on("GET", /^\/campaigns\/camp-a\/world\/search/, {
    body: {
      items: [
        {
          entity_id: "location-1",
          category: "location",
          entity_type_code: "city",
          name: "Glass Harbor",
          summary: null,
        },
      ],
      next_cursor: null,
    },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("world visibility for a player who also owns a legacy world", () => {
  it("All Worlds and the hierarchy offer the same two worlds", async () => {
    renderAt("/worlds")

    const owned = await screen.findByRole("link", { name: "test 1" })
    const hosted = screen.getByRole("link", { name: "Phase13C Dev World" })
    expect(owned).toHaveAttribute("href", "/worlds/world-owned")
    expect(owned.closest("li")).not.toHaveTextContent("View only")
    expect(hosted).toHaveAttribute("href", "/app/camp-a/world")
    expect(hosted.closest("li")).toHaveTextContent("View only")
    await waitFor(() =>
      expect(worldOptions()).toEqual(["No selection", "Phase13C Dev World", "test 1"]),
    )
  })

  it("keeps the same hierarchy choices on a campaign route", async () => {
    renderAt("/app/camp-a/home")

    await waitFor(() =>
      expect(worldOptions()).toEqual(["No selection", "Phase13C Dev World", "test 1"]),
    )
  })

  it("opens the campaign-visible world in Campaign World, read-only", async () => {
    renderAt("/worlds")

    fireEvent.click(await screen.findByRole("link", { name: "Phase13C Dev World" }))

    expect(await screen.findByText("Glass Harbor")).toBeInTheDocument()
    expect(screen.queryByText("World unavailable")).not.toBeInTheDocument()
    // campaign.view alone: no world-authoring or campaign-creation controls.
    for (const name of ["New location", "Edit world", "New campaign", "Create world"]) {
      expect(screen.queryByRole("link", { name })).not.toBeInTheDocument()
    }
    expect(server.callsTo("GET", /^\/campaigns\/camp-a\/world\/search/)).not.toHaveLength(0)
  })

  it("exposes editing only on the explicitly owned world", async () => {
    const owned = renderAt("/worlds/world-owned")
    expect(await screen.findByRole("link", { name: "Edit world" })).toBeInTheDocument()
    owned.unmount()

    const hosted = renderAt("/worlds/world-hosted")
    expect(await screen.findByRole("heading", { level: 1, name: "World not available" })).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "Edit world" })).not.toBeInTheDocument()
    hosted.unmount()

    renderAt("/worlds/world-hosted/edit")
    await waitFor(() => expect(server.callsTo("GET", "/worlds/world-hosted")).not.toHaveLength(0))
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument()
  })

  it("never offers the inaccessible campaign", async () => {
    renderAt("/app/camp-a/home")

    const campaign = await screen.findByRole("combobox", { name: "Campaign" })
    await waitFor(() =>
      expect(within(campaign).getAllByRole("option").map((o) => o.textContent)).toEqual([
        "No selection",
        "Phase13C Campaign A",
      ]),
    )
    expect(document.body.textContent).not.toContain("Campaign B")
    expect(server.calls.some((call) => call.path.includes("camp-b"))).toBe(false)
  })
})
