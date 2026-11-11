import { act, cleanup, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { StrictMode, useLayoutEffect, useState } from "react"
import { Link, Route, RouterProvider, Routes, createMemoryRouter, useLocation } from "react-router"
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
import { selectionOwner, useSelectedContextStore } from "./selectedContextStore"
import type { SelectedContextStore } from "./selectedContextStore"
import { ThemeProvider } from "../themes/ThemeProvider"
import type { CampaignContext, SessionBootstrap } from "../types/bootstrap"

// P02-3 history retention. Every accepted in-app location of the authenticated portal mirrors the
// validated selected context into its own entry (state.ctx), and a reload or Back/Forward restores it
// through the same validation, for campaign, World and unscoped routes alike. Real providers, shell,
// layouts, guards and router; only the session bootstrap and fetch are faked.

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

function bootstrapOf(over: { alphaDefault?: string | null; withAlpha?: boolean; alpha?: string[]; user?: string } = {}): SessionBootstrap {
  const { alphaDefault = null, withAlpha = true, alpha = ["a1", "a2"], user = "u1" } = over
  return {
    user: { user_id: user, display_name: "Gina" },
    csrf_token: "csrf",
    browser_session_id: "s1",
    system_roles: ["player"],
    global_capabilities: [],
    startup_campaign_id: "beta",
    campaign_preferences: { startup_mode: "resume_last_visited", preferred_campaign_id: null, last_visited_campaign_id: "beta" },
    campaigns: [
      ...(withAlpha ? [campaign("alpha", "w1", alpha, alphaDefault)] : []),
      campaign("beta", "w1", ["b1"], "b1"),
      campaign("gamma", "w2", [], null),
    ],
    features: { ask: false, ai_summaries: false, gm_briefs: false, cited_rules: false },
  }
}

const requests: string[] = []
// Worlds the session cannot read (a non-disclosing 404), and reads parked until the test answers them.
const unreadableWorlds = new Set<string>()
let parkWorlds = false
type Answer = "ok" | "deny" | "fail"
const parkedWorlds: Array<{ id: string; answer: (kind?: Answer) => Promise<void> }> = []
// Worlds whose read fails for a transient reason (a 500), apart from the ones the session may not read.
const failingWorlds = new Set<string>()
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
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

function NotesPage() {
  const { getSelectedCharacterId } = usePerspective()
  const campaignId = useLocation().pathname.split("/")[2]!
  const perspective = getSelectedCharacterId(campaignId) ?? ""
  const read = useAuthoringResource<{ who: string }>(`/campaigns/${campaignId}/probe?character_id=${perspective}`)
  return (
    <div>
      <h1>Notes</h1>
      <p data-testid="read">{read.state.kind === "ready" ? `ready:${campaignId}:${read.state.data.who}` : read.state.kind}</p>
    </div>
  )
}

// A World editor: unsent input holds the page's one question.
function WorldEditor() {
  const [text, setText] = useState("")
  const guard = useUnsavedChangesGuard(text !== "")
  return (
    <div>
      <h1>World editor</h1>
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

// Hands the tab's real store to the test, to read the selection and to make a deliberate change to it.
let storeRef: SelectedContextStore
function StoreProbe() {
  const store = useSelectedContextStore()
  useLayoutEffect(() => {
    storeRef = store
  }, [store])
  return null
}

type Entry = string | { pathname: string; search?: string; state?: unknown }
let router: DataRouter
// Every location the router ever published, to prove what a stamp is and is not.
let seen: Array<{ key: string; action: string; pathname: string }> = []

function tree(entry: Entry) {
  router = createMemoryRouter(
    [
      {
        path: "*",
        element: (
          <RouteSessionProvider>
            <Routes>
              <Route element={<AuthenticatedAppLayout />}>
                <Route path="/campaigns" element={<main><h1>Campaigns</h1><StoreProbe /><Link to="/app/beta/notes">to beta</Link></main>} />
                <Route path="/other" element={<main><h1>Other</h1><StoreProbe /></main>} />
                <Route element={<WorldWorkspaceLayout />}>
                  <Route path="/worlds/:worldId" element={<h1>World page</h1>} />
                  <Route path="/worlds/:worldId/edit" element={<WorldEditor />} />
                </Route>
                <Route path="/app/:campaignId" element={<CampaignSessionBoundary />}>
                  <Route path="notes" element={<NotesPage />} />
                  {/* Where a deliberate perspective change lands (PD-6); the same probe page reads under it. */}
                  <Route path="characters/:characterId" element={<NotesPage />} />
                  <Route path="characters/all" element={<NotesPage />} />
                </Route>
              </Route>
            </Routes>
          </RouteSessionProvider>
        ),
      },
    ],
    { initialEntries: [entry] },
  )
  seen = []
  router.subscribe((state) => {
    const last = seen[seen.length - 1]
    if (last !== undefined && last.key === state.location.key && last.action === state.historyAction) return
    seen.push({ key: state.location.key, action: state.historyAction, pathname: state.location.pathname })
  })
  return (
    <ThemeProvider>
      <RouterProvider router={router} />
    </ThemeProvider>
  )
}

const mount = (entry: Entry) => render(tree(entry))
const mountStrict = (entry: Entry) => render(<StrictMode>{tree(entry)}</StrictMode>)

beforeEach(() => {
  requests.length = 0
  unreadableWorlds.clear()
  failingWorlds.clear()
  parkWorlds = false
  parkedWorlds.length = 0
  control.bootstrap = bootstrapOf()
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString()
      requests.push(url)
      const probe = /\/probe\?character_id=([^&]*)/.exec(url)
      if (probe !== null) return json({ who: decodeURIComponent(probe[1]!) })
      const worldMatch = /\/worlds\/(w\d)$/.exec(url)
      if (worldMatch !== null) {
        const id = worldMatch[1]!
        const answer = (kind?: Answer) =>
          kind === "deny" || (kind === undefined && unreadableWorlds.has(id))
            ? json({ detail: "not found" }, 404)
            : kind === "fail" || (kind === undefined && failingWorlds.has(id))
              ? json({ detail: "boom" }, 500)
              : json(world(id))
        if (!parkWorlds) return answer()
        return new Promise<Response>((resolve) => {
          parkedWorlds.push({
            id,
            answer: async (kind) => {
              await act(async () => {
                resolve(answer(kind))
                await Promise.resolve()
              })
            },
          })
        })
      }
      if (/\/worlds\?/.test(url)) return json({ items: [], next_cursor: null })
      return json({ detail: "not found" }, 404)
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const stamp = (campaignId: string | null, characterId: string | null, worldId?: string) => ({
  v: 1,
  campaignId,
  worldId: campaignId === null ? null : (worldId ?? "w1"),
  timelineId: campaignId === null ? null : `t-${worldId ?? "w1"}`,
  characterId,
})
const NOTHING = stamp(null, null)
const ctx = () => (router.state.location.state as { ctx?: unknown } | null)?.ctx
const select = () => screen.getByRole("combobox", { name: "Character perspective" }) as HTMLSelectElement
const nav = () => screen.getByRole("navigation", { name: "Main" })
const quests = () => within(nav()).queryByRole("link", { name: "Quests" })
const go = async (to: string | number) => {
  await act(async () => {
    await router.navigate(to as string)
  })
}
const ready = (campaignId: string, who: string) =>
  waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent(`ready:${campaignId}:${who}`))
const stamped = (expected: unknown) => waitFor(() => expect(ctx()).toEqual(expected))
const probes = () => requests.filter((url) => url.includes("/probe?")).map((url) => url.replace(/^.*\/campaigns\//, ""))

// What a reload would hand the new document: the current entry, exactly as the history holds it.
function reload() {
  const { pathname, search, state } = router.state.location
  cleanup()
  requests.length = 0
  render(tree({ pathname, search, state }))
}

// alpha with a2 chosen, then on to `to`.
async function selectedAlphaThen(to: string) {
  mount("/app/alpha/notes")
  await ready("alpha", "")
  fireEvent.change(select(), { target: { value: "a2" } })
  await ready("alpha", "a2")
  await go(to)
}

describe("reload restores the selected context for every kind of route", () => {
  it("Campaign → World → reload: the compatible authorized selection is back, as the selected campaign", async () => {
    await selectedAlphaThen("/worlds/w1")
    await screen.findByRole("heading", { name: "World page" })
    await stamped(stamp("alpha", "a2"))

    reload()
    await screen.findByRole("heading", { name: "World page" })
    await waitFor(() => expect(screen.getByRole("heading", { name: "Selected campaign" })).toBeInTheDocument())
    expect(quests()).toHaveAttribute("href", "/app/alpha/quests")

    // The campaign route still governs its own scope, and the retained perspective is the one chosen.
    await go("/app/alpha/notes")
    await ready("alpha", "a2")
    expect(select()).toHaveValue("a2")
    expect(probes()).toEqual(["alpha/probe?character_id=a2"])
  })

  it("Campaign → unscoped portal route → reload: the selection is back", async () => {
    await selectedAlphaThen("/campaigns")
    await screen.findByRole("heading", { name: "Campaigns" })
    await stamped(stamp("alpha", "a2"))

    reload()
    await screen.findByRole("heading", { name: "Campaigns" })
    await waitFor(() => expect(quests()).toHaveAttribute("href", "/app/alpha/quests"))
    await go("/app/alpha/notes")
    await ready("alpha", "a2")
    expect(select()).toHaveValue("a2")
  })

  it("an incompatible World drops the retained campaign and stamps that, so a reload does not bring it back", async () => {
    await selectedAlphaThen("/worlds/w2")
    await screen.findByRole("heading", { name: "World page" })
    await stamped({ v: 1, campaignId: null, worldId: "w2", timelineId: null, characterId: null })
    reload()
    await screen.findByRole("heading", { name: "World page" })
    expect(quests()).toBeNull()
  })
})

describe("the entry's own state on arrival", () => {
  it("restores an explicit none, and keeps it apart from an uninitialized default", async () => {
    control.bootstrap = bootstrapOf({ alphaDefault: "a1" })
    mount({ pathname: "/campaigns", state: { ctx: stamp("alpha", null) } })
    await screen.findByRole("heading", { name: "Campaigns" })
    await waitFor(() => expect(quests()).toHaveAttribute("href", "/app/alpha/quests"))
    await go("/app/alpha/notes")
    await ready("alpha", "")
    // The server default (a1) did not replace the recorded choice of no perspective.
    expect(select()).toHaveValue("")
  })

  it("restores a valid recorded perspective", async () => {
    mount({ pathname: "/campaigns", state: { ctx: stamp("alpha", "a2") } })
    await screen.findByRole("heading", { name: "Campaigns" })
    await waitFor(() => expect(quests()).toHaveAttribute("href", "/app/alpha/quests"))
    await stamped(stamp("alpha", "a2"))
    await go("/app/alpha/notes")
    await ready("alpha", "a2")
  })

  it.each([
    ["no state", undefined],
    ["a string", { ctx: "x" }],
    ["an array", { ctx: [] }],
    ["a wrong version", { ctx: { ...stamp("alpha", "a2"), v: 2 } }],
    ["a partial form", { ctx: { v: 1, campaignId: "alpha", characterId: "a2" } }],
    ["a mistyped id", { ctx: { ...stamp("alpha", "a2"), campaignId: 7 } }],
    ["a campaign the session does not list", { ctx: stamp("ghost", "a2") }],
    ["another world than the campaign's", { ctx: { ...stamp("alpha", "a2"), worldId: "w9" } }],
    ["a perspective the campaign does not authorize", { ctx: stamp("alpha", "someone-else") }],
    ["the older perspective-only stamp, which names no campaign", { ctx: { v: 1, characterId: "a2" } }],
  ])("selects nothing from %s, and repairs the entry to record that", async (_name, state) => {
    mount({ pathname: "/campaigns", state })
    await screen.findByRole("heading", { name: "Campaigns" })
    await stamped(NOTHING)
    expect(quests()).toBeNull()
    expect(router.state.historyAction).toBe("REPLACE")
  })
})

describe("Back and Forward restore the context each entry recorded", () => {
  it("across campaign, World and unscoped entries", async () => {
    await selectedAlphaThen("/campaigns") // entry 2 records alpha/a2
    await screen.findByRole("heading", { name: "Campaigns" })
    await stamped(stamp("alpha", "a2"))
    await go("/app/beta/notes") // route wins: beta/b1
    await ready("beta", "b1")
    await go("/worlds/w1") // compatible with beta
    await screen.findByRole("heading", { name: "World page" })
    await stamped(stamp("beta", "b1"))
    await waitFor(() => expect(quests()).toHaveAttribute("href", "/app/beta/quests"))

    await go(-1) // beta
    await ready("beta", "b1")
    await go(-1) // the unscoped entry, which recorded alpha/a2
    await screen.findByRole("heading", { name: "Campaigns" })
    await waitFor(() => expect(quests()).toHaveAttribute("href", "/app/alpha/quests"))
    await stamped(stamp("alpha", "a2"))

    await go(1) // beta's campaign entry: the route governs again
    await ready("beta", "b1")
    expect(select()).toHaveValue("b1")
    await go(1) // the World entry
    await screen.findByRole("heading", { name: "World page" })
    await waitFor(() => expect(quests()).toHaveAttribute("href", "/app/beta/quests"))
  })
})

describe("a dirty World editor", () => {
  it("Stay keeps draft, context and history; Leave commits once", async () => {
    await selectedAlphaThen("/worlds/w1/edit")
    await screen.findByRole("heading", { name: "World editor" })
    await stamped(stamp("alpha", "a2"))
    fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "half" } })
    const here = router.state.location.key
    seen.length = 0

    void router.navigate("/campaigns")
    const dialog = await screen.findByRole("dialog", { name: "Discard your draft?" })
    fireEvent.click(within(dialog).getByRole("button", { name: "Stay" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(router.state.location.key).toBe(here)
    expect(router.state.location.pathname).toBe("/worlds/w1/edit")
    expect(screen.getByLabelText("Draft")).toHaveValue("half")
    expect(ctx()).toEqual(stamp("alpha", "a2"))
    expect(quests()).toHaveAttribute("href", "/app/alpha/quests")
    // The router may announce the same entry again; nothing new was pushed, replaced or popped.
    expect(seen.filter((entry) => entry.key !== here)).toEqual([])

    void router.navigate("/campaigns")
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Discard your draft?" })).getByRole("button", { name: "Leave" }))
    await screen.findByRole("heading", { name: "Campaigns" })
    await stamped(stamp("alpha", "a2"))
    expect(seen.filter((entry) => entry.action === "PUSH")).toHaveLength(1)
  })
})

describe("authority changes invalidate what was stored", () => {
  it("a revoked campaign is not restored, and re-authorization does not bring it back", async () => {
    control.bootstrap = bootstrapOf({ withAlpha: false })
    mount({ pathname: "/campaigns", state: { ctx: stamp("alpha", "a2") } })
    await screen.findByRole("heading", { name: "Campaigns" })
    await stamped(NOTHING)
    await act(async () => control.publish!(bootstrapOf()))
    expect(quests()).toBeNull()
    expect(ctx()).toEqual(NOTHING)
  })

  it("a different user or session in the same tab empties the selection and the entry's record of it", async () => {
    await selectedAlphaThen("/campaigns")
    await stamped(stamp("alpha", "a2"))
    await act(async () => control.publish!(bootstrapOf({ user: "u2" })))
    await waitFor(() => expect(quests()).toBeNull())
    await stamped(NOTHING)
    await act(async () => control.publish!(bootstrapOf()))
    expect(quests()).toBeNull()
  })

  it("a perspective that is no longer authorized is not restored, and is recorded as none", async () => {
    await selectedAlphaThen("/campaigns")
    await stamped(stamp("alpha", "a2"))
    await act(async () => control.publish!(bootstrapOf({ alpha: ["a1"] })))
    await stamped(stamp("alpha", null))
    await act(async () => control.publish!(bootstrapOf()))
    expect(ctx()).toEqual(stamp("alpha", null))
  })
})

describe("stamping itself", () => {
  it("never overwrites a newer navigation made while it was pending", async () => {
    mount({ pathname: "/campaigns", state: { ctx: stamp("alpha", "a2") } })
    await screen.findByRole("heading", { name: "Campaigns" })
    // Immediately: before the restored selection has been recorded back on this entry.
    await go("/app/beta/notes")
    await ready("beta", "b1")
    await stamped(stamp("beta", "b1"))
    expect(router.state.location.pathname).toBe("/app/beta/notes")
    await go(-1)
    await screen.findByRole("heading", { name: "Campaigns" })
    expect(ctx()).toEqual(stamp("alpha", "a2"))
  })

  it("adds no entry, keeps unrelated state and task, and causes no extra page read", async () => {
    const task = { v: 1, root: "world", scope: { worldId: "w1" }, trail: [] }
    mount({ pathname: "/worlds/w1", state: { task, keep: "me" } })
    await screen.findByRole("heading", { name: "World page" })
    await stamped(NOTHING_WITH_WORLD)
    expect(router.state.location.state).toMatchObject({ task, keep: "me" })
    expect(seen.every((entry) => entry.action === "REPLACE" || entry.action === "POP")).toBe(true)
    expect(requests.filter((url) => /\/worlds\/w1$/.test(url))).toHaveLength(1)
    const count = requests.length
    await act(async () => {
      await Promise.resolve()
    })
    expect(requests.length).toBe(count)
  })
})

const NOTHING_WITH_WORLD = { v: 1, campaignId: null, worldId: "w1", timelineId: null, characterId: null }

// A valid no-campaign selection may retain a World. History ids are not authority: the session's own
// World read (GET /worlds/{id}, the one a World route uses) must confirm it before it is selected again.
const WORLD_ONLY = (worldId: string, timelineId: string | null = null) => ({
  v: 1,
  campaignId: null,
  worldId,
  timelineId,
  characterId: null,
})
const worldReads = (id: string) => requests.filter((url) => new RegExp(`/worlds/${id}$`).test(url))

describe("a World selected without a campaign (World-only context)", () => {
  it("survives Select World → unscoped route → reload, verified by the session, with the same corrected stamp", async () => {
    mount("/worlds/w2")
    await screen.findByRole("heading", { name: "World page" })
    await stamped(WORLD_ONLY("w2"))
    await go("/campaigns")
    await screen.findByRole("heading", { name: "Campaigns" })
    await stamped(WORLD_ONLY("w2"))

    reload()
    await screen.findByRole("heading", { name: "Campaigns" })
    // Verified through the existing World read, not trusted from history.
    await waitFor(() => expect(worldReads("w2")).toHaveLength(1))
    await act(async () => {
      await Promise.resolve()
    })
    expect(ctx()).toEqual(WORLD_ONLY("w2"))
    expect(worldReads("w2")).toHaveLength(1)
    // No campaign or perspective was inferred to fill the missing levels.
    expect(quests()).toBeNull()
  })

  it("restores an initial World-only stamp on an unscoped route once the World is read, and not before", async () => {
    parkWorlds = true
    mount({ pathname: "/campaigns", state: { ctx: WORLD_ONLY("w2") } })
    await screen.findByRole("heading", { name: "Campaigns" })
    await waitFor(() => expect(parkedWorlds).toHaveLength(1))
    // Unverified: the entry still records it (it is not repaired to nothing) and nothing is governed by it.
    expect(ctx()).toEqual(WORLD_ONLY("w2"))
    expect(quests()).toBeNull()
    await parkedWorlds[0]!.answer()
    await act(async () => {
      await Promise.resolve()
    })
    expect(ctx()).toEqual(WORLD_ONLY("w2"))
    expect(worldReads("w2")).toHaveLength(1)
  })

  it("drops a World the session cannot read, and repairs the entry to record nothing", async () => {
    unreadableWorlds.add("w2")
    mount({ pathname: "/campaigns", state: { ctx: WORLD_ONLY("w2") } })
    await screen.findByRole("heading", { name: "Campaigns" })
    await stamped(NOTHING)
    await act(async () => control.publish!(bootstrapOf()))
    expect(ctx()).toEqual(NOTHING)
  })

  it("ignores a verification that answers after newer navigation", async () => {
    parkWorlds = true
    mount({ pathname: "/campaigns", state: { ctx: WORLD_ONLY("w2") } })
    await waitFor(() => expect(parkedWorlds).toHaveLength(1))
    parkWorlds = false
    await go("/app/alpha/notes")
    await ready("alpha", "")
    await stamped(stamp("alpha", null))
    await parkedWorlds[0]!.answer()
    await act(async () => {
      await Promise.resolve()
    })
    // The route campaign governs and the late answer changed nothing.
    expect(ctx()).toEqual(stamp("alpha", null))
    await go("/campaigns")
    await stamped(stamp("alpha", null))
    expect(quests()).toHaveAttribute("href", "/app/alpha/quests")
  })

  it("ignores a verification that answers after the user or session changed", async () => {
    parkWorlds = true
    mount({ pathname: "/campaigns", state: { ctx: WORLD_ONLY("w2") } })
    await waitFor(() => expect(parkedWorlds).toHaveLength(1))
    await act(async () => control.publish!(bootstrapOf({ user: "u2" })))
    await parkedWorlds[0]!.answer()
    await act(async () => {
      await Promise.resolve()
    })
    await stamped(NOTHING)
  })

  it("keeps a fully empty selection empty, with no World read", async () => {
    mount({ pathname: "/campaigns", state: { ctx: NOTHING } })
    await screen.findByRole("heading", { name: "Campaigns" })
    await act(async () => {
      await Promise.resolve()
    })
    expect(ctx()).toEqual(NOTHING)
    expect(requests.filter((url) => /\/worlds\/w\d$/.test(url))).toEqual([])
    expect(quests()).toBeNull()
  })

  it("Back and Forward through World-only and campaign-selected entries", async () => {
    await selectedAlphaThen("/campaigns") // entry A: alpha/a2
    await stamped(stamp("alpha", "a2"))
    await go("/worlds/w2") // entry B: World-only (alpha is not in w2)
    await screen.findByRole("heading", { name: "World page" })
    await stamped(WORLD_ONLY("w2"))
    await go("/campaigns") // entry C: World-only
    await stamped(WORLD_ONLY("w2"))
    expect(quests()).toBeNull()

    await go(-1)
    await screen.findByRole("heading", { name: "World page" })
    await stamped(WORLD_ONLY("w2"))
    await go(-1) // back to alpha/a2
    await screen.findByRole("heading", { name: "Campaigns" })
    await waitFor(() => expect(quests()).toHaveAttribute("href", "/app/alpha/quests"))
    await stamped(stamp("alpha", "a2"))

    await go(1)
    await screen.findByRole("heading", { name: "World page" })
    await waitFor(() => expect(quests()).toBeNull())
    await stamped(WORLD_ONLY("w2"))
    await go(1)
    await screen.findByRole("heading", { name: "Campaigns" })
    await stamped(WORLD_ONLY("w2"))
  })

  it.each([
    ["a timeline of that World", WORLD_ONLY("w2", "t-w2"), WORLD_ONLY("w2", "t-w2")],
    ["a timeline the World does not list: kept as the World alone, never guessed", WORLD_ONLY("w2", "t-zzz"), WORLD_ONLY("w2")],
    ["a timeline with no World", { ...WORLD_ONLY("w2"), worldId: null, timelineId: "t-w2" }, NOTHING],
    ["a perspective with no campaign", { ...WORLD_ONLY("w2"), characterId: "a2" }, NOTHING],
    ["a malformed World id", { ...WORLD_ONLY("w2"), worldId: "../x" }, NOTHING],
  ])("timeline and shape policy: %s", async (_name, recorded, expected) => {
    mount({ pathname: "/campaigns", state: { ctx: recorded } })
    await screen.findByRole("heading", { name: "Campaigns" })
    await stamped(expected)
  })

  it("a dirty World editor still Stays and Leaves with the World-only context intact", async () => {
    mount("/worlds/w2/edit")
    await screen.findByRole("heading", { name: "World editor" })
    await stamped(WORLD_ONLY("w2"))
    fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "half" } })
    void router.navigate("/campaigns")
    const dialog = await screen.findByRole("dialog", { name: "Discard your draft?" })
    fireEvent.click(within(dialog).getByRole("button", { name: "Stay" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(router.state.location.pathname).toBe("/worlds/w2/edit")
    expect(screen.getByLabelText("Draft")).toHaveValue("half")
    expect(ctx()).toEqual(WORLD_ONLY("w2"))
    void router.navigate("/campaigns")
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Discard your draft?" })).getByRole("button", { name: "Leave" }))
    await screen.findByRole("heading", { name: "Campaigns" })
    await stamped(WORLD_ONLY("w2"))
  })
})

// One restoration attempt owns exactly one request and one result, and may select or repair only while it
// still owns the history entry it was made for, the selection revision it was made against, and the user
// and session it was made under. Same address, same World id and an empty selection prove none of that.
const OWNER = selectionOwner(bootstrapOf())
const T1 = { v: 1, root: "world", scope: { worldId: "w2" }, trail: [] }
const T2 = { v: 1, root: "world", scope: { worldId: "w1" }, trail: [] }
const taskOf = () => (router.state.location.state as { task?: unknown } | null)?.task
const selectedWorld = () => storeRef.getSnapshot().worldId
const flush = () =>
  act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })

describe.each([
  ["plain", false],
  ["StrictMode", true],
])("a restoration attempt owns its history entry (%s)", (_name, strict) => {
  const open = () => {
    parkWorlds = true
    const state = { task: T1, ctx: WORLD_ONLY("w2") }
    return strict ? mountStrict({ pathname: "/campaigns", state }) : mount({ pathname: "/campaigns", state })
  }

  it.each([
    ["a newer same-path entry (PUSH) with other task state", false],
    ["an unrelated REPLACE of the same path with other task state", true],
  ])("%s supersedes it: the late answer neither selects, clears nor repairs the newer entry", async (_label, replace) => {
    open()
    await waitFor(() => expect(parkedWorlds.length).toBeGreaterThan(0))
    const requestsMade = parkedWorlds.length
    await act(async () => {
      await router.navigate("/campaigns", { replace, state: { task: T2 } })
    })
    await stamped({ ...NOTHING })
    expect(taskOf()).toEqual(T2)

    // The first attempt's own answer, long after the newer entry stamped itself.
    await parkedWorlds[0]!.answer("ok")
    await flush()
    expect(ctx()).toEqual(NOTHING)
    expect(taskOf()).toEqual(T2)
    expect(selectedWorld()).toBeNull()
    expect(quests()).toBeNull()
    // The newer entry asked for nothing, so nothing else was verified.
    expect(parkedWorlds).toHaveLength(requestsMade)
  })

  it("a refusal for the superseded attempt does not clear or repair the newer entry either", async () => {
    open()
    await waitFor(() => expect(parkedWorlds.length).toBeGreaterThan(0))
    await act(async () => {
      await router.navigate("/campaigns", { replace: true, state: { task: T2, ctx: stamp("alpha", "a2") } })
    })
    await stamped(NOTHING)
    await parkedWorlds[0]!.answer("deny")
    await flush()
    expect(ctx()).toEqual(NOTHING)
    expect(taskOf()).toEqual(T2)
  })
})

describe("a restoration attempt owns the selection revision it was made against", () => {
  const open = async () => {
    parkWorlds = true
    mount({ pathname: "/campaigns", state: { ctx: WORLD_ONLY("w2") } })
    await waitFor(() => expect(parkedWorlds).toHaveLength(1))
  }

  it("a deliberate select-then-clear invalidates it, even though the store ends where it began", async () => {
    await open()
    await act(async () => {
      storeRef.commit({ owner: OWNER, campaignId: "alpha", worldId: "w1", timelineId: "t-w1", characterId: "a2" })
    })
    await act(async () => {
      storeRef.commit({ owner: OWNER, campaignId: null, worldId: null, timelineId: null, characterId: undefined })
    })
    await parkedWorlds[0]!.answer("ok")
    await flush()
    // The cleared choice is not resurrected, and the entry does not record the obsolete World.
    expect(selectedWorld()).toBeNull()
    await stamped(NOTHING)
    expect(quests()).toBeNull()
  })

  it("A → B → A back to identical values is still a deliberate change", async () => {
    await selectedAlphaThen("/campaigns")
    await stamped(stamp("alpha", "a2"))
    await go("/worlds/w2")
    await screen.findByRole("heading", { name: "World page" })
    await stamped(WORLD_ONLY("w2"))
    await go("/campaigns")
    await stamped(WORLD_ONLY("w2"))
    await go(-2) // the entry that recorded alpha/a2
    await waitFor(() => expect(quests()).toHaveAttribute("href", "/app/alpha/quests"))
    await stamped(stamp("alpha", "a2"))

    parkWorlds = true
    parkedWorlds.length = 0
    await go(2) // a World-only entry: an attempt, made while alpha/a2 is selected
    await waitFor(() => expect(parkedWorlds).toHaveLength(1))
    await act(async () => {
      storeRef.commit({ owner: OWNER, campaignId: "beta", worldId: "w1", timelineId: "t-w1", characterId: "b1" })
    })
    await act(async () => {
      storeRef.commit({ owner: OWNER, campaignId: "alpha", worldId: "w1", timelineId: "t-w1", characterId: "a2" })
    })
    await parkedWorlds[0]!.answer("ok")
    await flush()
    expect(storeRef.getSnapshot()).toMatchObject({ campaignId: "alpha", characterId: "a2" })
    expect(selectedWorld()).toBe("w1")
    await stamped(stamp("alpha", "a2"))
  })
})

describe("a restoration attempt owns its own request and result", () => {
  it("is not settled by an earlier attempt's response: each entry gets its own verification", async () => {
    parkWorlds = true
    mount({ pathname: "/campaigns", state: { ctx: WORLD_ONLY("w2") } })
    await waitFor(() => expect(parkedWorlds).toHaveLength(1))
    await go("/campaigns") // a newer entry on the same address
    await go(-1) // back to the first entry: a new attempt
    await waitFor(() => expect(parkedWorlds).toHaveLength(2))
    expect(worldReads("w2")).toHaveLength(2)

    await parkedWorlds[0]!.answer("ok") // the first attempt's result
    await flush()
    expect(selectedWorld()).toBeNull()
    expect(ctx()).toEqual(WORLD_ONLY("w2"))

    await parkedWorlds[1]!.answer("ok") // its own
    await waitFor(() => expect(selectedWorld()).toBe("w2"))
    expect(ctx()).toEqual(WORLD_ONLY("w2"))
  })

  it("a prior success never confirms a current denial: the retained World is dropped", async () => {
    mount({ pathname: "/campaigns", state: { ctx: WORLD_ONLY("w2") } })
    await waitFor(() => expect(selectedWorld()).toBe("w2"))
    await go("/campaigns") // same address, another entry
    unreadableWorlds.add("w2")
    await go(-1) // a new attempt for the first entry
    await waitFor(() => expect(worldReads("w2")).toHaveLength(2))
    await stamped(NOTHING)
    expect(selectedWorld()).toBeNull()
  })

  it("a prior transient failure never denies a current success", async () => {
    failingWorlds.add("w2")
    mount({ pathname: "/campaigns", state: { ctx: WORLD_ONLY("w2") } })
    await stamped(NOTHING) // failed closed, repaired
    failingWorlds.clear()
    await go("/worlds/w2")
    await screen.findByRole("heading", { name: "World page" })
    await stamped(WORLD_ONLY("w2"))
    await go("/campaigns")
    await stamped(WORLD_ONLY("w2"))
    await go(-2) // the repaired first entry: nothing selected
    await waitFor(() => expect(selectedWorld()).toBeNull())
    const before = worldReads("w2").length
    await go(2) // a World-only entry: its own attempt, its own request
    await waitFor(() => expect(worldReads("w2")).toHaveLength(before + 1))
    await waitFor(() => expect(selectedWorld()).toBe("w2"))
    expect(ctx()).toEqual(WORLD_ONLY("w2"))
  })

  it("never settles a pending attempt before its own response arrives", async () => {
    parkWorlds = true
    mount({ pathname: "/campaigns", state: { ctx: WORLD_ONLY("w2") } })
    await waitFor(() => expect(parkedWorlds).toHaveLength(1))
    await flush()
    await flush()
    expect(ctx()).toEqual(WORLD_ONLY("w2"))
    expect(selectedWorld()).toBeNull()
    await parkedWorlds[0]!.answer("ok")
    await waitFor(() => expect(selectedWorld()).toBe("w2"))
  })
})
