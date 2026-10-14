import { configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { RouterProvider, createMemoryRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import App from "./App"
import { RouteSessionProvider } from "./context/RouteSessionProvider"
import { ThemeProvider } from "./themes/ThemeProvider"
import type { CampaignContext, SessionBootstrap } from "./types/bootstrap"

// World / Campaign context propagation (docs/UI_DESIGN.md §4.5): a newer
// explicit selection (route campaign, or the world the route selects) always
// beats the saved last-visited / startup fallbacks, and a fallback is only
// ever a campaign of the selected world. The server is faked at the fetch
// boundary so the real session provider, sidebar, hierarchy panel and routes
// run together.

function campaign(id: string, worldId: string, timelineId: string): CampaignContext {
  return {
    campaign_id: id,
    campaign_name: `Campaign ${id}`,
    world_id: worldId,
    world_name: `World ${worldId}`,
    timeline_id: timelineId,
    timeline_name: `Timeline ${timelineId}`,
    roles: ["campaign_owner"],
    character_perspectives: [],
    selected_character_id: null,
    capabilities: ["access.manage"],
  }
}

// World w1 holds campaigns a and b; world w2 holds only c.
const CAMPAIGNS = [campaign("a", "w1", "t1"), campaign("b", "w1", "t1"), campaign("c", "w2", "t2")]

function worldDetail(id: string, timelineId: string) {
  return {
    world_id: id,
    name: `World ${id}`,
    description: null,
    lifecycle_status: "active",
    row_version: 1,
    primary_timeline_id: timelineId,
    capabilities: ["world.manage", "world.view"],
    default_ruleset_id: null,
    allowed_rulesets: [],
    timelines: [
      {
        timeline_id: timelineId,
        name: `Timeline ${timelineId}`,
        description: null,
        is_primary: true,
        parent_timeline_id: null,
        branch_point: null,
        lifecycle_status: "active",
        row_version: 1,
      },
    ],
    managed_campaigns: [],
    available_actions: ["update"],
    blocked_actions: [],
  }
}

function accessOverview(campaignId: string) {
  return {
    members: [
      {
        campaign_membership_id: `m-${campaignId}`,
        user_id: `u-${campaignId}`,
        display_name: `Member of ${campaignId}`,
        status_code: "active",
        status_display_name: "Active",
        account_is_active: true,
        joined_at: "2026-01-01T00:00:00Z",
        roles: [],
        character_relationships: [],
        grants: [],
      },
    ],
    assignable_roles: [],
    assignable_characters: [],
    assignable_relationship_types: [],
    grantable_resource_capabilities: [],
    access_groups: [],
  }
}

function deferred(): { promise: Promise<void>; release: () => void } {
  let release: () => void = () => undefined
  const promise = new Promise<void>((resolve) => {
    release = resolve
  })
  return { promise, release }
}

interface FakeServer {
  lastVisited: string | null
  requests: string[]
  // Optional gates that model slow responses.
  holdPut: Promise<void> | null
  holdWorld: Record<string, Promise<void>>
  holdAccess: Record<string, Promise<void>>
  unavailableWorlds: string[]
  startup: string | null
}

// These tests drive the whole application through several navigations; leave
// headroom for a loaded CI worker instead of the 1s default.
configure({ asyncUtilTimeout: 5000 })
vi.setConfig({ testTimeout: 20_000 })

let server: FakeServer
let worlds: ReturnType<typeof worldDetail>[]

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function installFakeServer(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString()
      server.requests.push(`${init?.method ?? "GET"} ${url}`)

      if (url === "/auth/session") {
        // As on the real server, the saved value is read when this is handled.
        const bootstrap: SessionBootstrap = {
          user: { user_id: "u1", display_name: "Gina GM" },
          csrf_token: "csrf",
          browser_session_id: "s1",
          is_platform_administrator: false,
          global_capabilities: [],
          startup_campaign_id: server.startup,
          campaign_preferences: {
            startup_mode: "resume_last_visited",
            preferred_campaign_id: null,
            last_visited_campaign_id: server.lastVisited,
          },
          campaigns: CAMPAIGNS,
          features: { ask: false, ai_summaries: false, gm_briefs: false, cited_rules: false },
        }
        return json(bootstrap)
      }
      if (url === "/api/auth/preferences/last-visited-campaign") {
        await server.holdPut
        server.lastVisited = JSON.parse(String(init?.body)).campaign_id
        return new Response(null, { status: 204 })
      }
      if (url.startsWith("/api/worlds?")) {
        return json({ items: worlds, next_cursor: null })
      }
      const worldMatch = /^\/api\/worlds\/([^/?]+)$/.exec(url)
      if (worldMatch !== null) {
        const id = worldMatch[1]!
        await server.holdWorld[id]
        const world = worlds.find((item) => item.world_id === id)
        return world === undefined || server.unavailableWorlds.includes(id)
          ? json({ detail: "not found" }, 404)
          : json(world)
      }
      const accessMatch = /^\/api\/campaigns\/([^/]+)\/access-overview$/.exec(url)
      if (accessMatch !== null) {
        const id = accessMatch[1]!
        await server.holdAccess[id]
        return json(accessOverview(id))
      }
      return json({ detail: "not found" }, 404)
    }),
  )
}

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      {
        path: "*",
        element: (
          <RouteSessionProvider>
            <App />
          </RouteSessionProvider>
        ),
      },
    ],
    { initialEntries: [path] },
  )
  const view = render(
    <ThemeProvider>
      <RouterProvider router={router} />
    </ThemeProvider>,
  )
  lastUnmount = view.unmount
  return router
}

let lastUnmount: () => void = () => undefined

function renderAtWithUnmount(path: string) {
  renderAt(path)
  return { unmount: lastUnmount }
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

function sidebar() {
  return screen.getByRole("navigation", { name: "Main" })
}

function accessButton() {
  return within(sidebar()).queryByRole("button", { name: "Access" })
}

// The sidebar's Access slot is present for this caller on every route; it only
// becomes an enabled disclosure once a campaign resolves.
async function expectAccessSlotRendered() {
  await waitFor(() => expect(sidebar().textContent).toContain("Access"))
}

// Opens the Access group and follows Access Management. `expected` is the
// campaign the link must target; waiting for it keeps a test from clicking a
// group that is about to be replaced while the sidebar settles.
async function openAccess(expected?: string) {
  const nav = await screen.findByRole("navigation", { name: "Main" })
  const accessLink = () => within(nav).getByText("Access Management").closest("a")!

  // Poll with plain timers rather than waitFor: right after a history
  // navigation outside act(), waitFor keeps React from committing the sidebar's
  // update until it gives up, so it can never observe the settled state.
  const until = async (check: () => void) => {
    const deadline = Date.now() + 5000
    for (;;) {
      try {
        check()
        return
      } catch (error) {
        if (Date.now() > deadline) throw error
        await sleep(50)
      }
    }
  }

  // Let the sidebar settle on the expected target first (its group is replaced
  // while the session and world reload), then open it.
  await until(() => {
    if (expected !== undefined) {
      expect(accessLink()).toHaveAttribute("href", `/app/${expected}/access`)
    } else {
      expect(accessLink()).toBeInTheDocument()
    }
  })
  // The group opens itself when mounted on an Access route.
  const button = within(nav).getByRole("button", { name: "Access" })
  if (button.getAttribute("aria-expanded") !== "true") {
    fireEvent.click(button)
  }
  await until(() => expect(accessLink().closest("ul")).not.toHaveAttribute("hidden"))
  fireEvent.click(accessLink())
}

async function chooseInfoBoxCampaign(id: string) {
  const select = await screen.findByLabelText("Campaign", { selector: "select" })
  fireEvent.change(select, { target: { value: id } })
}

async function chooseInfoBoxWorld(id: string) {
  const select = await screen.findByLabelText("World", { selector: "select" })
  await waitFor(() =>
    expect(within(select).getByRole("option", { name: `World ${id}` })).toBeInTheDocument(),
  )
  // Wait for GET /worlds: explicit world authority decides the destination.
  await waitFor(() =>
    expect(server.requests.some((entry) => entry.startsWith("GET /api/worlds?"))).toBe(true),
  )
  await sleep(50)
  fireEvent.change(select, { target: { value: id } })
}

beforeEach(() => {
  worlds = [worldDetail("w1", "t1"), worldDetail("w2", "t2")]
  server = {
    lastVisited: null,
    requests: [],
    holdPut: null,
    holdWorld: {},
    holdAccess: {},
    unavailableWorlds: [],
    startup: "a",
  }
  installFakeServer()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("Access follows the selected campaign", () => {
  it("Info Box campaign change", async () => {
    server.lastVisited = "a"
    const router = renderAt("/app/a/home")

    await chooseInfoBoxCampaign("b")
    await waitFor(() => expect(router.state.location.pathname).toBe("/app/b/home"))
    await openAccess()

    await waitFor(() => expect(router.state.location.pathname).toBe("/app/b/access"))
    await waitFor(() =>
      expect(server.requests).toContain("GET /api/campaigns/b/access-overview"),
    )
    expect(server.requests).not.toContain("GET /api/campaigns/a/access-overview")
  })

  it("campaign list selection", async () => {
    server.lastVisited = "a"
    const router = renderAt("/campaigns")

    const heading = await screen.findByRole("heading", { name: "Campaign b" })
    fireEvent.click(heading.closest("a")!)
    await waitFor(() => expect(router.state.location.pathname).toBe("/app/b/home"))
    await openAccess()

    await waitFor(() => expect(router.state.location.pathname).toBe("/app/b/access"))
  })

  it("the sidebar's other campaign-scoped destinations follow the chosen campaign too", async () => {
    server.lastVisited = "a"
    renderAt("/app/a/home")

    await chooseInfoBoxCampaign("b")
    await waitFor(() => {
      const hrefs = within(sidebar())
        .getAllByRole("link")
        .map((link) => link.getAttribute("href"))
      expect(hrefs).toContain("/app/b/quests")
      expect(hrefs).toContain("/app/b/characters")
      expect(hrefs).not.toContain("/app/a/quests")
    })
  })

  it("Info Box world change to a campaign-visible world", async () => {
    // No explicit world authority: the world opens through its campaign.
    worlds = []
    server.lastVisited = "a"
    const router = renderAt("/app/a/home")

    const select = await screen.findByLabelText("World", { selector: "select" })
    fireEvent.change(select, { target: { value: "w2" } })
    await waitFor(() => expect(router.state.location.pathname).toBe("/app/c/world"))
    await openAccess()

    await waitFor(() => expect(router.state.location.pathname).toBe("/app/c/access"))
  })
})

describe("world routes keep saved defaults out of the selected context", () => {
  it("Info Box world change, then Access", async () => {
    server.lastVisited = "a"
    const router = renderAt("/app/a/home")

    await chooseInfoBoxWorld("w2")
    await waitFor(() => expect(router.state.location.pathname).toBe("/worlds/w2"))
    await waitFor(() => expect(accessButton()).not.toBeNull())
    await openAccess()

    await waitFor(() => expect(router.state.location.pathname).toBe("/app/c/access"))
    expect(server.requests).not.toContain("GET /api/campaigns/a/access-overview")
  })

  it("Info Box world change, then a valid campaign of that world, then Access", async () => {
    server.lastVisited = "c"
    const router = renderAt("/app/c/home")

    await chooseInfoBoxWorld("w1")
    await waitFor(() => expect(router.state.location.pathname).toBe("/worlds/w1"))
    await router.navigate("/worlds/w1/timelines/t1")
    await waitFor(() => expect(router.state.location.pathname).toBe("/worlds/w1/timelines/t1"))
    const select = await screen.findByLabelText("Campaign", { selector: "select" })
    await waitFor(() =>
      expect(within(select).getByRole("option", { name: "Campaign b" })).toBeInTheDocument(),
    )
    fireEvent.change(select, { target: { value: "b" } })
    await waitFor(() => expect(router.state.location.pathname).toBe("/app/b/home"))
    await openAccess()

    await waitFor(() => expect(router.state.location.pathname).toBe("/app/b/access"))
  })

  it("offers no campaign link while the chosen world is still being confirmed", async () => {
    server.lastVisited = "a"
    const gate = deferred()
    server.holdWorld["w2"] = gate.promise
    const router = renderAt("/app/a/home")

    await chooseInfoBoxWorld("w2")
    await waitFor(() => expect(router.state.location.pathname).toBe("/worlds/w2"))
    await expectAccessSlotRendered()

    expect(accessButton()).toBeNull()
    expect(
      within(sidebar()).queryByRole("link", { name: "Characters" }),
    ).not.toBeInTheDocument()

    gate.release()
    await waitFor(() => expect(accessButton()).not.toBeNull())
    await openAccess()
    await waitFor(() => expect(router.state.location.pathname).toBe("/app/c/access"))
  })

  it("keeps a saved campaign that belongs to the selected world", async () => {
    server.lastVisited = "b"
    const router = renderAt("/worlds/w1")

    await waitFor(() => expect(accessButton()).not.toBeNull())
    await openAccess()

    await waitFor(() => expect(router.state.location.pathname).toBe("/app/b/access"))
  })

  it("does not use a campaign of another world on a direct world link", async () => {
    server.lastVisited = "a"
    const router = renderAt("/worlds/w2")

    await waitFor(() => expect(accessButton()).not.toBeNull())
    await openAccess()

    await waitFor(() => expect(router.state.location.pathname).toBe("/app/c/access"))
  })

  it("does not choose between several campaigns of the world when no saved one belongs to it", async () => {
    server.lastVisited = "c"
    server.startup = "c"
    renderAt("/worlds/w1")

    await expectAccessSlotRendered()
    await sleep(100)
    expect(accessButton()).toBeNull()
    expect(
      within(sidebar()).queryByRole("link", { name: "Characters" }),
    ).not.toBeInTheDocument()
  })

  it("exposes no campaign navigation for a world that is denied, missing, or fails", async () => {
    server.lastVisited = "a"
    server.unavailableWorlds = ["w9"]
    worlds = [...worlds, worldDetail("w9", "t9")]

    for (const path of ["/worlds/w9", "/worlds/does-not-exist"]) {
      const { unmount } = renderAtWithUnmount(path)
      await expectAccessSlotRendered()
      await waitFor(() =>
        expect(server.requests.some((r) => r.endsWith(path.replace("/worlds/", "/api/worlds/")))).toBe(
          true,
        ),
      )
      await sleep(150)
      expect(accessButton()).toBeNull()
      expect(within(sidebar()).queryByRole("link", { name: "Characters" })).not.toBeInTheDocument()
      expect(within(sidebar()).queryByRole("link", { name: "Campaign Home" })).not.toBeInTheDocument()
      unmount()
    }
  })

  it("exposes no campaign navigation for an unknown timeline of a valid world", async () => {
    server.lastVisited = "a"
    renderAt("/worlds/w1/timelines/t9")

    await expectAccessSlotRendered()
    await waitFor(() => expect(server.requests).toContain("GET /api/worlds/w1"))
    await sleep(150)
    expect(accessButton()).toBeNull()
    expect(within(sidebar()).queryByRole("link", { name: "Characters" })).not.toBeInTheDocument()
  })

  it("still resolves a campaign for a valid timeline of the world", async () => {
    server.lastVisited = "b"
    const router = renderAt("/worlds/w1/timelines/t1")

    await openAccess("b")
    await waitFor(() => expect(router.state.location.pathname).toBe("/app/b/access"))
  })

  it("follows browser Back and Forward between a campaign and a world", async () => {
    server.lastVisited = "a"
    const router = renderAt("/app/a/home")
    await screen.findByLabelText("Campaign", { selector: "select" })

    await chooseInfoBoxWorld("w2")
    await waitFor(() => expect(router.state.location.pathname).toBe("/worlds/w2"))
    await waitFor(() => expect(accessButton()).not.toBeNull())

    await router.navigate(-1)
    await waitFor(() => expect(router.state.location.pathname).toBe("/app/a/home"))
    // A history navigation outside act() remounts the scope-keyed session;
    // give it a moment to settle before reading the sidebar.
    await sleep(400)
    await openAccess("a")
    await waitFor(() => expect(router.state.location.pathname).toBe("/app/a/access"))

    await router.navigate("/worlds/w2")
    await waitFor(() => expect(router.state.location.pathname).toBe("/worlds/w2"))
    // A history navigation outside act() remounts the scope-keyed session;
    // give it a moment to settle before reading the sidebar.
    await sleep(400)
    await openAccess("c")
    await waitFor(() => expect(router.state.location.pathname).toBe("/app/c/access"))
  })
})

describe("a newer selection survives lagging or stale saved state", () => {
  it("targets the campaign just chosen while its last-visited write is still in flight", async () => {
    server.lastVisited = "a"
    const gate = deferred()
    server.holdPut = gate.promise
    const router = renderAt("/app/a/home")

    await chooseInfoBoxCampaign("b")
    await waitFor(() => expect(router.state.location.pathname).toBe("/app/b/home"))
    await waitFor(() =>
      expect(server.requests).toContain("PUT /api/auth/preferences/last-visited-campaign"),
    )

    // Leave the campaign scope before the write has committed.
    await router.navigate("/campaigns")
    await sleep(50)
    gate.release()

    await waitFor(() => expect(accessButton()).not.toBeNull())
    expect(server.lastVisited).toBe("b")
    await openAccess()
    await waitFor(() => expect(router.state.location.pathname).toBe("/app/b/access"))
  })

  it("a delayed Access response for the previous campaign never replaces the new one", async () => {
    server.lastVisited = "a"
    const gate = deferred()
    server.holdAccess["a"] = gate.promise
    const router = renderAt("/app/a/access")
    await waitFor(() =>
      expect(server.requests).toContain("GET /api/campaigns/a/access-overview"),
    )

    await chooseInfoBoxCampaign("b")
    await waitFor(() => expect(router.state.location.pathname).toBe("/app/b/home"))
    await openAccess()
    await screen.findByText("Member of b")

    gate.release()
    await sleep(50)
    expect(screen.queryByText("Member of a")).not.toBeInTheDocument()
    expect(screen.getByText("Member of b")).toBeInTheDocument()
  })

  it("never uses an unauthorized campaign in the URL", async () => {
    server.lastVisited = "c"
    renderAt("/app/ghost/home")

    await screen.findByText("Campaign not found")
    await waitFor(() => expect(accessButton()).not.toBeNull())
    expect(document.querySelector('a[href*="ghost"]')).toBeNull()
  })

  it("ignores a saved campaign that is no longer authorized", async () => {
    server.lastVisited = "gone"
    renderAt("/campaigns")

    await screen.findByRole("heading", { name: "Campaign a" })
    // Falls through to the server's startup campaign.
    await waitFor(() => expect(accessButton()).not.toBeNull())
    expect(document.querySelector('a[href*="gone"]')).toBeNull()
  })
})
