import { act, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { useState } from "react"
import { Link, Outlet, Route, RouterProvider, Routes, createMemoryRouter, useLocation } from "react-router"
import type { DataRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { RouteSessionProvider } from "../context/RouteSessionProvider"
import { usePageArrival } from "../hooks/usePageArrival"
import { navigationRegistryCounts } from "../hooks/navigationHolds"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import { AuthenticatedAppLayout } from "../layouts/AuthenticatedAppLayout"
import { CampaignSessionBoundary } from "../layouts/CampaignSessionBoundary"
import { WorldWorkspaceLayout } from "../layouts/WorldWorkspaceLayout"
import { ThemeProvider } from "../themes/ThemeProvider"
import type { CampaignContext, SessionBootstrap } from "../types/bootstrap"
import { ConfirmDialog } from "./authoring/ConfirmDialog"
import { WorldTimePicker } from "./authoring/WorldTimePicker"

// P02-4. The Campaign, World and Characters split controls and the menu / drawer / focus lifecycle, in
// the production tree: the authenticated shell with its sidebar and header, the scope-keyed session, the
// selected-context store, the real router, and real guarded pages (the page guard with its
// ConfirmDialog, and the world-time picker's own hold). Only the session bootstrap and fetch are faked.
//
// jsdom proves the DOM state it can: aria state, document.activeElement, the router's final location and
// its task / context state. It does not prove real browser focus visibility, a keyboard's native
// activation, touch, narrow-viewport layout or screen-reader output; those are the manual checks in
// docs/UI_DESIGN.md §4.8. A keyboard activation of a native button is the browser's own click with
// `detail: 0`, which is what the keyboard cases dispatch.

configure({ asyncUtilTimeout: 5000 })

const control = vi.hoisted(() => ({
  bootstrap: null as unknown,
  publish: null as null | ((bootstrap: unknown) => void),
}))

vi.mock("../hooks/useSessionBootstrap", async () => {
  const react = await import("react")
  return {
    useSessionBootstrap: () => {
      const [bootstrap, setBootstrap] = react.useState(control.bootstrap)
      control.publish = (next) => {
        control.bootstrap = next
        setBootstrap(next)
      }
      const refresh = react.useCallback(async () => true, [])
      const reload = react.useCallback(() => undefined, [])
      return { state: { status: "authenticated", bootstrap }, reload, refresh }
    },
  }
})

function campaign(
  id: string,
  world: string,
  perspectives: string[],
  selected: string | null,
  extra: Partial<CampaignContext> = {},
): CampaignContext {
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
    capabilities: ["canon.edit"],
    world_capabilities: ["world.view", "world.canon.read_private"],
    ...extra,
  }
}

function bootstrapOf(options: { withAlpha?: boolean; alphaCapabilities?: string[]; alphaWorld?: string[] } = {}): SessionBootstrap {
  const { withAlpha = true, alphaCapabilities = ["canon.edit", "access.manage"], alphaWorld = ["world.view", "world.canon.read_private"] } = options
  return {
    user: { user_id: "u1", display_name: "Gina" },
    csrf_token: "csrf",
    browser_session_id: "s1",
    system_roles: ["player"],
    global_capabilities: [],
    startup_campaign_id: "beta",
    campaign_preferences: { startup_mode: "resume_last_visited", preferred_campaign_id: null, last_visited_campaign_id: "beta" },
    campaigns: [
      ...(withAlpha
        ? [campaign("alpha", "w1", ["a1", "a2"], "a1", { capabilities: alphaCapabilities, world_capabilities: alphaWorld })]
        : []),
      campaign("beta", "w1", ["b1"], "b1"),
      campaign("gamma", "w2", [], null, { world_capabilities: [] }),
    ],
    features: { ask: false, ai_summaries: false, gm_briefs: false, cited_rules: false },
  }
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
}

const world = (id: string) => ({
  world_id: id,
  name: `World ${id}`,
  capabilities: ["world.view", "world.manage"],
  default_ruleset_id: null,
  allowed_rulesets: [],
  timelines: [{ timeline_id: `t-${id}`, name: `Timeline ${id}` }],
  managed_campaigns: [],
  available_actions: [],
  blocked_actions: [],
})

// A page as the real ones are: its heading takes focus on arrival.
function Page({ title, children }: { title: string; children?: React.ReactNode }) {
  const heading = usePageArrival(true)
  return (
    <main>
      <h1 ref={heading} tabIndex={-1}>
        {title}
      </h1>
      {children}
    </main>
  )
}

// A real guarded page: an unsaved draft is held by the page guard and asked about in a ConfirmDialog.
function DraftPage() {
  const [text, setText] = useState("")
  const guard = useUnsavedChangesGuard(text !== "")
  const location = useLocation()
  return (
    <Page title="New party">
      <p data-testid="path">{location.pathname}</p>
      <label>
        Draft
        <input value={text} onChange={(event) => setText(event.target.value)} />
      </label>
      <ConfirmDialog
        open={guard.blocked}
        title="Discard your draft?"
        description="unsent"
        confirmLabel="Leave"
        cancelLabel="Stay"
        onConfirm={guard.discard}
        onCancel={guard.stay}
      />
    </Page>
  )
}

// A page holding the real world-time picker, whose own hold and blocker take part in the one question.
function PickerPage() {
  const [when, setWhen] = useState("")
  return (
    <Page title="New session">
      <form aria-label="Session form">
        <WorldTimePicker campaignId="alpha" id="when" label="When" value={when} onChange={setWhen} />
      </form>
      <Link to="/campaigns">plain link</Link>
    </Page>
  )
}

let router: DataRouter

function tree(entry: string) {
  router = createMemoryRouter(
    [
      {
        path: "*",
        element: (
          <RouteSessionProvider>
            <Routes>
              <Route element={<AuthenticatedAppLayout />}>
                <Route path="/campaigns" element={<Page title="Campaigns" />} />
                <Route path="/settings" element={<Page title="Settings" />} />
                <Route element={<WorldWorkspaceLayout />}>
                  <Route path="/worlds/:worldId" element={<Page title="World page" />} />
                  <Route path="/worlds/:worldId/timelines" element={<Page title="Timelines" />} />
                </Route>
                <Route path="/worlds" element={<Page title="Worlds" />} />
                <Route path="/app/:campaignId" element={<CampaignSessionBoundary />}>
                  <Route path="home" element={<Page title="Campaign Home" />} />
                  <Route path="parties" element={<Page title="Parties" />} />
                  <Route path="parties/new" element={<DraftPage />} />
                  <Route path="sessions/new" element={<PickerPage />} />
                  <Route path="quests" element={<Page title="Quests" />} />
                  <Route path="world-times" element={<Page title="World time" />} />
                  <Route path="world" element={<Page title="Campaign world" />} />
                  <Route path="characters/all" element={<Page title="All characters" />} />
                  <Route path="characters/:characterId" element={<Page title="Character record" />} />
                </Route>
              </Route>
            </Routes>
            <Outlet />
          </RouteSessionProvider>
        ),
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

const mount = (entry: string) => render(tree(entry))

const CALENDAR = {
  calendar_id: "cal-1",
  code: "common",
  name: "Common Reckoning",
  description: null,
  days_per_week: 7,
  epoch_label: "Founding",
  months: [
    { month_number: 1, name: "Frost", day_count: 30 },
    { month_number: 2, name: "Bloom", day_count: 28 },
  ],
}

const posts: string[] = []
let postOutcome: "created" | "network-error" = "created"

beforeEach(() => {
  control.bootstrap = bootstrapOf()
  posts.length = 0
  postOutcome = "created"
  window.localStorage.clear()
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString()
      const method = init?.method ?? "GET"
      if (/\/campaigns\/[^/]+\/world-times/.test(url)) {
        if (method === "POST") {
          posts.push(url)
          if (postOutcome === "network-error") throw new TypeError("network down")
          return json({ world_time_id: "t9", created: true, changed: true }, 201)
        }
        return json({ items: [], next_cursor: null })
      }
      if (/\/campaigns\/[^/]+\/calendars/.test(url)) return json({ calendars: [CALENDAR] })
      const worldMatch = /\/worlds\/(w\d)$/.exec(url)
      if (worldMatch !== null) return json(world(worldMatch[1]!))
      if (/\/worlds\?/.test(url)) return json({ items: [], next_cursor: null })
      return json({ detail: "not found" }, 404)
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const nav = () => screen.getByRole("navigation", { name: "Main" })
const inNav = () => within(nav())
const here = () => router.state.location.pathname
const stateOf = () => router.state.location.state as { task?: { root?: string }; ctx?: unknown } | null
const go = async (to: string) => {
  await act(async () => {
    await router.navigate(to)
  })
}
const heading = (name: string) => screen.findByRole("heading", { name })
const campaignDisclosure = () => inNav().getByRole("button", { name: "Show campaign menu" })
const worldDisclosure = () => inNav().getByRole("button", { name: "Show world menu" })
const charactersDisclosure = () => inNav().getByRole("button", { name: "Show characters menu" })
// A pointer click: the browser focuses the control it is made on (jsdom does not), then clicks it.
const press = (element: HTMLElement) => {
  element.focus()
  fireEvent.pointerDown(element)
  fireEvent.click(element, { detail: 1 })
}
// A keyboard activation of a native button: focus is already there, and the click carries no pointer.
const activate = (element: HTMLElement) => {
  element.focus()
  fireEvent.click(element, { detail: 0 })
}
const question = () => screen.queryByRole("dialog", { name: "Discard your draft?" })
const typeDraft = (value = "unsent party") =>
  fireEvent.change(screen.getByRole("textbox", { name: "Draft" }), { target: { value } })

async function mountSettled(entry: string, title: string) {
  mount(entry)
  await heading(title)
}

describe("Campaign, World and Characters main controls: link, button and disclosure", () => {
  it("Campaign: a link to the selected campaign's Home away from it, a button at it, separate from the disclosure", async () => {
    await mountSettled("/app/alpha/parties", "Parties")

    const link = inNav().getByRole("link", { name: "Campaign: open Campaign alpha" })
    expect(link).toHaveAttribute("href", "/app/alpha/home")
    // The disclosure is its own control, never nested in the link.
    expect(link.contains(campaignDisclosure())).toBe(false)
    expect(campaignDisclosure()).toHaveAttribute("aria-expanded", "false")

    fireEvent.click(link)
    await heading("Campaign Home")
    expect(here()).toBe("/app/alpha/home")
    // The accepted link started a Campaign task.
    expect(stateOf()?.task?.root).toBe("campaign")

    // At the destination the same slot is a button that only toggles.
    expect(inNav().queryByRole("link", { name: /^Campaign: open/ })).toBeNull()
    const button = inNav().getByRole("button", { name: "Campaign menu" })
    expect(button).toHaveAttribute("aria-expanded", "false")
    activate(button)
    expect(button).toHaveAttribute("aria-expanded", "true")
    expect(here()).toBe("/app/alpha/home")
  })

  it("Campaign: with no selected campaign the main control is a button and nothing is guessed", async () => {
    await mountSettled("/settings", "Settings")

    expect(inNav().getByRole("button", { name: "Campaign menu" })).toBeInTheDocument()
    expect(inNav().queryByRole("link", { name: /^Campaign: open/ })).toBeNull()
    // Not the startup, last-visited or sole campaign: no campaign-scoped link at all.
    expect(inNav().queryByRole("link", { name: "Quests", hidden: true })).toBeNull()
    expect(inNav().queryByRole("link", { name: /^Characters: open/, hidden: true })).toBeNull()
    activate(campaignDisclosure())
    expect(inNav().getByRole("link", { name: "Campaign beta" })).toHaveAttribute("href", "/app/beta/home")
    expect(inNav().getByRole("link", { name: "View all campaigns" })).toHaveAttribute("href", "/campaigns")
  })

  it("World: a link to /worlds/:w for a viewable selected world, then a button inside the World task", async () => {
    await mountSettled("/app/alpha/parties", "Parties")

    const link = await inNav().findByRole("link", { name: "World: open World w1" })
    expect(link).toHaveAttribute("href", "/worlds/w1")
    fireEvent.click(link)
    await heading("World page")
    expect(here()).toBe("/worlds/w1")
    expect(stateOf()?.task?.root).toBe("world")
    expect(inNav().getByRole("button", { name: "World menu" })).toBeInTheDocument()
    expect(inNav().queryByRole("link", { name: /^World: open/ })).toBeNull()
  })

  it("World: falls back to the campaign world page without world.view, and offers nothing for an unknown world", async () => {
    control.bootstrap = bootstrapOf({ alphaWorld: [] })
    await mountSettled("/app/alpha/parties", "Parties")

    // No world.view: the campaign's own world page, not /worlds/w1.
    const link = await inNav().findByRole("link", { name: "World: open World w1" })
    expect(link).toHaveAttribute("href", "/app/alpha/world")
    expect(nav().innerHTML).not.toContain('href="/worlds/w1"')
  })

  it("Characters: a link to the selected character's record shell, a button when the page shown is that shell", async () => {
    await mountSettled("/app/alpha/parties", "Parties")

    const link = inNav().getByRole("link", { name: "Characters: open Name a1" })
    expect(link).toHaveAttribute("href", "/app/alpha/characters/a1")
    fireEvent.click(link)
    await heading("Character record")
    expect(here()).toBe("/app/alpha/characters/a1")
    expect(stateOf()?.task?.root).toBe("characters")
    expect(inNav().getByRole("button", { name: "Characters menu" })).toBeInTheDocument()
    expect(inNav().queryByRole("link", { name: /^Characters: open/ })).toBeNull()
  })

  it("Characters: an explicit choice of none makes the control a button; the viewed record is never a selection", async () => {
    await mountSettled("/app/alpha/characters/a2", "Character record")

    // Viewing a2 did not select it: the selection is still the server default a1.
    expect(inNav().queryByRole("link", { name: "Characters: open Name a2" })).toBeNull()
    // At a different place in another task the link is the selected one, a1.
    await go("/app/alpha/parties")
    expect(await inNav().findByRole("link", { name: "Characters: open Name a1" })).toHaveAttribute(
      "href",
      "/app/alpha/characters/a1",
    )

    fireEvent.change(screen.getByRole("combobox", { name: "Character perspective" }), { target: { value: "" } })
    await waitFor(() => expect(inNav().queryByRole("link", { name: /^Characters: open/ })).toBeNull())
    expect(inNav().getByRole("button", { name: "Characters menu" })).toBeInTheDocument()
    // The menu offers browsing, and no selected character.
    activate(charactersDisclosure())
    expect(inNav().getByRole("link", { name: "All characters" })).toHaveAttribute("href", "/app/alpha/characters/all")
    expect(inNav().getByText("Selected character", { selector: "[aria-disabled='true'] .portal-sidebar__label" })).toBeInTheDocument()
  })

  it("a revoked campaign leaves every control a button, with no stale link", async () => {
    await mountSettled("/app/alpha/parties", "Parties")
    await inNav().findByRole("link", { name: "World: open World w1" })
    await go("/campaigns")
    await heading("Campaigns")
    expect(inNav().getByRole("link", { name: "Campaign: open Campaign alpha" })).toBeInTheDocument()

    act(() => {
      control.publish?.(bootstrapOf({ withAlpha: false }))
    })

    await waitFor(() => expect(inNav().queryByRole("link", { name: /^(Campaign|World|Characters): open/ })).toBeNull())
    for (const name of ["Campaign menu", "World menu", "Characters menu"]) {
      expect(inNav().getByRole("button", { name })).toBeInTheDocument()
    }
    expect(nav().innerHTML).not.toContain("/app/alpha")
  })

  it("keeps a modified click and a new-tab open on the browser: no navigation, menu untouched", async () => {
    await mountSettled("/app/alpha/parties", "Parties")
    const link = inNav().getByRole("link", { name: "Campaign: open Campaign alpha" })

    fireEvent.click(link, { ctrlKey: true })
    fireEvent.click(link, { metaKey: true })
    fireEvent.click(link, { button: 1 })

    expect(here()).toBe("/app/alpha/parties")
    expect(campaignDisclosure()).toHaveAttribute("aria-expanded", "false")
  })
})

// The main control links to the authorized selected destination whenever the page shown is a different one,
// whatever task the person is in. It expands the menu only where it already is, or nothing applies.
describe("the primary action follows the selected record, not the task root", () => {
  const mainLinks = (href: string) =>
    inNav()
      .queryAllByRole("link")
      .filter((link) => link.getAttribute("href") === href && link.closest(".portal-sidebar__row") !== null)

  it("Characters: viewing a2 inside a Characters task with a1 selected offers navigation to a1", async () => {
    await mountSettled("/app/alpha/characters/a2", "Character record")
    // The task the page belongs to is Characters (route default root).
    expect(mainLinks("/app/alpha/characters/a1")).toHaveLength(1)
    expect(inNav().queryByRole("button", { name: "Characters menu" })).toBeNull()

    fireEvent.click(mainLinks("/app/alpha/characters/a1")[0]!)
    await waitFor(() => expect(here()).toBe("/app/alpha/characters/a1"))
    // Already at the selected destination: the same slot expands the menu instead.
    expect(await inNav().findByRole("button", { name: "Characters menu" })).toBeInTheDocument()
    expect(mainLinks("/app/alpha/characters/a1")).toHaveLength(0)
  })

  it("Characters: the record shell with a query is still the destination; a deeper route is not", async () => {
    await mountSettled("/app/alpha/characters/a1?section=notes", "Character record")
    expect(inNav().getByRole("button", { name: "Characters menu" })).toBeInTheDocument()
    expect(mainLinks("/app/alpha/characters/a1")).toHaveLength(0)
  })

  it("Campaign: inside a Campaign task on a page that is not Home offers navigation to Home", async () => {
    await mountSettled("/app/alpha/world-times", "World time")
    expect(mainLinks("/app/alpha/home")).toHaveLength(1)
    expect(inNav().queryByRole("button", { name: "Campaign menu" })).toBeNull()
  })

  it("World: inside a World task on another world page offers navigation to the world's details", async () => {
    await mountSettled("/worlds/w1/timelines", "Timelines")
    await waitFor(() => expect(mainLinks("/worlds/w1")).toHaveLength(1))
    expect(inNav().queryByRole("button", { name: "World menu" })).toBeNull()

    fireEvent.click(mainLinks("/worlds/w1")[0]!)
    await heading("World page")
    expect(inNav().getByRole("button", { name: "World menu" })).toBeInTheDocument()
  })

  it("the disclosure stays available whichever the main control is", async () => {
    await mountSettled("/app/alpha/characters/a2", "Character record")
    for (const name of ["Show campaign menu", "Show world menu", "Show characters menu"]) {
      expect(inNav().getByRole("button", { name })).toHaveAttribute("aria-expanded")
    }
  })
})

describe("the main control's accessible name contains its visible label", () => {
  const labels = ["Campaign", "World", "Characters"]

  it.each([
    ["a link (away from the destination)", "/app/alpha/parties/new", "Parties"],
    ["a button (at the destination)", "/campaigns", "Campaigns"],
  ])("in every split group when it is %s", async (_state, entry, title) => {
    await mountSettled(entry === "/campaigns" ? entry : "/app/alpha/parties", entry === "/campaigns" ? title : "Parties")
    const rows = Array.from(nav().querySelectorAll<HTMLElement>(".portal-sidebar__split-group > .portal-sidebar__row"))
    expect(rows).toHaveLength(3)
    for (const row of rows) {
      const main = row.querySelector<HTMLElement>("[data-menu-control='main']")!
      const visible = main.querySelector(".portal-sidebar__label")!.textContent!
      expect(labels).toContain(visible)
      expect(main).toHaveAccessibleName(expect.stringContaining(visible))
      // The disclosure is a different control with a different name.
      const disclosure = row.querySelector<HTMLElement>("[data-menu-control='disclosure']")!
      expect(disclosure).toHaveAccessibleName(`Show ${visible.toLowerCase()} menu`)
      expect(main).not.toHaveAccessibleName(`Show ${visible.toLowerCase()} menu`)
    }
  })

  it("keeps expanded state accurate on both controls when the main control is a button", async () => {
    await mountSettled("/campaigns", "Campaigns")
    const main = inNav().getByRole("button", { name: "World menu" })
    const disclosure = worldDisclosure()
    expect(main).toHaveAttribute("aria-expanded", "false")
    activate(disclosure)
    expect(main).toHaveAttribute("aria-expanded", "true")
    expect(disclosure).toHaveAttribute("aria-expanded", "true")
    expect(main).toHaveAttribute("aria-controls", disclosure.getAttribute("aria-controls"))
  })
})

describe("menu lifecycle: open, close and focus (pointer and keyboard alike)", () => {
  it.each([
    ["pointer", press],
    ["keyboard", activate],
  ])("opening by %s moves focus to the first enabled item, from either control", async (_name, open) => {
    await mountSettled("/campaigns", "Campaigns")

    // The disclosure.
    open(worldDisclosure())
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "true")
    await waitFor(() => expect(inNav().getByRole("link", { name: "All worlds" })).toHaveFocus())

    // And the main control, which here is a button (nothing applicable is selected), opens it the same way.
    open(worldDisclosure())
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "false")
    const main = inNav().getByRole("button", { name: "World menu" })
    open(main)
    expect(main).toHaveAttribute("aria-expanded", "true")
    await waitFor(() => expect(inNav().getByRole("link", { name: "All worlds" })).toHaveFocus())
  })

  it("skips a disabled first item and focuses the first enabled one", async () => {
    await mountSettled("/settings", "Settings")

    // No campaign: Campaign Home is the disabled first entry; the first enabled one is a campaign.
    activate(campaignDisclosure())
    await waitFor(() => expect(inNav().getByRole("link", { name: "Campaign alpha" })).toHaveFocus())
  })

  it("does not take focus when a menu starts open for the route", async () => {
    await mountSettled("/campaigns", "Campaigns")

    expect(campaignDisclosure()).toHaveAttribute("aria-expanded", "true")
    expect(inNav().getByRole("link", { name: "View all campaigns" })).not.toHaveFocus()
    expect(screen.getByRole("heading", { name: "Campaigns" })).toHaveFocus()
  })

  it.each([
    ["disclosure", () => worldDisclosure()],
    ["main control", () => inNav().getByRole("button", { name: "World menu" })],
  ])("Escape closes the menu and returns focus to the actual opener (%s)", async (_name, opener) => {
    await mountSettled("/campaigns", "Campaigns")
    const control = opener()
    activate(control)
    const first = await inNav().findByRole("link", { name: "All worlds" })
    await waitFor(() => expect(first).toHaveFocus())

    fireEvent.keyDown(first, { key: "Escape" })

    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "false")
    expect(control).toHaveFocus()
  })

  it("closing with the same control keeps focus on it", async () => {
    await mountSettled("/campaigns", "Campaigns")
    activate(worldDisclosure())
    activate(worldDisclosure())
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "false")
    expect(worldDisclosure()).toHaveFocus()
  })

  it("an outside pointer-down and a Tab out close the menu without moving focus", async () => {
    await mountSettled("/campaigns", "Campaigns")
    // Any control outside the group: the header's navigation toggle.
    const outside = screen.getByRole("button", { name: /(Open|Close) navigation/ })

    activate(worldDisclosure())
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "true")
    fireEvent.pointerDown(screen.getByRole("heading", { name: "Campaigns" }))
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "false")

    activate(worldDisclosure())
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "true")
    act(() => outside.focus())
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "false")
    // The new target keeps focus; nothing pulled it back.
    expect(outside).toHaveFocus()
  })

  it("an accepted child navigation closes its menu and focuses the new page's heading; the click alone did not", async () => {
    await mountSettled("/campaigns", "Campaigns")
    activate(worldDisclosure())
    const child = await inNav().findByRole("link", { name: "All worlds" })
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "true")

    fireEvent.click(child)

    await heading("Worlds")
    expect(here()).toBe("/worlds")
    await waitFor(() => expect(worldDisclosure()).toHaveAttribute("aria-expanded", "false"))
    await waitFor(() => expect(screen.getByRole("heading", { name: "Worlds" })).toHaveFocus())
  })

  it("a stamp-only REPLACE neither closes a menu nor moves focus", async () => {
    await mountSettled("/app/alpha/parties", "Parties")
    activate(worldDisclosure())
    const first = await inNav().findByRole("link", { name: "All worlds" })
    await waitFor(() => expect(first).toHaveFocus())
    const before = router.state.location

    await act(async () => {
      await router.navigate(
        { pathname: before.pathname, search: before.search },
        { replace: true, state: { ...(before.state as object), ctx: { v: 1, characterId: "a1" } }, preventScrollReset: true },
      )
    })

    expect(router.state.location.key).not.toBe(before.key)
    expect(here()).toBe("/app/alpha/parties")
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "true")
    expect(first).toHaveFocus()
  })

  it("keeps Knowledge, Items and Access on the same rules: opener Escape, outside close, accepted-only close", async () => {
    await mountSettled("/app/alpha/parties", "Parties")
    const items = inNav().getByRole("button", { name: "Items" })

    activate(items)
    const inventory = await inNav().findByRole("link", { name: "Inventory" })
    await waitFor(() => expect(inventory).toHaveFocus())
    fireEvent.keyDown(inventory, { key: "Escape" })
    expect(items).toHaveAttribute("aria-expanded", "false")
    expect(items).toHaveFocus()

    activate(items)
    fireEvent.pointerDown(screen.getByRole("heading", { name: "Parties" }))
    expect(items).toHaveAttribute("aria-expanded", "false")
  })
})

describe("the unsaved-changes question and the menu (CTX-4)", () => {
  async function dirtyDraft(entry = "/app/alpha/parties/new") {
    await mountSettled(entry, "New party")
    typeDraft()
  }

  it("a dirty menu child keeps the menu open through the question; Stay restores focus to that child and keeps the draft", async () => {
    await dirtyDraft()
    activate(worldDisclosure())
    const child = await inNav().findByRole("link", { name: "All worlds" })
    await waitFor(() => expect(child).toHaveFocus())

    fireEvent.click(child)

    await screen.findByRole("dialog", { name: "Discard your draft?" })
    // The click did not close anything; the question is the only modal.
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "true")
    expect(here()).toBe("/app/alpha/parties/new")
    expect(screen.getAllByRole("dialog")).toHaveLength(1)

    fireEvent.click(screen.getByRole("button", { name: "Stay" }))

    await waitFor(() => expect(question()).toBeNull())
    expect(here()).toBe("/app/alpha/parties/new")
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "true")
    expect(child).toHaveFocus()
    expect(screen.getByRole("textbox", { name: "Draft" })).toHaveValue("unsent party")
    expect(navigationRegistryCounts().questions).toBe(0)
  })

  it("ignores blur and outside pointer dismissal while the question owns the screen, and does not steal its focus", async () => {
    await dirtyDraft()
    activate(worldDisclosure())
    const child = await inNav().findByRole("link", { name: "All worlds" })
    fireEvent.click(child)
    const dialog = await screen.findByRole("dialog", { name: "Discard your draft?" })
    const stay = within(dialog).getByRole("button", { name: "Stay" })
    await waitFor(() => expect(stay).toHaveFocus())

    // Focus moved into the dialog (a blur from the child), and a press outside the menu landed there.
    fireEvent.pointerDown(dialog)
    fireEvent.pointerDown(screen.getByRole("textbox", { name: "Draft" }))
    fireEvent.blur(child, { relatedTarget: stay })

    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "true")
    expect(stay).toHaveFocus()
  })

  it("Leave completes the navigation: final route, task started, heading focused, menu closed", async () => {
    await dirtyDraft()
    activate(worldDisclosure())
    // Within the same campaign scope, so the sidebar is not remounted by the move (a remount would
    // reopen a menu whose section the new route is in, which is the separate initial-render rule).
    fireEvent.click(await inNav().findByRole("link", { name: "Campaign world" }))
    await screen.findByRole("dialog", { name: "Discard your draft?" })
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "true")

    fireEvent.click(screen.getByRole("button", { name: "Leave" }))

    await heading("Campaign world")
    expect(here()).toBe("/app/alpha/world")
    await waitFor(() => expect(worldDisclosure()).toHaveAttribute("aria-expanded", "false"))
    await waitFor(() => expect(screen.getByRole("heading", { name: "Campaign world" })).toHaveFocus())
    expect(stateOf()?.task?.root).toBe("world")
  })

  it("the main control as a link is guarded like any link: Stay keeps the page, Leave starts the task", async () => {
    await dirtyDraft()
    const link = inNav().getByRole("link", { name: "Campaign: open Campaign alpha" })

    fireEvent.click(link)
    await screen.findByRole("dialog", { name: "Discard your draft?" })
    fireEvent.click(screen.getByRole("button", { name: "Stay" }))
    await waitFor(() => expect(question()).toBeNull())
    expect(here()).toBe("/app/alpha/parties/new")
    expect(screen.getByRole("textbox", { name: "Draft" })).toHaveValue("unsent party")

    fireEvent.click(link)
    await screen.findByRole("dialog", { name: "Discard your draft?" })
    fireEvent.click(screen.getByRole("button", { name: "Leave" }))
    await heading("Campaign Home")
    expect(here()).toBe("/app/alpha/home")
    expect(stateOf()?.task?.root).toBe("campaign")
  })

  it("opening a menu or the disclosure with a dirty form asks nothing and changes nothing", async () => {
    await dirtyDraft()
    activate(campaignDisclosure())
    activate(charactersDisclosure())
    expect(question()).toBeNull()
    expect(screen.getByRole("textbox", { name: "Draft" })).toHaveValue("unsent party")
    expect(here()).toBe("/app/alpha/parties/new")
  })

  it("Stay with the activated control gone falls back to the menu opener", async () => {
    await dirtyDraft()
    activate(inNav().getByRole("button", { name: "Items" }))
    const definitions = await inNav().findByRole("link", { name: "Definitions" })
    act(() => definitions.focus())
    fireEvent.click(definitions)
    await screen.findByRole("dialog", { name: "Discard your draft?" })

    // While the question is open the server stops listing the child (the menu item is replaced).
    act(() => {
      control.publish?.(bootstrapOf({ alphaWorld: ["world.view"] }))
    })
    await waitFor(() => expect(definitions.isConnected).toBe(false))
    fireEvent.click(screen.getByRole("button", { name: "Stay" }))

    await waitFor(() => expect(question()).toBeNull())
    expect(inNav().getByRole("button", { name: "Items" })).toHaveAttribute("aria-expanded", "true")
    expect(inNav().getByRole("button", { name: "Items" })).toHaveFocus()
    expect(here()).toBe("/app/alpha/parties/new")
  })
})

describe("the drawer", () => {
  const toggle = () => screen.getByRole("button", { name: /(Open|Close) navigation/ })
  const drawerOpen = () => nav().classList.contains("portal-sidebar--mobile-open")

  async function openDrawerWithDraft() {
    await mountSettled("/app/alpha/parties/new", "New party")
    typeDraft()
    fireEvent.click(toggle())
    expect(drawerOpen()).toBe(true)
  }

  it("a navigation click keeps the drawer open through the question; Stay leaves drawer and menu as they were", async () => {
    await openDrawerWithDraft()
    activate(worldDisclosure())
    const child = await inNav().findByRole("link", { name: "All worlds" })

    fireEvent.click(child)
    await screen.findByRole("dialog", { name: "Discard your draft?" })
    expect(drawerOpen()).toBe(true)
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "true")

    // Escape in the question means Stay and must not close the drawer behind it.
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" })
    fireEvent(screen.getByRole("dialog", { name: "Discard your draft?" }), new Event("cancel", { cancelable: true }))

    await waitFor(() => expect(question()).toBeNull())
    expect(drawerOpen()).toBe(true)
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "true")
    expect(child).toHaveFocus()
    expect(here()).toBe("/app/alpha/parties/new")
  })

  it("Leave closes the drawer and the menu together once the location has changed", async () => {
    await openDrawerWithDraft()
    activate(worldDisclosure())
    fireEvent.click(await inNav().findByRole("link", { name: "Campaign world" }))
    await screen.findByRole("dialog", { name: "Discard your draft?" })

    fireEvent.click(screen.getByRole("button", { name: "Leave" }))

    await heading("Campaign world")
    expect(here()).toBe("/app/alpha/world")
    await waitFor(() => expect(drawerOpen()).toBe(false))
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "false")
    await waitFor(() => expect(screen.getByRole("heading", { name: "Campaign world" })).toHaveFocus())
  })

  it("a plain link closes the drawer on acceptance only", async () => {
    await openDrawerWithDraft()
    const parties = inNav().getByRole("link", { name: "Parties" })
    fireEvent.click(parties)
    await screen.findByRole("dialog", { name: "Discard your draft?" })
    expect(drawerOpen()).toBe(true)
    fireEvent.click(screen.getByRole("button", { name: "Stay" }))
    await waitFor(() => expect(question()).toBeNull())
    expect(drawerOpen()).toBe(true)
    expect(here()).toBe("/app/alpha/parties/new")
  })

  it("Stay with the whole group gone falls back to the drawer toggle", async () => {
    await openDrawerWithDraft()
    activate(inNav().getByRole("button", { name: "Access" }))
    const access = await inNav().findByRole("link", { name: "Access Management" })
    act(() => access.focus())
    fireEvent.click(access)
    await screen.findByRole("dialog", { name: "Discard your draft?" })

    act(() => {
      control.publish?.(bootstrapOf({ alphaCapabilities: ["canon.edit"] }))
    })
    await waitFor(() => expect(access.isConnected).toBe(false))
    fireEvent.click(screen.getByRole("button", { name: "Stay" }))

    await waitFor(() => expect(question()).toBeNull())
    expect(drawerOpen()).toBe(true)
    expect(toggle()).toHaveFocus()
    expect(here()).toBe("/app/alpha/parties/new")
  })

  it("Escape with a menu open closes the menu and leaves the drawer; a second Escape closes the drawer to the toggle", async () => {
    await mountSettled("/campaigns", "Campaigns")
    fireEvent.click(toggle())
    activate(worldDisclosure())
    const first = await inNav().findByRole("link", { name: "All worlds" })

    fireEvent.keyDown(first, { key: "Escape" })
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "false")
    expect(drawerOpen()).toBe(true)

    fireEvent.keyDown(document, { key: "Escape" })
    expect(drawerOpen()).toBe(false)
    expect(toggle()).toHaveFocus()
  })
})

describe("the world-time picker's hold takes part in the same question", () => {
  async function openPickerAndFill() {
    await mountSettled("/app/alpha/sessions/new", "New session")
    const trigger = (await screen.findAllByRole("button", { name: "Record a new time" }))[0]!
    fireEvent.click(trigger)
    const dialog = await screen.findByRole("dialog", { name: "Record a world time" })
    fireEvent.change(within(dialog).getByRole("textbox", { name: /Year/ }), { target: { value: "3" } })
    return dialog
  }

  it("a dirty picker draft holds a menu navigation: one question, menu open, Stay keeps the draft and the route", async () => {
    const dialog = await openPickerAndFill()
    activate(worldDisclosure())
    const child = await inNav().findByRole("link", { name: "All worlds", hidden: true })

    fireEvent.click(child)

    // The picker's own blocker asks inside its open dialog: still the one question on screen.
    await within(dialog).findByText(/You have entered a time that has not been recorded/)
    expect(screen.getAllByRole("dialog")).toHaveLength(1)
    expect(here()).toBe("/app/alpha/sessions/new")
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "true")
    // A press outside the menu while it asks does not dismiss the menu.
    fireEvent.pointerDown(dialog)
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "true")
    fireEvent.click(within(dialog).getByRole("button", { name: "Stay" }))

    await waitFor(() => expect(within(dialog).queryByText(/You have entered a time/)).toBeNull())
    expect(here()).toBe("/app/alpha/sessions/new")
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "true")
    expect(within(dialog).getByRole("textbox", { name: /Year/ })).toHaveValue("3")
    expect(navigationRegistryCounts().questions).toBe(0)
  })

  it("an uncertain write keeps the question and the recovery path: Stay leaves the retry available", async () => {
    postOutcome = "network-error"
    const dialog = await openPickerAndFill()
    fireEvent.change(within(dialog).getByRole("combobox", { name: "Month" }), { target: { value: "2" } })
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Day" }), { target: { value: "5" } })
    fireEvent.click(within(dialog).getByRole("button", { name: "Record time" }))
    await within(dialog).findByText(/cannot tell whether this was saved/)
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
    fireEvent.click(within(dialog).getByRole("button", { name: "Close and check later" }))

    activate(worldDisclosure())
    fireEvent.click(await inNav().findByRole("link", { name: "All worlds" }))
    const ask = await screen.findByRole("dialog", { name: "Leave this page?" })
    expect(ask).toHaveAccessibleDescription(/may already have been recorded/)
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "true")
    fireEvent.click(within(ask).getByRole("button", { name: "Stay" }))

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(here()).toBe("/app/alpha/sessions/new")
    expect(worldDisclosure()).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByRole("button", { name: "Reopen to retry" })).toBeInTheDocument()
    expect(posts).toHaveLength(1)
  })
})
