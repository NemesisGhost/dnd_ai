import { act, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { Outlet, RouterProvider, createMemoryRouter, redirect } from "react-router"
import type { DataRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { RouteSessionProvider } from "../context/RouteSessionProvider"
import { usePageArrival } from "../hooks/usePageArrival"
import { AuthenticatedAppLayout } from "../layouts/AuthenticatedAppLayout"
import { CampaignSessionBoundary } from "../layouts/CampaignSessionBoundary"
import { ThemeProvider } from "../themes/ThemeProvider"
import type { CampaignContext, SessionBootstrap } from "../types/bootstrap"

// P02-4 correction. The menu and the drawer close only for the navigation the click itself started.
// Everything here runs on the production shell with a real data router whose loaders are deferred or
// redirecting, so what is in flight, what superseded it and what committed are all deterministic: no timers.

configure({ asyncUtilTimeout: 5000 })

const control = vi.hoisted(() => ({ bootstrap: null as unknown }))

vi.mock("../hooks/useSessionBootstrap", async () => {
  const react = await import("react")
  return {
    useSessionBootstrap: () => {
      const [bootstrap] = react.useState(control.bootstrap)
      const refresh = react.useCallback(async () => true, [])
      const reload = react.useCallback(() => undefined, [])
      return { state: { status: "authenticated", bootstrap }, reload, refresh }
    },
  }
})

function campaign(id: string, world: string, perspectives: string[], selected: string | null): CampaignContext {
  return {
    campaign_id: id,
    campaign_name: `Campaign ${id}`,
    world_id: world,
    world_name: `World ${world}`,
    timeline_id: `t-${world}`,
    timeline_name: `Timeline ${world}`,
    roles: ["campaign_owner"],
    character_perspectives: perspectives.map((p) => ({ character_id: p, character_name: `Name ${p}`, authorized_parties: [] })),
    selected_character_id: selected,
    capabilities: [],
    world_capabilities: ["world.view"],
  }
}

function bootstrapOf(): SessionBootstrap {
  return {
    user: { user_id: "u1", display_name: "Gina" },
    csrf_token: "csrf",
    browser_session_id: "s1",
    system_roles: ["player"],
    global_capabilities: [],
    startup_campaign_id: null,
    campaign_preferences: { startup_mode: "resume_last_visited", preferred_campaign_id: null, last_visited_campaign_id: null },
    campaigns: [campaign("alpha", "w1", ["a1", "a2"], "a1")],
    features: { ask: false, ai_summaries: false, gm_briefs: false, cited_rules: false },
  }
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
}

function Page({ title }: { title: string }) {
  const heading = usePageArrival(true)
  return (
    <main>
      <h1 ref={heading} tabIndex={-1}>
        {title}
      </h1>
    </main>
  )
}

// A loader gate per pathname: a navigation to it stays in flight until the test releases it.
interface Gate {
  release: () => void
  promise: Promise<void>
}
const gates = new Map<string, Gate>()
function hold(pathname: string): Gate {
  let release: () => void = () => {}
  const promise = new Promise<void>((resolve) => {
    release = resolve
  })
  const gate = { release, promise }
  gates.set(pathname, gate)
  return gate
}
const gated = async ({ request }: { request: Request }) => {
  await gates.get(new URL(request.url).pathname)?.promise
  return null
}

let router: DataRouter
let pingTarget = "/app/alpha/home"

function tree(entry: string) {
  router = createMemoryRouter(
    [
      {
        element: (
          <RouteSessionProvider>
            <Outlet />
          </RouteSessionProvider>
        ),
        children: [
          {
            element: <AuthenticatedAppLayout />,
            children: [
              { path: "/campaigns", element: <Page title="Campaigns" /> },
              { path: "/worlds", element: <Page title="Worlds" /> },
              {
                path: "/app/:campaignId",
                element: <CampaignSessionBoundary />,
                children: [
                  { path: "home", element: <Page title="Campaign Home" /> },
                  { path: "parties", element: <Page title="Parties" /> },
                  { path: "quests", loader: gated, element: <Page title="Quests" /> },
                  { path: "world", loader: gated, element: <Page title="Campaign world" /> },
                  {
                    path: "sessions",
                    // Waits for its gate when a test holds one, then redirects (the click's own redirect).
                    loader: async ({ request }: { request: Request }) => {
                      await gates.get(new URL(request.url).pathname)?.promise
                      return redirect("/app/alpha/parties")
                    },
                    element: <Page title="Sessions" />,
                  },
                  {
                    path: "knowledge",
                    loader: () => {
                      throw new Error("the read failed")
                    },
                    element: <Page title="Knowledge" />,
                    errorElement: <h1 tabIndex={-1}>Knowledge failed</h1>,
                  },
                  // Only ever the target of a fetcher: its loader waits for its gate, then redirects.
                  {
                    id: "ping",
                    path: "ping",
                    loader: async ({ request }: { request: Request }) => {
                      await gates.get(new URL(request.url).pathname)?.promise
                      return redirect(pingTarget)
                    },
                    element: <Page title="Ping" />,
                  },
                  { path: "characters/all", loader: gated, element: <Page title="All characters" /> },
                  { path: "characters/:characterId", element: <Page title="Character record" /> },
                ],
              },
            ],
          },
        ],
      },
    ],
    { initialEntries: [entry] },
  )
  return (
    <ThemeProvider>
      <RouterProvider router={router} />
    </ThemeProvider>
  )
}

beforeEach(() => {
  control.bootstrap = bootstrapOf()
  gates.clear()
  window.localStorage.clear()
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString()
      if (/\/worlds\/w1$/.test(url)) {
        return json({
          world_id: "w1",
          name: "World w1",
          capabilities: ["world.view"],
          default_ruleset_id: null,
          allowed_rulesets: [],
          timelines: [],
          managed_campaigns: [],
          available_actions: [],
          blocked_actions: [],
        })
      }
      return json({ detail: "not found" }, 404)
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const nav = () => screen.getByRole("navigation", { name: "Main" })
const inNav = () => within(nav())
const here = () => `${router.state.location.pathname}${router.state.location.search}${router.state.location.hash}`
const drawerToggle = () => screen.getByRole("button", { name: /(Open|Close) navigation/ })
const drawerOpen = () => nav().classList.contains("portal-sidebar--mobile-open")
const activate = (element: HTMLElement) => {
  element.focus()
  fireEvent.click(element, { detail: 0 })
}

async function start(entry: string, title: string) {
  render(tree(entry))
  await screen.findByRole("heading", { name: title })
}
const go = async (to: string | number) => {
  await act(async () => {
    await router.navigate(to as string)
  })
}
// Resolves once the router has taken the navigation in flight (the loader is gated).
const inFlight = () => waitFor(() => expect(router.state.navigation.state).not.toBe("idle"))


// The narrow drawer is the clearest witness of "closed because the click's navigation arrived": unlike a
// menu, nothing else closes it (a menu also closes when a new page takes focus, which is its own rule).
async function openDrawerAndClick(name: string) {
  fireEvent.click(drawerToggle())
  expect(drawerOpen()).toBe(true)
  const link = inNav().getByRole("link", { name })
  fireEvent.click(link)
  await inFlight()
  return link
}

describe("completion belongs to the navigation the click started", () => {
  it("is completed by its own navigation when it arrives, once: final route, drawer closed, heading focused", async () => {
    await start("/app/alpha/parties", "Parties")
    const gate = hold("/app/alpha/quests")
    await openDrawerAndClick("Quests")
    // In flight: nothing has closed.
    expect(drawerOpen()).toBe(true)

    gate.release()
    await screen.findByRole("heading", { name: "Quests" })

    expect(here()).toBe("/app/alpha/quests")
    await waitFor(() => expect(drawerOpen()).toBe(false))
    expect(screen.getByRole("heading", { name: "Quests" })).toHaveFocus()
  })

  it("is not completed by the same pathname with a different query", async () => {
    await start("/app/alpha/parties", "Parties")
    const gate = hold("/app/alpha/quests")
    await openDrawerAndClick("Quests")

    // Another navigation takes over, to the same pathname but not the same destination.
    const other = router.navigate("/app/alpha/quests?section=other")
    gate.release()
    await act(async () => {
      await other
    })
    await screen.findByRole("heading", { name: "Quests" })

    expect(here()).toBe("/app/alpha/quests?section=other")
    expect(drawerOpen()).toBe(true)
  })

  it("is not completed by the same pathname with a different hash", async () => {
    await start("/app/alpha/parties", "Parties")
    const gate = hold("/app/alpha/quests")
    await openDrawerAndClick("Quests")

    const other = router.navigate("/app/alpha/quests#elsewhere")
    gate.release()
    await act(async () => {
      await other
    })

    expect(here()).toBe("/app/alpha/quests#elsewhere")
    expect(drawerOpen()).toBe(true)
  })

  it("is not completed by a POP onto the requested destination", async () => {
    await start("/app/alpha/quests", "Quests")
    await go("/app/alpha/parties")
    await screen.findByRole("heading", { name: "Parties" })
    // The destination the click will ask for is also where Back leads.
    const gate = hold("/app/alpha/quests")
    await openDrawerAndClick("Quests")

    const back = router.navigate(-1)
    gate.release()
    await act(async () => {
      await back
    })

    expect(here()).toBe("/app/alpha/quests")
    expect(router.state.historyAction).toBe("POP")
    expect(drawerOpen()).toBe(true)
  })

  it("is not completed by an unrelated navigation to the very same destination", async () => {
    await start("/app/alpha/parties", "Parties")
    const gate = hold("/app/alpha/quests")
    await openDrawerAndClick("Quests")

    // Someone else asks for the same address while the click's own navigation is still in flight.
    const unrelated = router.navigate("/app/alpha/quests")
    gate.release()
    await act(async () => {
      await unrelated
    })

    expect(here()).toBe("/app/alpha/quests")
    expect(drawerOpen()).toBe(true)
  })

  it("is not completed by a stamp-only REPLACE of the entry it left", async () => {
    await start("/app/alpha/parties", "Parties")
    const gate = hold("/app/alpha/quests")
    await openDrawerAndClick("Quests")

    // The in-flight navigation is superseded by a same-address REPLACE of the left entry (a stamp).
    const before = router.state.location
    const stamp = router.navigate(
      { pathname: before.pathname, search: before.search },
      { replace: true, state: { ...(before.state as object), ctx: { v: 1, characterId: "a1" } }, preventScrollReset: true },
    )
    gate.release()
    await act(async () => {
      await stamp
    })

    expect(here()).toBe("/app/alpha/parties")
    expect(drawerOpen()).toBe(true)
  })

  it("follows a redirect of the click's own navigation, closing the drawer once", async () => {
    await start("/app/alpha/quests", "Quests")
    fireEvent.click(drawerToggle())
    expect(drawerOpen()).toBe(true)
    const closes = vi.fn()
    const observer = new MutationObserver(() => {
      if (!drawerOpen()) closes()
    })
    observer.observe(nav(), { attributes: true, attributeFilter: ["class"] })

    fireEvent.click(inNav().getByRole("link", { name: "Sessions" }))

    await screen.findByRole("heading", { name: "Parties" })
    expect(here()).toBe("/app/alpha/parties")
    await waitFor(() => expect(drawerOpen()).toBe(false))
    expect(closes).toHaveBeenCalledTimes(1)
    observer.disconnect()
  })

  describe("a redirect the click's own navigation did not make", () => {
    // The router marks every redirect `_isRedirect`, whoever asked for it. An independent fetcher whose
    // loader redirects while the click's navigation is still in flight produces the same mark.
    async function fetcherRedirects(to: string) {
      pingTarget = to
      const ping = hold("/app/alpha/ping")
      await act(async () => {
        void router.fetch("independent", "ping", "/app/alpha/ping")
      })
      await waitFor(() => expect(router.state.fetchers.get("independent")?.state).toBe("loading"))
      ping.release()
    }

    it("is not completed by an independent fetcher's redirect to another place", async () => {
      pingTarget = "/app/alpha/home"
      await start("/app/alpha/parties", "Parties")
      hold("/app/alpha/quests")
      await openDrawerAndClick("Quests")

      await fetcherRedirects("/app/alpha/home")
      await screen.findByRole("heading", { name: "Campaign Home" })

      expect(here()).toBe("/app/alpha/home")
      // The click never arrived: the drawer is still the person's, and nothing moved focus on its behalf.
      expect(drawerOpen()).toBe(true)
    })

    it("is not completed by an independent fetcher's redirect to the very address the click asked for", async () => {
      await start("/app/alpha/parties", "Parties")
      const quests = hold("/app/alpha/quests")
      await openDrawerAndClick("Quests")

      await fetcherRedirects("/app/alpha/quests")
      quests.release()
      await screen.findByRole("heading", { name: "Quests" })

      expect(here()).toBe("/app/alpha/quests")
      expect(drawerOpen()).toBe(true)
    })

    it("competing work that starts after the click and settles without redirecting still makes the owned redirect ambiguous", async () => {
      // The conservative policy, unchanged: the router offers no way to tell whose redirect a marked
      // location is once other work has been seen, even after that work has finished and redirected nothing.
      await start("/app/alpha/quests", "Quests")
      fireEvent.click(drawerToggle())
      expect(drawerOpen()).toBe(true)
      const sessions = hold("/app/alpha/sessions")
      fireEvent.click(inNav().getByRole("link", { name: "Sessions" }))
      await waitFor(() => expect(router.state.navigation.state).toBe("loading"))

      // After the click: an independent fetcher loads and settles, with no redirect of its own.
      const world = hold("/app/alpha/world")
      await act(async () => {
        void router.fetch("independent", "world", "/app/alpha/world")
      })
      await waitFor(() => expect(router.state.fetchers.get("independent")?.state).toBe("loading"))
      world.release()
      await waitFor(() => expect(router.state.fetchers.get("independent")?.state ?? "idle").toBe("idle"))
      expect(router.state.navigation.state).toBe("loading")

      // Now the click's own loader redirects.
      sessions.release()
      await screen.findByRole("heading", { name: "Parties" })

      expect(here()).toBe("/app/alpha/parties")
      expect(drawerOpen()).toBe(true)
    })

    it("still follows the click's own loader redirect while an unrelated fetcher is idle", async () => {
      await start("/app/alpha/quests", "Quests")
      await act(async () => {
        await router.fetch("settled", "ping", "/app/alpha/ping")
      })
      await waitFor(() => expect(router.state.fetchers.get("settled")?.state ?? "idle").toBe("idle"))
      await screen.findByRole("heading", { name: /Campaign Home|Quests/ })
      await go("/app/alpha/quests")
      fireEvent.click(drawerToggle())
      expect(drawerOpen()).toBe(true)

      fireEvent.click(inNav().getByRole("link", { name: "Sessions" }))
      await screen.findByRole("heading", { name: "Parties" })

      await waitFor(() => expect(drawerOpen()).toBe(false))
    })
  })

  it("does not take a failed navigation for completion", async () => {
    await start("/app/alpha/quests", "Quests")
    fireEvent.click(drawerToggle())
    expect(drawerOpen()).toBe(true)

    fireEvent.click(inNav().getByRole("link", { name: "Knowledge" }))

    await screen.findByRole("heading", { name: "Knowledge failed" })
    expect(here()).toBe("/app/alpha/knowledge")
    expect(drawerOpen()).toBe(true)
  })

  it("does not take a cancelled navigation for completion", async () => {
    await start("/app/alpha/parties", "Parties")
    const gate = hold("/app/alpha/quests")
    await openDrawerAndClick("Quests")

    // The in-flight navigation is abandoned for another place in the same scope; the click never arrived.
    await go("/app/alpha/home")
    gate.release()
    await screen.findByRole("heading", { name: "Campaign Home" })

    expect(here()).toBe("/app/alpha/home")
    expect(drawerOpen()).toBe(true)
  })

  it("lets a second action supersede the first: only the second closes the drawer, once", async () => {
    await start("/app/alpha/home", "Campaign Home")
    const first = hold("/app/alpha/quests")
    await openDrawerAndClick("Quests")

    // The second action, to a place that does not wait: it interrupts the first.
    fireEvent.click(inNav().getByRole("link", { name: "Parties" }))
    await screen.findByRole("heading", { name: "Parties" })
    first.release()

    expect(here()).toBe("/app/alpha/parties")
    await waitFor(() => expect(drawerOpen()).toBe(false))
    expect(screen.getByRole("heading", { name: "Parties" })).toHaveFocus()
    // The first request never arrives later and reopens or re-closes anything.
    await act(async () => {
      await Promise.resolve()
    })
    expect(here()).toBe("/app/alpha/parties")
  })

  it("a second menu action from the same menu supersedes the first", async () => {
    await start("/app/alpha/parties", "Parties")
    const first = hold("/app/alpha/characters/all")
    const disclosure = inNav().getByRole("button", { name: "Show characters menu" })
    activate(disclosure)
    fireEvent.click(await inNav().findByRole("link", { name: "All characters" }))
    await inFlight()

    fireEvent.click(inNav().getByRole("link", { name: /^Selected character/ }))
    await screen.findByRole("heading", { name: "Character record" })
    first.release()

    expect(here()).toBe("/app/alpha/characters/a1")
    await waitFor(() => expect(disclosure).toHaveAttribute("aria-expanded", "false"))
    expect(screen.getByRole("heading", { name: "Character record" })).toHaveFocus()
  })
})
