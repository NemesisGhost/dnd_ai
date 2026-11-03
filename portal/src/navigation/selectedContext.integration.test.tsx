import { act, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { StrictMode, useState } from "react"
import { Link, Outlet, Route, RouterProvider, Routes, createMemoryRouter, useLocation } from "react-router"
import type { DataRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import { RouteSessionProvider } from "../context/RouteSessionProvider"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import { AuthenticatedAppLayout } from "../layouts/AuthenticatedAppLayout"
import { CampaignSessionBoundary } from "../layouts/CampaignSessionBoundary"
import { WorldWorkspaceLayout } from "../layouts/WorldWorkspaceLayout"
import { ThemeProvider } from "../themes/ThemeProvider"
import type { CampaignContext, SessionBootstrap } from "../types/bootstrap"
import { useBreadcrumbLabel, useBreadcrumbLabelReader } from "./BreadcrumbLabelContext"

// P02-3. The retained selection (this tab's explicit choice) and the route (what a page reads and
// writes) are different things, and the route wins. Everything here is the production tree: the
// selected-context store above the scope-keyed session, the authenticated shell with its sidebar and
// Infobox, the campaign and world layouts, the guards and the router. Only the session bootstrap and
// fetch are faked, and page reads are deferred where the order of answers is the point.

configure({ asyncUtilTimeout: 5000 })

const control = vi.hoisted(() => ({
  bootstrap: null as unknown,
  publish: null as null | ((bootstrap: unknown) => void),
  refreshes: 0,
}))

vi.mock("../hooks/useSessionBootstrap", async () => {
  const react = await import("react")
  return {
    useSessionBootstrap: () => {
      // Each scope mount starts from what the server last said, as a fresh bootstrap read would.
      const [bootstrap, setBootstrap] = react.useState(control.bootstrap)
      control.publish = (next) => {
        control.bootstrap = next
        setBootstrap(next)
      }
      const refresh = react.useCallback(async () => {
        control.refreshes += 1
        return true
      }, [])
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
    capabilities: ["access.manage"],
  }
}

interface Shape {
  alpha?: string[]
  alphaDefault?: string | null
  withAlpha?: boolean
  beta?: string[]
}
function bootstrapOf({ alpha = ["a1", "a2"], alphaDefault = null, withAlpha = true, beta = ["b1"] }: Shape = {}): SessionBootstrap {
  return {
    user: { user_id: "u1", display_name: "Gina" },
    csrf_token: "csrf",
    browser_session_id: "s1",
    system_roles: ["player"],
    global_capabilities: [],
    startup_campaign_id: "beta",
    campaign_preferences: { startup_mode: "resume_last_visited", preferred_campaign_id: null, last_visited_campaign_id: "beta" },
    campaigns: [
      ...(withAlpha ? [campaign("alpha", "w1", alpha, alphaDefault)] : []),
      campaign("beta", "w1", beta, "b1"),
      campaign("gamma", "w2", [], null),
    ],
    features: { ask: false, ai_summaries: false, gm_briefs: false, cited_rules: false },
  }
}

const requests: string[] = []
const probes = () => requests.filter((url) => url.includes("/probe?")).map((url) => url.replace(/^.*\/campaigns\//, ""))
// Reads that are parked until the test answers them (in the order the requests were made).
const parked: Array<{ url: string; answer: (who: string) => Promise<void> }> = []
let parkProbes = false

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

interface Label {
  who: string
}

function NotesPage() {
  const { getSelectedCharacterId } = usePerspective()
  const campaignId = useLocation().pathname.split("/")[2]!
  const perspective = getSelectedCharacterId(campaignId) ?? ""
  const [text, setText] = useState("")
  const guard = useUnsavedChangesGuard(text !== "")
  const read = useAuthoringResource<Label>(`/campaigns/${campaignId}/probe?character_id=${perspective}`)
  useBreadcrumbLabel({
    route: "parties.detail",
    params: { campaignId, partyId: "p1" },
    name: read.state.kind === "ready" ? read.state.data.who : null,
    authority: read.authority,
  })
  const labelFor = useBreadcrumbLabelReader()
  return (
    <div>
      <h1>Notes</h1>
      <p data-testid="read">{read.state.kind === "ready" ? `ready:${campaignId}:${read.state.data.who}` : read.state.kind}</p>
      <p data-testid="label">{labelFor("parties.detail", { campaignId, partyId: "p1" }) ?? "generic"}</p>
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
    </div>
  )
}

function CampaignsPage() {
  return (
    <main>
      <h1>Campaigns</h1>
      <Link to="/app/alpha/notes">to alpha</Link>
      <Link to="/app/beta/notes">to beta</Link>
    </main>
  )
}

function WorldPage() {
  return <h1>World page</h1>
}

let router: DataRouter

function tree(entry: string | { pathname: string; state?: unknown }) {
  router = createMemoryRouter(
    [
      {
        path: "*",
        element: (
          <RouteSessionProvider>
            <Routes>
              <Route element={<AuthenticatedAppLayout />}>
                <Route path="/campaigns" element={<CampaignsPage />} />
                <Route element={<WorldWorkspaceLayout />}>
                  <Route path="/worlds/:worldId" element={<WorldPage />} />
                </Route>
                <Route path="/app/:campaignId" element={<CampaignSessionBoundary />}>
                  <Route path="notes" element={<NotesPage />} />
                  {/* Where a deliberate perspective change lands (PD-6); the same probe page reads under it. */}
                  <Route path="characters/:characterId" element={<NotesPage />} />
                  <Route path="characters/all" element={<NotesPage />} />
                  <Route path="other" element={<h1>Other</h1>} />
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

function mount(entry: string | { pathname: string; state?: unknown } = "/app/alpha/notes", strict = false) {
  const element = tree(entry)
  return render(strict ? <StrictMode>{element}</StrictMode> : element)
}

beforeEach(() => {
  requests.length = 0
  parked.length = 0
  parkProbes = false
  control.refreshes = 0
  control.bootstrap = bootstrapOf()
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString()
      requests.push(url)
      const probe = /\/probe\?character_id=([^&]*)/.exec(url)
      if (probe !== null) {
        const who = decodeURIComponent(probe[1]!)
        if (!parkProbes) return json({ who })
        return new Promise<Response>((resolve) => {
          parked.push({
            url,
            answer: async (answer) => {
              await act(async () => {
                resolve(json({ who: answer }))
                await Promise.resolve()
              })
            },
          })
        })
      }
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

const select = () => screen.getByRole("combobox", { name: "Character perspective" }) as HTMLSelectElement
const choose = (value: string) => fireEvent.change(select(), { target: { value } })
const nav = () => screen.getByRole("navigation", { name: "Main" })
const quests = () => within(nav()).queryByRole("link", { name: "Quests" })
const go = async (to: string | number) => {
  await act(async () => {
    await router.navigate(to as string)
  })
}
const goBack = async () => {
  await act(async () => {
    await router.navigate(-1)
  })
}
const ready = (campaignId: string, who: string) =>
  waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent(`ready:${campaignId}:${who}`))
const campaignSelect = () => screen.getByRole("combobox", { name: /^(Selected campaign|Campaign)$/ }) as HTMLSelectElement

describe.each([
  ["plain", false],
  ["StrictMode", true],
])("the route governs; the retained selection only informs navigation (%s)", (_name, strict) => {
  it("keeps the selected campaign across an unscoped page and targets it, and guesses nothing without one", async () => {
    mount("/app/alpha/notes", strict)
    await ready("alpha", "")
    choose("a2")
    await ready("alpha", "a2")
    await go("/campaigns")
    await screen.findByRole("heading", { name: "Campaigns" })
    // The explicit selection, not the startup/last-visited campaign (beta).
    await waitFor(() => expect(quests()).toHaveAttribute("href", "/app/alpha/quests"))
  })

  it("shows no campaign links at all when nothing was selected, whatever the saved preferences say", async () => {
    mount("/campaigns", strict)
    await screen.findByRole("heading", { name: "Campaigns" })
    expect(quests()).toBeNull()
    expect(nav().innerHTML).not.toContain("/app/beta/quests")
  })

  it("lets the route campaign replace a retained other campaign before anything reads under it", async () => {
    mount("/app/alpha/notes", strict)
    await ready("alpha", "")
    choose("a2")
    await ready("alpha", "a2")
    requests.length = 0

    await go("/app/beta/notes")
    await ready("beta", "b1")
    // Beta's own default initializes its perspective; alpha's a2 never reaches a beta request.
    expect(select()).toHaveValue("b1")
    expect(probes().filter((p) => p.startsWith("beta/"))).toEqual(
      expect.arrayContaining(["beta/probe?character_id=b1"]),
    )
    expect(probes().some((p) => p.startsWith("beta/") && p.includes("a2"))).toBe(false)
    expect(probes().some((p) => p.startsWith("beta/") && p.endsWith("character_id="))).toBe(false)

    // And beta is now what the tab has selected.
    await go("/campaigns")
    await waitFor(() => expect(quests()).toHaveAttribute("href", "/app/beta/quests"))
  })

  it("makes a route campaign with no perspective the selected campaign too, not only one with a default", async () => {
    mount("/app/beta/notes", strict)
    await ready("beta", "b1")
    await go("/app/alpha/notes")
    await ready("alpha", "")
    expect(select()).toHaveValue("")
    await go("/campaigns")
    // Beta's b1 was replaced when alpha, which has no default perspective, became the route's campaign.
    await waitFor(() => expect(quests()).toHaveAttribute("href", "/app/alpha/quests"))
  })

  it("A → B → A by link does not bring the old perspective back; Back to the A entry does (through its stamp)", async () => {
    mount("/app/alpha/notes", strict)
    await ready("alpha", "")
    choose("a2")
    await ready("alpha", "a2")
    await go("/app/beta/notes")
    await ready("beta", "b1")

    await go("/app/alpha/notes")
    await ready("alpha", "")
    expect(select()).toHaveValue("")

    // History: the entry that recorded a2 restores it, validated.
    await goBack() // beta
    await ready("beta", "b1")
    await goBack() // alpha, the entry stamped a2
    await ready("alpha", "a2")
    expect(select()).toHaveValue("a2")
  })

  it("keeps an explicit choice of no perspective, and an initialized default, across an unscoped page", async () => {
    control.bootstrap = bootstrapOf({ alphaDefault: "a1" })
    mount("/app/alpha/notes", strict)
    await ready("alpha", "a1")
    expect(select()).toHaveValue("a1")
    await go("/campaigns")
    await go("/app/alpha/notes")
    await ready("alpha", "a1")

    choose("")
    await ready("alpha", "")
    await go("/campaigns")
    await go("/app/alpha/notes")
    await ready("alpha", "")
    // The server default (a1) never replaces what was chosen.
    expect(select()).toHaveValue("")
    expect(probes().at(-1)).toBe("alpha/probe?character_id=")
  })
})

describe("initial entry, reload and the entry's own context", () => {
  const stamp = (campaignId: string, characterId: string | null) => ({
    v: 1,
    campaignId,
    worldId: "w1",
    timelineId: "t-w1",
    characterId,
  })
  const ctx = () => (router.state.location.state as { ctx?: unknown } | null)?.ctx

  it("reload restores the stamped perspective before any page reads under the default", async () => {
    mount({ pathname: "/app/alpha/notes", state: { ctx: stamp("alpha", "a2") } })
    await ready("alpha", "a2")
    expect(probes()).toEqual(["alpha/probe?character_id=a2"])
    expect(select()).toHaveValue("a2")
  })

  it("keeps unrelated router state beside the stamp it writes", async () => {
    mount({ pathname: "/app/alpha/notes", state: { task: { v: 1 }, keep: "me" } })
    await ready("alpha", "")
    await waitFor(() => expect(ctx()).toEqual(stamp("alpha", null)))
    expect(router.state.location.state).toMatchObject({ task: { v: 1 }, keep: "me" })
    expect(router.state.historyAction).toBe("REPLACE")
  })

  it("ignores a stamp made under another campaign, replaces it, and never reads under its character", async () => {
    mount({ pathname: "/app/alpha/notes", state: { ctx: stamp("beta", "b1") } })
    await ready("alpha", "")
    await waitFor(() => expect(ctx()).toEqual(stamp("alpha", null)))
    expect(probes()).toEqual(["alpha/probe?character_id="])
  })

  it("ignores a stamp naming another world or timeline of this route", async () => {
    mount({ pathname: "/app/alpha/notes", state: { ctx: { ...stamp("alpha", "a2"), worldId: "w9" } } })
    await ready("alpha", "")
    await waitFor(() => expect(ctx()).toEqual(stamp("alpha", null)))
  })

  it.each([
    ["a string", "x"],
    ["an array", []],
    ["a wrong version", { v: 2, characterId: "a2" }],
    ["a partial form", { v: 1, campaignId: "alpha", characterId: "a2" }],
    ["an unauthorized perspective", stamp("alpha", "someone-else")],
    ["a mistyped id", { ...stamp("alpha", "a2"), campaignId: 7 }],
  ])("falls back to the default and repairs %s", async (_name, bad) => {
    mount({ pathname: "/app/alpha/notes", state: { ctx: bad } })
    await ready("alpha", "")
    await waitFor(() => expect(ctx()).toEqual(stamp("alpha", null)))
    expect(probes()).toEqual(["alpha/probe?character_id="])
  })

  it("honors and upgrades the older perspective-only stamp", async () => {
    mount({ pathname: "/app/alpha/notes", state: { ctx: { v: 1, characterId: "a2" } } })
    await ready("alpha", "a2")
    await waitFor(() => expect(ctx()).toEqual(stamp("alpha", "a2")))
    expect(router.state.historyAction).toBe("REPLACE")
    expect(probes()).toEqual(["alpha/probe?character_id=a2"])
  })

  it("a legacy entry with no stamp uses the bootstrap default and a direct entry selects the route campaign", async () => {
    control.bootstrap = bootstrapOf({ alphaDefault: "a1" })
    mount("/app/alpha/notes")
    await ready("alpha", "a1")
    await go("/campaigns")
    await waitFor(() => expect(quests()).toHaveAttribute("href", "/app/alpha/quests"))
  })
})

describe("a retained selection and a guarded departure", () => {
  const typeDraft = async () => {
    await ready("alpha", "a2")
    fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "half a thought" } })
  }

  it("Stay leaves selection, route, draft and reads untouched; Leave commits the route campaign", async () => {
    mount("/app/alpha/notes")
    await ready("alpha", "")
    choose("a2")
    await typeDraft()
    requests.length = 0
    control.refreshes = 0

    void router.navigate("/app/beta/notes")
    const dialog = await screen.findByRole("dialog", { name: "Discard your draft?" })
    fireEvent.click(within(dialog).getByRole("button", { name: "Stay" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    // (choosing a2 is a departure to a2's Characters details, PD-6; Stay keeps the page it was on.)
    expect(router.state.location.pathname).toBe("/app/alpha/characters/a2")
    expect(select()).toHaveValue("a2")
    expect(screen.getByLabelText("Draft")).toHaveValue("half a thought")
    expect(requests.filter((url) => url.includes("/beta/"))).toEqual([])
    expect(control.refreshes).toBe(0)

    // The selection still names alpha: leaving to an unscoped page is guarded too, and Stay keeps it.
    void router.navigate("/campaigns")
    const again = await screen.findByRole("dialog", { name: "Discard your draft?" })
    fireEvent.click(within(again).getByRole("button", { name: "Leave" }))
    await screen.findByRole("heading", { name: "Campaigns" })
    await waitFor(() => expect(quests()).toHaveAttribute("href", "/app/alpha/quests"))

    await go("/app/beta/notes")
    await ready("beta", "b1")
    expect(select()).toHaveValue("b1")
  })
})

describe("the World workspace shows a retained campaign only while it belongs to the confirmed world", () => {
  it("shows a compatible one as the selected campaign and drops an incompatible one", async () => {
    mount("/app/alpha/notes")
    await ready("alpha", "")
    choose("a2")
    await ready("alpha", "a2")

    await go("/worlds/w1")
    await screen.findByRole("heading", { name: "World page" })
    await waitFor(() => expect(campaignSelect()).toHaveValue("alpha"))
    expect(screen.getByRole("heading", { name: "Selected campaign" })).toBeInTheDocument()
    expect(quests()).toHaveAttribute("href", "/app/alpha/quests")

    await go("/worlds/w2")
    await screen.findByRole("heading", { name: "World page" })
    await waitFor(() => expect(screen.getByRole("heading", { name: "Campaign" })).toBeInTheDocument())
    expect(quests()).toBeNull()

    // The incompatible choice was cleared, not parked: alpha comes back at its default.
    await go("/app/alpha/notes")
    await ready("alpha", "")
    expect(select()).toHaveValue("")
  })

  it("never shows the retained campaign while the world is unconfirmed", async () => {
    mount("/app/alpha/notes")
    await ready("alpha", "")
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: "not found" }, 404)),
    )
    await go("/worlds/w1")
    await screen.findByRole("heading", { name: "World page" })
    expect(quests()).toBeNull()
    expect(screen.queryByRole("heading", { name: "Selected campaign" })).toBeNull()
  })
})

describe("permission loss and re-authorization", () => {
  const revoke = async (shape: Shape) => {
    await act(async () => {
      control.publish!(bootstrapOf(shape))
    })
  }

  it("clears a selected campaign the session no longer lists, and re-authorization does not bring it back", async () => {
    mount("/app/alpha/notes")
    await ready("alpha", "")
    choose("a2")
    await ready("alpha", "a2")
    await go("/campaigns")
    await waitFor(() => expect(quests()).toHaveAttribute("href", "/app/alpha/quests"))

    await revoke({ withAlpha: false })
    await waitFor(() => expect(quests()).toBeNull())
    await revoke({})
    expect(quests()).toBeNull()

    await go("/app/alpha/notes")
    await ready("alpha", "")
    expect(select()).toHaveValue("")
  })

  it("clears a lost perspective to an explicit none off the campaign route, and re-authorization does not restore it", async () => {
    control.bootstrap = bootstrapOf({ alphaDefault: "a1" })
    mount("/app/alpha/notes")
    await ready("alpha", "a1")
    choose("a2")
    await ready("alpha", "a2")
    await go("/campaigns")

    await revoke({ alpha: ["a1"], alphaDefault: "a1" })
    await revoke({ alpha: ["a1", "a2"], alphaDefault: "a1" })

    await go("/app/alpha/notes")
    // Not a2 (restored), and not the server default a1 (replacing a lost choice): no perspective.
    await ready("alpha", "")
    expect(select()).toHaveValue("")
    expect(probes().filter((p) => p.includes("a2")).length).toBe(1)
  })

  it("loses the campaign route itself as 'Campaign not found' and clears the selection with it", async () => {
    mount("/app/alpha/notes")
    await ready("alpha", "")
    await revoke({ withAlpha: false })
    await screen.findByRole("heading", { name: "Campaign not found" })
    await go("/campaigns")
    expect(quests()).toBeNull()
  })

  it("drops the selection when the signed-in user or browser session changes", async () => {
    mount("/app/alpha/notes")
    await ready("alpha", "")
    choose("a2")
    await ready("alpha", "a2")
    await go("/campaigns")
    await act(async () => {
      control.publish!({ ...bootstrapOf(), user: { user_id: "u2", display_name: "Other" } })
    })
    await waitFor(() => expect(quests()).toBeNull())
  })
})

describe.each([
  ["plain", false],
  ["StrictMode", true],
])("late responses and labels under the authority they started in (%s)", (_name, strict) => {
  const answer = async (index: number, who: string) => {
    await parked[index]!.answer(who)
  }

  it("a page read from the old campaign cannot alter the new campaign's selection or page", async () => {
    parkProbes = true
    mount("/app/alpha/notes", strict)
    await waitFor(() => expect(parked.length).toBeGreaterThan(0))
    const alphaReads = parked.length

    await go("/app/beta/notes")
    await waitFor(() => expect(parked.length).toBeGreaterThan(alphaReads))
    // The old campaign's answer arrives after the route moved on.
    await answer(0, "late-alpha")
    expect(screen.getByTestId("read")).not.toHaveTextContent("late-alpha")
    expect(screen.getByTestId("label")).toHaveTextContent("generic")

    await answer(parked.length - 1, "b1")
    await ready("beta", "b1")
    expect(screen.getByTestId("label")).toHaveTextContent("b1")
    expect(select()).toHaveValue("b1")
    expect(router.state.location.pathname).toBe("/app/beta/notes")
  })

  it("A → B → A: a read begun in the first A publishes no label into the second A", async () => {
    parkProbes = true
    mount("/app/alpha/notes", strict)
    await waitFor(() => expect(parked.length).toBeGreaterThan(0))
    const firstAlpha = parked.length

    await go("/app/beta/notes")
    await waitFor(() => expect(parked.length).toBeGreaterThan(firstAlpha))
    const beta = parked.length
    await go("/app/alpha/notes")
    await waitFor(() => expect(parked.length).toBeGreaterThan(beta))

    // The oldest answers arrive last.
    await answer(0, "stale-first-alpha")
    expect(screen.getByTestId("label")).toHaveTextContent("generic")
    expect(screen.getByTestId("read")).not.toHaveTextContent("stale-first-alpha")

    await answer(parked.length - 1, "")
    await ready("alpha", "")
    expect(screen.getByTestId("label")).not.toHaveTextContent("stale-first-alpha")
  })

  it("a read begun under the previous perspective publishes no label for the new one", async () => {
    parkProbes = true
    mount("/app/alpha/notes", strict)
    await waitFor(() => expect(parked.length).toBeGreaterThan(0))
    await answer(parked.length - 1, "")
    await ready("alpha", "")
    const before = parked.length
    choose("a2")
    await waitFor(() => expect(parked.length).toBeGreaterThan(before))

    await answer(before - 1, "old-perspective")
    expect(screen.getByTestId("label")).not.toHaveTextContent("old-perspective")
    await answer(parked.length - 1, "a2")
    await ready("alpha", "a2")
    expect(screen.getByTestId("label")).toHaveTextContent("a2")
  })
})
