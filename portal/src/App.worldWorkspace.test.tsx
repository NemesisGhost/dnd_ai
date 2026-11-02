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

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const timeline = (id: string, name: string, over: object = {}) => ({
  timeline_id: id,
  name,
  description: null,
  is_primary: id === "timeline-primary",
  parent_timeline_id: null,
  branch_point: null,
  lifecycle_status: "active",
  row_version: 1,
  ...over,
})

const worldBody = {
  world_id: "world-mundivita",
  name: "Mundivita",
  description: null,
  lifecycle_status: "active",
  row_version: 1,
  primary_timeline_id: "timeline-primary",
  capabilities: ["campaign.create", "timeline.manage", "world.manage", "world.view"],
  allowed_rulesets: [],
  timelines: [
    timeline("timeline-primary", "Primary Timeline"),
    timeline("timeline-side", "Side Timeline", { parent_timeline_id: "timeline-primary" }),
  ],
  managed_campaigns: [],
  available_actions: [],
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

beforeEach(() => {
  vi.mocked(useSessionBootstrap).mockReturnValue({
    state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
    reload: vi.fn(),
    refresh: vi.fn(),
  })
  server = installMockServer()
  server.on("GET", /^\/worlds\?status=/, {
    body: {
      items: [
        {
          world_id: "world-mundivita",
          name: "Mundivita",
          description: null,
          capabilities: ["campaign.create", "timeline.manage", "world.manage", "world.view"],
        },
      ],
      next_cursor: null,
    },
  })
  server.on("GET", "/worlds/world-mundivita", { body: worldBody })
  server.on("GET", "/worlds/world-mundivita/timelines/timeline-side", {
    body: {
      ...timeline("timeline-side", "Side Timeline"),
      children: [],
      managed_campaigns: [],
      available_actions: [],
      blocked_actions: [],
    },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("world workspace routes", () => {
  it.each([
    ["/worlds", "Worlds"],
    ["/worlds/world-mundivita", "Mundivita"],
    ["/worlds/world-mundivita/timelines", "Timelines"],
    ["/worlds/world-mundivita/timelines/timeline-side", "Side Timeline"],
  ])("%s has one main, one h1, and the hierarchy panel", async (path, heading) => {
    renderAt(path)

    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument()
    expect(screen.getAllByRole("main")).toHaveLength(1)
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
    const main = screen.getByRole("main")
    for (const name of ["World", "Timeline", "Campaign", "Character perspective"]) {
      expect(within(main).getByRole("combobox", { name })).toBeInTheDocument()
    }
  })

  it("identifies the parent world on a directly loaded timeline", async () => {
    renderAt("/worlds/world-mundivita/timelines/timeline-side")

    const main = screen.getByRole("main")
    await waitFor(() =>
      expect(
        (within(main).getByRole("combobox", { name: "World" }) as HTMLSelectElement)
          .selectedOptions[0]?.textContent,
      ).toBe("Mundivita"),
    )
    expect(
      (within(main).getByRole("combobox", { name: "Timeline" }) as HTMLSelectElement)
        .selectedOptions[0]?.textContent,
    ).toBe("Side Timeline")
    expect(
      screen.getByRole("link", { name: "Timeline overview" }),
    ).toHaveAttribute("href", "/worlds/world-mundivita/timelines/timeline-side")
  })

  it("the sidebar Timelines destination opens the world collection, not a campaign's timeline", async () => {
    renderAt("/worlds/world-mundivita")
    await screen.findByRole("heading", { level: 1, name: "Mundivita" })

    const link = await screen.findByRole("link", { name: "Timelines" })
    expect(link).toHaveAttribute("href", "/worlds/world-mundivita/timelines")
    fireEvent.click(link)

    expect(await screen.findByRole("heading", { level: 1, name: "Timelines" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Side Timeline" })).toHaveAttribute(
      "href",
      "/worlds/world-mundivita/timelines/timeline-side",
    )
  })

  it("makes no Phase 12 request from the world workspace", async () => {
    renderAt("/worlds/world-mundivita/timelines")
    await screen.findByRole("link", { name: "Side Timeline" })

    expect(server.calls.filter((call) => /\/ask|ai|summar/i.test(call.path))).toEqual([])
  })
})
