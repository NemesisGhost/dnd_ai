import { act, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { StrictMode, useState } from "react"
import { Route, RouterProvider, Routes, createMemoryRouter, useLocation, useParams } from "react-router"
import type { DataRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import { RouteSessionProvider } from "../context/RouteSessionProvider"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useNavigationHold } from "../hooks/navigationHolds"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import { AuthenticatedAppLayout } from "../layouts/AuthenticatedAppLayout"
import { CampaignSessionBoundary } from "../layouts/CampaignSessionBoundary"
import { WorldWorkspaceLayout } from "../layouts/WorldWorkspaceLayout"
import { ThemeProvider } from "../themes/ThemeProvider"
import type { CampaignContext, SessionBootstrap } from "../types/bootstrap"
import { parseTask } from "./taskOrigin"

// P02-5 / PD-6. A deliberate Infobox selection is an ordinary departure: it asks the router for one
// destination with a new task, the existing guard decides first, and nothing (selection, task, query,
// bootstrap, page) changes until the navigation is accepted. The production tree runs: the selected-
// context store, the shell and Infobox, the campaign and world layouts, the guards and the router. Only
// the bootstrap and fetch are faked; reads and writes are parked where the order of answers is the point.

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

function bootstrapOf(alpha: string[] = ["a1", "a2", "a3"]): SessionBootstrap {
  return {
    user: { user_id: "u1", display_name: "Gina" },
    csrf_token: "csrf",
    browser_session_id: "s1",
    system_roles: ["player"],
    global_capabilities: [],
    startup_campaign_id: null,
    campaign_preferences: { startup_mode: "resume_last_visited", preferred_campaign_id: null, last_visited_campaign_id: null },
    campaigns: [campaign("alpha", "w1", alpha, null), campaign("beta", "w1", ["b1"], "b1"), campaign("gamma", "w2", [], null)],
    features: { ask: false, ai_summaries: false, gm_briefs: false, cited_rules: false },
  }
}

const requests: string[] = []
const posts: Array<{ url: string; key: string | null }> = []
// Reads and writes parked until the test answers them.
const parked: Array<{ url: string; answer: (who: string) => Promise<void> }> = []
const parkedPosts: Array<(outcome: "ok" | "lost") => Promise<void>> = []
let parkReads = false
let parkWrites = false
let loseWrites = false

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
}

const world = (id: string) => ({
  world_id: id,
  name: `World ${id}`,
  capabilities: ["world.view", "world.manage"],
  default_ruleset_id: null,
  allowed_rulesets: [],
  timelines: [
    { timeline_id: `t-${id}`, name: `Timeline ${id}` },
    { timeline_id: `t-${id}-b`, name: `Branch ${id}` },
  ],
  managed_campaigns: [],
  available_actions: [],
  blocked_actions: [],
})

const probeUrls = () => requests.filter((url) => url.includes("/probe?")).map((url) => url.replace(/^.*\/campaigns\//, ""))

// One guarded page for every campaign route in the test: a draft, an optional hold (a picker's open
// recording), and a write whose pending, unknown and confirmed-but-unread states the page itself holds.
function GuardedPage({ title }: { title: string }) {
  const { getSelectedCharacterId } = usePerspective()
  const location = useLocation()
  const { characterId } = useParams<{ characterId?: string }>()
  const campaignId = location.pathname.split("/")[2]!
  const perspective = getSelectedCharacterId(campaignId) ?? ""
  const [draft, setDraft] = useState("")
  const [hold, setHold] = useState(false)
  const [refreshFails, setRefreshFails] = useState(false)
  useNavigationHold(hold)
  const read = useAuthoringResource<{ who: string }>(
    `/campaigns/${campaignId}/probe?character_id=${perspective}&page=${title}&record=${characterId ?? ""}`,
  )
  const save = useAuthoringMutation<string, { ok: boolean }>({
    scopeKey: location.pathname,
    request: async (body, context) => {
      const response = await fetch(`/campaigns/${campaignId}/save`, {
        method: "POST",
        headers: { "Idempotency-Key": context.idempotencyKey, "Content-Type": "application/json" },
        body: JSON.stringify({ body }),
        signal: context.signal,
      })
      if (!response.ok) throw new Error("lost")
      return (await response.json()) as { ok: boolean }
    },
    onSuccess: () => (refreshFails ? "failed" : "ok"),
    ownsRefreshNotice: true,
  })
  // The page's own rule: an unresolved write is held like a dirty form.
  const unresolved = save.status.kind === "pending" || save.status.kind === "error" || save.status.kind === "confirmed"
  const guard = useUnsavedChangesGuard(draft !== "" || unresolved)
  return (
    <div>
      <h1>{title}</h1>
      <p data-testid="record">{characterId ?? "-"}</p>
      <p data-testid="read">{read.state.kind === "ready" ? `ready:${read.state.data.who}` : read.state.kind}</p>
      <p data-testid="write">{save.status.kind}</p>
      <label>
        Draft
        <input value={draft} onChange={(event) => setDraft(event.target.value)} />
      </label>
      <button type="button" onClick={() => setHold(true)}>
        Hold
      </button>
      <button type="button" onClick={() => setRefreshFails(true)}>
        Break refresh
      </button>
      <button type="button" onClick={() => save.submit("payload")}>
        Save
      </button>
      <button type="button" onClick={() => save.retry()}>
        Retry
      </button>
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

let router: DataRouter
let pushes = 0

function tree(entry: { pathname: string; search?: string; state?: unknown }) {
  router = createMemoryRouter(
    [
      {
        path: "*",
        element: (
          <RouteSessionProvider>
            <Routes>
              <Route element={<AuthenticatedAppLayout />}>
                <Route element={<WorldWorkspaceLayout />}>
                  <Route path="/worlds/:worldId" element={<h1>World page</h1>} />
                  <Route path="/worlds/:worldId/timelines/:timelineId" element={<h1>Timeline page</h1>} />
                </Route>
                <Route path="/app/:campaignId" element={<CampaignSessionBoundary />}>
                  <Route path="home" element={<GuardedPage title="Home" />} />
                  <Route path="world" element={<h1>Campaign world</h1>} />
                  <Route path="knowledge" element={<GuardedPage title="Knowledge" />} />
                  <Route path="quests" element={<GuardedPage title="Quests" />} />
                  <Route path="characters/all" element={<GuardedPage title="All characters" />} />
                  <Route path="characters/:characterId" element={<GuardedPage title="Character record" />} />
                </Route>
              </Route>
            </Routes>
          </RouteSessionProvider>
        ),
      },
    ],
    { initialEntries: [entry] },
  )
  pushes = 0
  let lastKey = router.state.location.key
  router.subscribe((state) => {
    if (state.location.key !== lastKey && state.historyAction === "PUSH") pushes += 1
    lastKey = state.location.key
  })
  return (
    <ThemeProvider>
      <RouterProvider router={router} />
    </ThemeProvider>
  )
}

function mount(path = "/app/alpha/knowledge", strict = false, state?: unknown) {
  const [pathname, query] = path.split("?")
  const element = tree({ pathname: pathname!, search: query === undefined ? "" : `?${query}`, state })
  return render(strict ? <StrictMode>{element}</StrictMode> : element)
}

beforeEach(() => {
  requests.length = 0
  posts.length = 0
  parked.length = 0
  parkedPosts.length = 0
  parkReads = false
  parkWrites = false
  loseWrites = false
  control.refreshes = 0
  control.bootstrap = bootstrapOf()
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString()
      requests.push(url)
      if (init?.method === "POST") {
        const key = (init.headers as Record<string, string>)["Idempotency-Key"] ?? null
        posts.push({ url, key })
        if (parkWrites) {
          return new Promise<Response>((resolve) => {
            parkedPosts.push(async (outcome) => {
              await act(async () => {
                resolve(outcome === "ok" ? json({ ok: true }) : json({ detail: "gone" }, 503))
                await Promise.resolve()
              })
            })
          })
        }
        return loseWrites ? json({ detail: "gone" }, 503) : json({ ok: true })
      }
      const probe = /\/probe\?character_id=([^&]*)/.exec(url)
      if (probe !== null) {
        const who = decodeURIComponent(probe[1]!)
        if (!parkReads) return json({ who })
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
const choose = (value: string) => {
  // A person's click or keystroke focuses the select before it changes.
  act(() => select().focus())
  fireEvent.change(select(), { target: { value } })
}
const level = (name: string | RegExp) => screen.getByRole("combobox", { name }) as HTMLSelectElement
const typeDraft = (text = "half a thought") => fireEvent.change(screen.getByLabelText("Draft"), { target: { value: text } })
const question = () => screen.findByRole("dialog", { name: "Discard your draft?" })
const answer = async (name: "Stay" | "Leave") => {
  const dialog = await question()
  fireEvent.click(within(dialog).getByRole("button", { name }))
}
const where = () => `${router.state.location.pathname}${router.state.location.search}`
const task = () => parseTask(router.state.location.state)
const stamp = () => (router.state.location.state as { ctx?: { characterId?: string | null } } | null)?.ctx
const onPage = (title: string) => screen.findByRole("heading", { name: title })
const settledRead = async (who: string) => waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent(`ready:${who}`))
const seededTask = (root: string, campaignId = "alpha") => ({
  v: 1,
  root,
  scope: { campaignId },
  trail: [{ route: "characters.list", params: { campaignId } }],
})

describe.each([
  ["plain", false],
  ["StrictMode", true],
])("a deliberate perspective change is an ordinary departure (%s)", (_name, strict) => {
  it("Knowledge → the selected character's details, a new Characters task, none of the page's query", async () => {
    mount("/app/alpha/knowledge?character_id=a1&party_id=p1&section=x", strict)
    await onPage("Knowledge")
    await settledRead("")
    requests.length = 0

    choose("a2")

    await onPage("Character record")
    expect(where()).toBe("/app/alpha/characters/a2")
    expect(task()).toMatchObject({ root: "characters", scope: { campaignId: "alpha" }, trail: [] })
    await waitFor(() => expect(stamp()).toMatchObject({ characterId: "a2" }))
    expect(select()).toHaveValue("a2")
    await settledRead("a2")
    // The details read ran under the new perspective, for the record it names, and nothing read as the old page.
    expect(probeUrls()).toContain("alpha/probe?character_id=a2&page=Character record&record=a2")
    expect(probeUrls().some((url) => url.includes("page=Knowledge"))).toBe(false)
    expect(probeUrls().some((url) => url.includes("character_id=a1") || url.includes("party_id"))).toBe(false)
  })

  it("Quests → the selected character's details", async () => {
    mount("/app/alpha/quests?party_id=p1", strict)
    await onPage("Quests")

    choose("a3")

    await onPage("Character record")
    expect(where()).toBe("/app/alpha/characters/a3")
    expect(task()).toMatchObject({ root: "characters", trail: [] })
  })

  it("Character A's details → character B: a new task, not a continuation of A's", async () => {
    mount("/app/alpha/characters/a1", strict, { task: seededTask("characters"), ctx: { v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t-w1", characterId: "a1" } })
    await onPage("Character record")
    await waitFor(() => expect(select()).toHaveValue("a1"))
    expect(task()?.trail).toHaveLength(1)

    choose("a2")

    await waitFor(() => expect(screen.getByTestId("record")).toHaveTextContent("a2"))
    expect(where()).toBe("/app/alpha/characters/a2")
    expect(task()).toMatchObject({ root: "characters", trail: [] })
    expect(task()?.list).toBeUndefined()
    expect(select()).toHaveValue("a2")
  })

  it("choosing the character already on screen (another is selected) is still a new Characters task on the same path", async () => {
    mount("/app/alpha/characters/a2", strict, { task: seededTask("characters"), ctx: { v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t-w1", characterId: "a1" } })
    await onPage("Character record")
    await waitFor(() => expect(select()).toHaveValue("a1"))
    const entries = router.state.historyAction
    expect(entries).toBe("POP")

    choose("a2")

    await waitFor(() => expect(select()).toHaveValue("a2"))
    expect(where()).toBe("/app/alpha/characters/a2")
    expect(router.state.historyAction).toBe("PUSH")
    expect(task()?.trail).toEqual([])
  })

  it("dirty: the question comes first; Stay keeps the page, values, selection, task and history exactly", async () => {
    mount("/app/alpha/knowledge?section=x", strict, { task: seededTask("knowledge") })
    await onPage("Knowledge")
    await settledRead("")
    typeDraft()
    const before = router.state.location
    requests.length = 0
    const refreshes = control.refreshes

    choose("a2")
    await answer("Stay")

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(router.state.location).toBe(before)
    expect(task()).toMatchObject({ root: "knowledge" })
    expect(screen.getByLabelText("Draft")).toHaveValue("half a thought")
    expect(select()).toHaveValue("")
    expect(requests).toEqual([])
    expect(control.refreshes).toBe(refreshes)
    expect(select()).toHaveFocus()
  })

  it("dirty: Leave follows the ordinary-navigation policy and commits destination, selection and task together", async () => {
    mount("/app/alpha/knowledge", strict)
    await onPage("Knowledge")
    typeDraft()

    choose("a2")
    // Nothing is committed behind the question.
    expect(where()).toBe("/app/alpha/knowledge")
    await answer("Leave")

    await onPage("Character record")
    expect(where()).toBe("/app/alpha/characters/a2")
    expect(task()).toMatchObject({ root: "characters", trail: [] })
    await waitFor(() => expect(select()).toHaveValue("a2"))
    expect(screen.getByLabelText("Draft")).toHaveValue("")
    await settledRead("a2")
  })

  it("an open picker recording (a navigation hold) asks even with nothing typed; Stay leaves the hold in force", async () => {
    mount("/app/alpha/quests", strict)
    await onPage("Quests")
    fireEvent.click(screen.getByRole("button", { name: "Hold" }))

    choose("a2")
    await answer("Stay")
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(where()).toBe("/app/alpha/quests")
    expect(select()).toHaveValue("")

    // Still held: the next ask is the same question, not a bypass.
    choose("a3")
    await answer("Stay")
    expect(where()).toBe("/app/alpha/quests")
  })

  it("a pending write is not abandoned behind the person's back: Stay keeps the request and it still resolves", async () => {
    parkWrites = true
    mount("/app/alpha/knowledge", strict)
    await onPage("Knowledge")
    fireEvent.click(screen.getByRole("button", { name: "Save" }))
    await waitFor(() => expect(screen.getByTestId("write")).toHaveTextContent("pending"))

    choose("a2")
    await answer("Stay")

    expect(where()).toBe("/app/alpha/knowledge")
    expect(posts).toHaveLength(1)
    await parkedPosts[0]!("ok")
    await waitFor(() => expect(screen.getByTestId("write")).toHaveTextContent("success"))
    expect(posts).toHaveLength(1)
  })

  it("an unknown outcome keeps its idempotency key through Stay; the retry repeats exactly that request", async () => {
    loseWrites = true
    mount("/app/alpha/knowledge", strict)
    await onPage("Knowledge")
    fireEvent.click(screen.getByRole("button", { name: "Save" }))
    await waitFor(() => expect(screen.getByTestId("write")).toHaveTextContent("error"))
    const key = posts[0]!.key

    choose("a2")
    await answer("Stay")
    expect(where()).toBe("/app/alpha/knowledge")
    expect(select()).toHaveValue("")

    loseWrites = false
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    await waitFor(() => expect(screen.getByTestId("write")).toHaveTextContent("success"))
    expect(posts).toHaveLength(2)
    expect(posts[1]!.key).toBe(key)
  })

  it("a confirmed-but-unread write the page holds is asked about like any other; Stay keeps it", async () => {
    mount("/app/alpha/knowledge", strict)
    await onPage("Knowledge")
    fireEvent.click(screen.getByRole("button", { name: "Break refresh" }))
    fireEvent.click(screen.getByRole("button", { name: "Save" }))
    await waitFor(() => expect(screen.getByTestId("write")).toHaveTextContent("confirmed"))

    choose("a2")
    await answer("Stay")

    expect(where()).toBe("/app/alpha/knowledge")
    expect(screen.getByTestId("write")).toHaveTextContent("confirmed")
    expect(posts).toHaveLength(1)
  })

  it("clearing the perspective opens All characters (never a character route built from none), as a Characters task", async () => {
    mount("/app/alpha/characters/a1", strict, { ctx: { v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t-w1", characterId: "a1" } })
    await onPage("Character record")
    await waitFor(() => expect(select()).toHaveValue("a1"))

    choose("")

    await onPage("All characters")
    expect(where()).toBe("/app/alpha/characters/all")
    expect(task()).toMatchObject({ root: "characters", trail: [] })
    await waitFor(() => expect(stamp()).toMatchObject({ characterId: null }))
    expect(select()).toHaveValue("")
    expect(requests.some((url) => /characters\/(null|undefined|)$/.test(url))).toBe(false)
  })

  it("the same value is nothing: no question, no entry, no task change", async () => {
    mount("/app/alpha/characters/a1", strict, { task: seededTask("characters"), ctx: { v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t-w1", characterId: "a1" } })
    await onPage("Character record")
    await waitFor(() => expect(select()).toHaveValue("a1"))
    typeDraft()
    const before = router.state.location
    const last = router.state.historyAction

    choose("a1")

    expect(screen.queryByRole("dialog")).toBeNull()
    expect(router.state.location).toBe(before)
    expect(router.state.historyAction).toBe(last)
    expect(task()?.trail).toHaveLength(1)
  })
})

describe("a newer deliberate selection supersedes an older one", () => {
  it("a late answer for the superseded character never reaches the page (parked reads)", async () => {
    mount("/app/alpha/knowledge")
    await onPage("Knowledge")
    await settledRead("")
    parkReads = true

    choose("a2")
    await waitFor(() => expect(parked.some((read) => read.url.includes("record=a2"))).toBe(true))
    choose("a3")
    await waitFor(() => expect(parked.some((read) => read.url.includes("record=a3"))).toBe(true))
    expect(where()).toBe("/app/alpha/characters/a3")

    const late = parked.find((read) => read.url.includes("record=a2"))!
    await late.answer("a2")
    expect(screen.getByTestId("read")).not.toHaveTextContent("ready:a2")
    await parked.find((read) => read.url.includes("record=a3"))!.answer("a3")
    await settledRead("a3")
    expect(screen.getByTestId("record")).toHaveTextContent("a3")
    expect(select()).toHaveValue("a3")
    expect(task()).toMatchObject({ root: "characters", trail: [] })
  })

  it("a question that is answered Stay leaves no half-made selection for the next choice to inherit", async () => {
    mount("/app/alpha/knowledge")
    await onPage("Knowledge")
    typeDraft()

    choose("a2")
    await answer("Stay")
    choose("a3")
    await answer("Leave")

    await onPage("Character record")
    expect(where()).toBe("/app/alpha/characters/a3")
    await waitFor(() => expect(select()).toHaveValue("a3"))
    expect(stamp()).toMatchObject({ characterId: "a3" })
  })
})

describe("changes the person did not make never reset the task or navigate (PD-6 does not apply)", () => {
  const seeded = { task: seededTask("knowledge"), ctx: { v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t-w1", characterId: "a1" } }

  it("a background bootstrap refresh with the selection still authorized changes nothing", async () => {
    mount("/app/alpha/knowledge", false, seeded)
    await onPage("Knowledge")
    await waitFor(() => expect(select()).toHaveValue("a1"))
    typeDraft()
    const before = router.state.location
    requests.length = 0

    await act(async () => {
      control.publish!(bootstrapOf())
    })

    expect(router.state.location).toBe(before)
    expect(task()).toMatchObject({ root: "knowledge" })
    expect(screen.getByLabelText("Draft")).toHaveValue("half a thought")
    expect(select()).toHaveValue("a1")
    expect(screen.queryByRole("dialog")).toBeNull()
    expect(requests).toEqual([])
  })

  it("revocation of the selected character clears it to none without a question, a PD-6 move or a task reset", async () => {
    mount("/app/alpha/knowledge", false, seeded)
    await onPage("Knowledge")
    await waitFor(() => expect(select()).toHaveValue("a1"))
    typeDraft()
    const pushed = pushes

    await act(async () => {
      control.publish!(bootstrapOf(["a2", "a3"]))
    })

    await waitFor(() => expect(screen.getByText(/Your selected character is no longer available/)).toBeInTheDocument())
    expect(screen.queryByRole("dialog")).toBeNull()
    expect(router.state.location.pathname).toBe("/app/alpha/knowledge")
    expect(pushes).toBe(pushed)
    expect(task()).toMatchObject({ root: "knowledge", trail: [{ route: "characters.list" }] })
    expect(select()).toHaveValue("")

    // Re-authorization does not resurrect it, and nothing moves.
    await act(async () => {
      control.publish!(bootstrapOf())
    })
    expect(select()).toHaveValue("")
    expect(router.state.location.pathname).toBe("/app/alpha/knowledge")
  })

  it("Back to an earlier perspective entry restores it and that entry's own task, without a new departure", async () => {
    mount("/app/alpha/knowledge", false, seeded)
    await onPage("Knowledge")
    await waitFor(() => expect(select()).toHaveValue("a1"))
    choose("a2")
    await waitFor(() => expect(screen.getByTestId("record")).toHaveTextContent("a2"))
    await waitFor(() => expect(stamp()).toMatchObject({ characterId: "a2" }))
    const pushed = pushes

    await act(async () => {
      await router.navigate(-1)
    })

    await onPage("Knowledge")
    await waitFor(() => expect(select()).toHaveValue("a1"))
    expect(router.state.location.pathname).toBe("/app/alpha/knowledge")
    expect(router.state.historyAction).toBe("POP")
    expect(task()).toMatchObject({ root: "knowledge", trail: [{ route: "characters.list" }] })
    expect(pushes).toBe(pushed)
  })
})

describe("campaign, World and timeline selections start the matching task", () => {
  it("a different campaign: its Home, a new Campaign task in that scope, perspective not carried", async () => {
    mount("/app/alpha/characters/a1", false, { task: seededTask("characters"), ctx: { v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t-w1", characterId: "a1" } })
    await onPage("Character record")
    await waitFor(() => expect(select()).toHaveValue("a1"))

    fireEvent.change(level(/^(Selected campaign|Campaign)$/), { target: { value: "beta" } })

    await onPage("Home")
    expect(where()).toBe("/app/beta/home")
    expect(task()).toMatchObject({ root: "campaign", scope: { campaignId: "beta" }, trail: [] })
    expect(select()).toHaveValue("b1")
  })

  it("dirty: a different campaign asks; Stay keeps the page, the select's old value and the task", async () => {
    mount("/app/alpha/knowledge", false, { task: seededTask("knowledge") })
    await onPage("Knowledge")
    typeDraft()
    const before = router.state.location

    fireEvent.change(level(/^(Selected campaign|Campaign)$/), { target: { value: "beta" } })
    await answer("Stay")

    expect(router.state.location).toBe(before)
    expect(level(/^(Selected campaign|Campaign)$/)).toHaveValue("alpha")
    expect(task()).toMatchObject({ root: "knowledge" })
    expect(screen.getByLabelText("Draft")).toHaveValue("half a thought")
  })

  it("a different World: the World task in the destination's scope", async () => {
    mount("/app/alpha/knowledge")
    await onPage("Knowledge")

    fireEvent.change(level("World"), { target: { value: "w2" } })

    await screen.findByRole("heading", { name: "Campaign world" })
    expect(where()).toBe("/app/gamma/world")
    expect(task()).toMatchObject({ root: "world", scope: { campaignId: "gamma" }, trail: [] })
  })

  it("a different timeline: the World task for that timeline", async () => {
    mount("/worlds/w1", false, { task: seededTask("world") })
    await onPage("World page")
    await waitFor(() => expect(level("Timeline")).toBeEnabled())

    fireEvent.change(level("Timeline"), { target: { value: "t-w1-b" } })

    await onPage("Timeline page")
    expect(where()).toBe("/worlds/w1/timelines/t-w1-b")
    expect(task()).toMatchObject({ root: "world", scope: { worldId: "w1" }, trail: [] })
  })

  it("the same campaign is nothing", async () => {
    mount("/app/alpha/knowledge")
    await onPage("Knowledge")
    const before = router.state.location

    fireEvent.change(level(/^(Selected campaign|Campaign)$/), { target: { value: "alpha" } })

    expect(router.state.location).toBe(before)
  })
})

// CN-1: a caller with no world.view reaches a timeline only through their campaigns. A timeline with
// several of them opens an inline chooser; only a chooser LINK is a departure, so only it asks.
describe("the campaign chooser is an ordinary departure only when a link is followed", () => {
  // Alpha and beta are on Timeline w1; delta is on Branch w1. None of them carries world.view.
  const campaignOnly = (): SessionBootstrap => {
    const base = bootstrapOf()
    const bare = (item: CampaignContext): CampaignContext => ({ ...item, world_capabilities: [] })
    return {
      ...base,
      campaigns: [
        ...base.campaigns.map(bare),
        bare({ ...campaign("delta", "w1", [], null), timeline_id: "t-w1-b", timeline_name: "Branch w1" }),
      ],
    }
  }
  const group = () => screen.queryByRole("group", { name: "Choose a campaign to open Timeline w1" })
  const readsOfWorld = () => requests.filter((url) => /\/worlds\/w\d$/.test(url))

  async function openChooser() {
    control.bootstrap = campaignOnly()
    mount("/app/delta/home")
    await onPage("Home")
    await waitFor(() => expect(level("Timeline")).toBeEnabled())
    act(() => level("Timeline").focus())
    fireEvent.change(level("Timeline"), { target: { value: "t-w1" } })
    await screen.findByRole("group", { name: "Choose a campaign to open Timeline w1" })
  }

  it("opening it asks nothing, even on a dirty page, and adds no entry; no world read was ever sent", async () => {
    await openChooser()
    typeDraft()
    const before = router.state.location
    const entries = pushes

    fireEvent.change(level("Timeline"), { target: { value: "t-w1-b" } })
    fireEvent.change(level("Timeline"), { target: { value: "t-w1" } })

    expect(screen.queryByRole("dialog")).toBeNull()
    expect(router.state.location).toBe(before)
    expect(pushes).toBe(entries)
    expect(group()).not.toBeNull()
    expect(readsOfWorld()).toEqual([])
    expect(screen.getByLabelText("Draft")).toHaveValue("half a thought")
  })

  it("Cancel never asks, even on a dirty page", async () => {
    await openChooser()
    typeDraft()

    fireEvent.click(within(group()!).getByRole("button", { name: "Cancel" }))

    expect(screen.queryByRole("dialog")).toBeNull()
    expect(group()).toBeNull()
    expect(level("Timeline")).toHaveFocus()
    expect(screen.getByLabelText("Draft")).toHaveValue("half a thought")
  })

  it("dirty: a chooser link asks; Stay changes nothing and leaves the chooser open", async () => {
    await openChooser()
    typeDraft()
    const before = router.state.location
    const entries = pushes
    const link = within(group()!).getByRole("link", { name: "Campaign alpha" })

    act(() => link.focus())
    fireEvent.click(link)
    await answer("Stay")

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(router.state.location).toBe(before)
    expect(pushes).toBe(entries)
    // Still open, and the activated link is where focus returns (the dialog's activated-control rule).
    expect(group()).not.toBeNull()
    await waitFor(() => expect(link).toHaveFocus())
    expect(screen.getByLabelText("Draft")).toHaveValue("half a thought")
    expect(task()).not.toMatchObject({ root: "campaign", scope: { campaignId: "alpha" } })
  })

  it("dirty: Leave arrives at that campaign as a new Campaign task, and announces the campaign changed", async () => {
    await openChooser()
    typeDraft()

    fireEvent.click(within(group()!).getByRole("link", { name: "Campaign alpha" }))
    await answer("Leave")

    await onPage("Home")
    await waitFor(() => expect(where()).toBe("/app/alpha/home"))
    expect(task()).toMatchObject({ root: "campaign", scope: { campaignId: "alpha" }, trail: [] })
    await screen.findByText("Campaign changed to Campaign alpha.")
    expect(group()).toBeNull()
    expect(readsOfWorld()).toEqual([])
  })
})
