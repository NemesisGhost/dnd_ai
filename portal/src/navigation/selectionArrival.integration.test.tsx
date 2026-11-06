import { act, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { StrictMode, useState } from "react"
import { Outlet, Route, RouterProvider, Routes, createMemoryRouter, useOutletContext } from "react-router"
import type { DataRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { RouteSessionProvider } from "../context/RouteSessionProvider"
import { characterSheetFixture } from "../fixtures/characterSheet"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import { AuthenticatedAppLayout } from "../layouts/AuthenticatedAppLayout"
import { CampaignSessionBoundary } from "../layouts/CampaignSessionBoundary"
import { WorldWorkspaceLayout } from "../layouts/WorldWorkspaceLayout"
import { CampaignCharactersBrowsePage } from "../pages/CampaignCharactersPage"
import { CampaignHomePage } from "../pages/CampaignHomePage"
import { CampaignWorldPage } from "../pages/CampaignWorldPage"
import { useAnnounce } from "../components/authoring/announcer"
import { CharacterSheetRoutePage } from "../pages/CharacterSheetRoutePage"
import { TimelinePage } from "../pages/TimelinePage"
import { WorldOverviewPage } from "../pages/WorldOverviewPage"
import { ThemeProvider } from "../themes/ThemeProvider"
import { replaceOwnEntry } from "./replaceOwnEntry"
import type { CampaignContext, SessionBootstrap } from "../types/bootstrap"

// P02-5 correction. An accepted Infobox selection is announced once (polite live region) after its
// context is committed, and the destination's heading takes focus once, when the destination has actually
// rendered. The production tree runs: the shell and Infobox, the selected-context store, the campaign and
// world layouts, the guards, the router and the real destination pages. Only the bootstrap and fetch are
// faked, and the destination reads are parked where the order of answers is the point. jsdom proves
// the live-region content and document.activeElement; it does not prove what a screen reader says.

configure({ asyncUtilTimeout: 5000 })

const control = vi.hoisted(() => ({
  bootstrap: null as unknown,
  publish: null as null | ((bootstrap: unknown) => void),
  signOut: null as null | (() => void),
}))

vi.mock("../hooks/useSessionBootstrap", async () => {
  const react = await import("react")
  return {
    useSessionBootstrap: () => {
      const [bootstrap, setBootstrap] = react.useState(control.bootstrap)
      const [signedOut, setSignedOut] = react.useState(false)
      control.publish = (next) => {
        control.bootstrap = next
        setBootstrap(next)
      }
      control.signOut = () => setSignedOut(true)
      const refresh = react.useCallback(async () => true, [])
      const reload = react.useCallback(() => undefined, [])
      return {
        state: signedOut ? { status: "unauthenticated" } : { status: "authenticated", bootstrap },
        reload,
        refresh,
      }
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

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
}

const timeline = (id: string, name: string) => ({
  timeline_id: id,
  name,
  description: null,
  is_primary: false,
  parent_timeline_id: null,
  branch_point: null,
  lifecycle_status: "active",
  row_version: 1,
})

const world = (id: string) => ({
  world_id: id,
  name: `World ${id}`,
  description: null,
  lifecycle_status: "active",
  row_version: 1,
  primary_timeline_id: `t-${id}`,
  capabilities: ["world.view", "world.manage"],
  default_ruleset_id: null,
  allowed_rulesets: [],
  timelines: [timeline(`t-${id}`, `Timeline ${id}`), timeline(`t-${id}-b`, `Branch ${id}`)],
  managed_campaigns: [],
  available_actions: [],
  blocked_actions: [],
})

const characterOf = (id: string) => ({
  character_id: id,
  name: `Character ${id}`,
  character_kind: "character",
  species_code: "human",
  size_category: "medium",
  current_hit_points: 6,
  maximum_hit_points: 12,
  temporary_hit_points: 0,
  exhaustion_level: 0,
  death_save_successes: 0,
  death_save_failures: 0,
  current_location_id: null,
  active_encounter_id: null,
  conditions: [],
  resources: [],
  sections: { details: true, sheet: true, relationships: false, inventory: false, parties: false },
})

// Reads of one character's details parked until the test answers them.
type Outcome = "ok" | "missing" | "broken"
const parkedCharacters: Array<{ id: string; answer: (outcome: Outcome) => Promise<void> }> = []
let parkCharacters = false
const requests: string[] = []
// How the world and timeline reads answer, and the Campaign World explorer's search (parked until the test answers).
let worldRead: Outcome = "ok"
let worldSearch: Outcome | "parked" = "ok"
const parkedSearches: Array<{ answer: (outcome: Outcome) => Promise<void> }> = []
// The campaign summary (Campaign Home's read), parked until the test answers it.
let parkSummary = false
const parkedSummaries: Array<{ answer: () => Promise<void> }> = []

function respondCharacter(id: string, outcome: Outcome): Response {
  if (outcome === "missing") return json({ detail: "not found" }, 404)
  if (outcome === "broken") return json({ detail: "boom" }, 500)
  return json(characterOf(id))
}

let router: DataRouter

// A source page with a draft, guarded the way every authoring page is.
function DraftPage() {
  const [draft, setDraft] = useState("")
  const guard = useUnsavedChangesGuard(draft !== "")
  return (
    <div>
      <h1>Knowledge</h1>
      <label>
        Draft
        <input value={draft} onChange={(event) => setDraft(event.target.value)} />
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

// Something unrelated to a selection that announces: a save, say.
function WithSay() {
  const announce = useAnnounce()
  const context = useOutletContext()
  return (
    <>
      <Outlet context={context} />
      <button type="button" onClick={() => announce("Saved.")}>
        Say saved
      </button>
    </>
  )
}

function tree(entry: { pathname: string; state?: unknown }) {
  router = createMemoryRouter(
    [
      {
        path: "*",
        element: (
          <RouteSessionProvider>
            <Routes>
              <Route element={<AuthenticatedAppLayout />}>
                <Route element={<WithSay />}>
                  <Route element={<WorldWorkspaceLayout />}>
                    <Route path="/worlds/:worldId" element={<WorldOverviewPage />} />
                    <Route path="/worlds/:worldId/timelines/:timelineId" element={<TimelinePage />} />
                  </Route>
                  <Route path="/app/:campaignId" element={<CampaignSessionBoundary />}>
                    <Route path="home" element={<CampaignHomePage />} />
                    <Route path="world" element={<CampaignWorldPage />} />
                    <Route path="knowledge" element={<DraftPage />} />
                    <Route path="characters/all" element={<CampaignCharactersBrowsePage />} />
                    <Route path="characters/:characterId" element={<CharacterSheetRoutePage />} />
                  </Route>
                </Route>
              </Route>
            </Routes>
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

// The polite live region, recorded: every message the shell announced, in order.
let said: string[] = []
let observer: MutationObserver | null = null

// The live region is remounted with the shell on a campaign scope change, so the whole document is
// watched and only changes inside a live region count.
function watchAnnouncer() {
  said = []
  observer?.disconnect()
  observer = new MutationObserver((records) => {
    for (const record of records) {
      const target = record.target instanceof Element ? record.target : null
      if (target?.getAttribute("data-testid") === "authoring-announcer" && record.addedNodes.length > 0) {
        said.push(target.textContent ?? "")
      }
    }
  })
  observer.observe(document.body, { childList: true, subtree: true })
}
const settle = () => act(async () => undefined)
// A context stamp written by the real writer (navigation/replaceOwnEntry) on the entry the router holds.
const writeStamp = async (context: unknown = ctxOf(null)) => {
  const current = router.state.location
  await act(async () => {
    replaceOwnEntry({
      router,
      navigate: vi.fn() as never,
      location: current,
      entryKey: current.key,
      next: (entry) => ({ search: entry.search, state: { ...(entry.state as object), ctx: context } }),
    })
  })
}
// What the polite live region holds right now (retained DOM text, not a claim about what was spoken).
const regionText = () => screen.getByTestId("authoring-announcer").textContent
// The newest parked read for a character: an earlier one may belong to a page instance that was replaced.
const parkedFor = (id: string) => parkedCharacters.filter((read) => read.id === id).at(-1)!
// Something outside the destination that a person can have focus on (the header's title link).
const elsewhere = () => screen.getByRole("link", { name: "D&D AI Portal" })

function mount(path: string, strict = false, state?: unknown) {
  const element = tree({ pathname: path, state })
  return render(strict ? <StrictMode>{element}</StrictMode> : element)
}

beforeEach(() => {
  requests.length = 0
  parkedCharacters.length = 0
  parkCharacters = false
  worldRead = "ok"
  worldSearch = "ok"
  parkedSearches.length = 0
  parkSummary = false
  parkedSummaries.length = 0
  said = []
  control.bootstrap = bootstrapOf()
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString()
      requests.push(url)
      const character = /\/api\/campaigns\/[^/]+\/characters\/([^/?]+)$/.exec(url)
      if (character !== null) {
        const id = decodeURIComponent(character[1]!)
        if (!parkCharacters) return respondCharacter(id, id === "ghost" ? "missing" : id === "broken" ? "broken" : "ok")
        return new Promise<Response>((resolve) => {
          parkedCharacters.push({
            id,
            answer: async (outcome) => {
              await act(async () => {
                resolve(respondCharacter(id, outcome))
                await Promise.resolve()
              })
            },
          })
        })
      }
      const sheet = /\/api\/campaigns\/[^/]+\/characters\/([^/?]+)\/sheet$/.exec(url)
      if (sheet !== null) {
        const id = decodeURIComponent(sheet[1]!)
        return json({ ...characterSheetFixture, character_id: id, name: `Character ${id}`, character_kind: "character" })
      }
      if (/\/campaigns\/[^/]+\/summary$/.test(url)) {
        const body = { current_session: null, previous_session_recap: null, recent_events: [] }
        if (!parkSummary) return json(body)
        return new Promise<Response>((resolve) => {
          parkedSummaries.push({
            answer: async () => {
              await act(async () => {
                resolve(json(body))
                await Promise.resolve()
              })
            },
          })
        })
      }
      if (/\/api\/campaigns\/[^/]+\/world\/search\/counts/.test(url)) return json({ detail: "none" }, 404)
      if (/\/api\/campaigns\/[^/]+\/world\/search/.test(url)) {
        const answerSearch = (outcome: Outcome): Response =>
          outcome === "missing" ? json({ detail: "no" }, 404) : outcome === "broken" ? json({ detail: "boom" }, 500) : json({ items: [], next_cursor: null })
        if (worldSearch !== "parked") return answerSearch(worldSearch)
        return new Promise<Response>((resolve) => {
          parkedSearches.push({
            answer: async (outcome) => {
              await act(async () => {
                resolve(answerSearch(outcome))
                await Promise.resolve()
              })
            },
          })
        })
      }
      if (worldRead !== "ok" && /\/worlds\/w\d(\/timelines\/[^/]+)?$/.test(url)) {
        return respondCharacter("x", worldRead)
      }
      const timelineMatch = /\/worlds\/(w\d)\/timelines\/(t-w\d(?:-b)?)$/.exec(url)
      if (timelineMatch !== null) {
        return json({
          ...timeline(timelineMatch[2]!, timelineMatch[2]!.endsWith("-b") ? `Branch ${timelineMatch[1]}` : `Timeline ${timelineMatch[1]}`),
          children: [],
          managed_campaigns: [],
          available_actions: [],
          blocked_actions: [],
        })
      }
      const worldMatch = /\/worlds\/(w\d)$/.exec(url)
      if (worldMatch !== null) return json(world(worldMatch[1]!))
      // The World choices: an explicit world no authorized campaign sits in.
      if (/\/worlds\?/.test(url)) {
        const { world_id, name, description, lifecycle_status, row_version, primary_timeline_id, capabilities } = world("w3")
        return json({
          items: [{ world_id, name, description, lifecycle_status, row_version, primary_timeline_id, capabilities }],
          next_cursor: null,
        })
      }
      return json({ detail: "not found" }, 404)
    }),
  )
})

afterEach(() => {
  observer?.disconnect()
  observer = null
  vi.unstubAllGlobals()
})

const select = () => screen.getByRole("combobox", { name: "Character perspective" }) as HTMLSelectElement
const level = (name: string | RegExp) => screen.getByRole("combobox", { name }) as HTMLSelectElement
// A person's click or keystroke focuses the select before it changes.
const choose = (value: string) => {
  act(() => select().focus())
  fireEvent.change(select(), { target: { value } })
}
const chooseLevel = (name: string | RegExp, value: string) => {
  act(() => level(name).focus())
  fireEvent.change(level(name), { target: { value } })
}
const campaignLevel = /^(Selected campaign|Campaign)$/
const where = () => router.state.location.pathname
const heading = (name: string | RegExp) => screen.findByRole("heading", { level: 1, name })
const stamp = () => (router.state.location.state as { ctx?: { characterId?: string | null } } | null)?.ctx
const typeDraft = () => fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "half a thought" } })
const answer = async (name: "Stay" | "Leave") => {
  const dialog = await screen.findByRole("dialog", { name: "Discard your draft?" })
  fireEvent.click(within(dialog).getByRole("button", { name }))
}
const ctxOf = (characterId: string | null) => ({ v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t-w1", characterId })

describe.each([
  ["plain", false],
  ["StrictMode", true],
])("an accepted selection is announced once and its heading takes focus once (%s)", (_name, strict) => {
  it("character: 'Viewing as …' after the commit, then the details heading when the page has rendered", async () => {
    mount("/app/alpha/knowledge", strict)
    await heading("Knowledge")
    watchAnnouncer()

    choose("a2")

    const record = await heading("Character a2")
    expect(where()).toBe("/app/alpha/characters/a2")
    await waitFor(() => expect(record).toHaveFocus())
    await waitFor(() => expect(stamp()).toMatchObject({ characterId: "a2" }))
    await waitFor(() => expect(said).toEqual(["Viewing as Name a2."]))
    await settle()
    expect(said).toEqual(["Viewing as Name a2."])
    expect(select()).toHaveValue("a2")
  })

  it("explicit none: 'No character perspective selected.' and the Characters heading, from All characters (same path)", async () => {
    mount("/app/alpha/characters/all", strict, { ctx: ctxOf("a1") })
    await heading("Characters")
    await waitFor(() => expect(select()).toHaveValue("a1"))
    const pathBefore = where()
    watchAnnouncer()

    choose("")

    await waitFor(() => expect(select()).toHaveValue(""))
    expect(where()).toBe(pathBefore)
    expect(router.state.historyAction).toBe("PUSH")
    await waitFor(() => expect(screen.getByRole("heading", { level: 1, name: "Characters" })).toHaveFocus())
    await waitFor(() => expect(said).toEqual(["No character perspective selected."]))
    await settle()
    expect(said).toEqual(["No character perspective selected."])
  })

  it("explicit none from a character's details opens Characters, announces and focuses its heading", async () => {
    mount("/app/alpha/characters/a1", strict, { ctx: ctxOf("a1") })
    await heading("Character a1")
    await waitFor(() => expect(select()).toHaveValue("a1"))
    watchAnnouncer()

    choose("")

    const browse = await heading("Characters")
    expect(where()).toBe("/app/alpha/characters/all")
    await waitFor(() => expect(browse).toHaveFocus())
    await waitFor(() => expect(said).toEqual(["No character perspective selected."]))
    await settle()
    expect(said).toEqual(["No character perspective selected."])
  })

  it("campaign: 'Campaign changed to …' and the Campaign Home heading", async () => {
    mount("/app/alpha/knowledge", strict)
    await heading("Knowledge")
    watchAnnouncer()

    chooseLevel(campaignLevel, "beta")

    const home = await heading("Campaign Home")
    expect(where()).toBe("/app/beta/home")
    await waitFor(() => expect(home).toHaveFocus())
    await waitFor(() => expect(said).toEqual(["Campaign changed to Campaign beta."]))
    await settle()
    expect(said).toEqual(["Campaign changed to Campaign beta."])
  })

  it("World: names the world and says the incompatible campaign selection was cleared", async () => {
    mount("/app/alpha/knowledge", strict)
    await heading("Knowledge")
    await waitFor(() => expect(level("World")).toBeEnabled())
    await waitFor(() => expect(within(level("World")).getByRole("option", { name: "World w3" })).toBeInTheDocument())
    watchAnnouncer()

    chooseLevel("World", "w3")

    const overview = await heading("World w3")
    expect(where()).toBe("/worlds/w3")
    await waitFor(() => expect(overview).toHaveFocus())
    await waitFor(() => expect(said).toEqual(["World changed to World w3. Campaign selection cleared."]))
    await settle()
    expect(said).toEqual(["World changed to World w3. Campaign selection cleared."])
  })

  it("timeline: names the timeline and focuses its heading", async () => {
    mount("/worlds/w1", strict)
    await heading("World w1")
    await waitFor(() => expect(level("Timeline")).toBeEnabled())
    watchAnnouncer()

    chooseLevel("Timeline", "t-w1-b")

    const page = await heading("Branch w1")
    expect(where()).toBe("/worlds/w1/timelines/t-w1-b")
    await waitFor(() => expect(page).toHaveFocus())
    await waitFor(() => expect(said).toEqual(["Timeline changed to Branch w1."]))
    await settle()
    expect(said).toEqual(["Timeline changed to Branch w1."])
  })

  it("dirty: Stay announces nothing and returns focus to the select; Leave then announces once", async () => {
    mount("/app/alpha/knowledge", strict)
    await heading("Knowledge")
    typeDraft()
    watchAnnouncer()

    choose("a2")
    await answer("Stay")

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    await waitFor(() => expect(select()).toHaveFocus())
    await settle()
    expect(said).toEqual([])
    expect(where()).toBe("/app/alpha/knowledge")

    choose("a2")
    await answer("Leave")

    const record = await heading("Character a2")
    await waitFor(() => expect(record).toHaveFocus())
    await waitFor(() => expect(said).toEqual(["Viewing as Name a2."]))
    await settle()
    expect(said).toEqual(["Viewing as Name a2."])
  })
})

describe("a deferred destination", () => {
  it("is announced when the selection is committed and focused only once the page has rendered, once", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    watchAnnouncer()
    parkCharacters = true

    choose("a2")

    // The context is committed; the details read is still out.
    await waitFor(() => expect(parkedCharacters.some((read) => read.id === "a2")).toBe(true))
    await waitFor(() => expect(said).toEqual(["Viewing as Name a2."]))
    await settle()
    expect(said).toEqual(["Viewing as Name a2."])
    const loading = screen.getByRole("heading", { level: 1, name: "Loading character" })
    expect(loading).not.toHaveFocus()
    expect(select()).toHaveFocus()

    parkCharacters = false
    await parkedFor("a2").answer("ok")

    const record = await heading("Character a2")
    await waitFor(() => expect(record).toHaveFocus())
    expect(said).toEqual(["Viewing as Name a2."])
  })

  it("does not take focus from a person who has moved on while it loaded", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    parkCharacters = true

    choose("a2")
    await waitFor(() => expect(parkedCharacters.some((read) => read.id === "a2")).toBe(true))
    const link = elsewhere()
    act(() => link.focus())
    parkCharacters = false
    await parkedFor("a2").answer("ok")

    await heading("Character a2")
    await settle()
    expect(link).toHaveFocus()
  })

  it("a later read, a bootstrap refresh and the history stamp never announce or refocus", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    watchAnnouncer()

    choose("a2")
    const record = await heading("Character a2")
    await waitFor(() => expect(record).toHaveFocus())
    await waitFor(() => expect(stamp()).toMatchObject({ characterId: "a2" }))
    await settle()

    // The person looks at something else; then everything that is not a choice happens.
    const other = elsewhere()
    act(() => other.focus())
    await act(async () => {
      control.publish!(bootstrapOf())
    })
    await settle()

    expect(other).toHaveFocus()
    expect(said).toEqual(["Viewing as Name a2."])
  })

  it("a newer choice supersedes the older one: its late answer neither focuses nor announces", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    watchAnnouncer()
    parkCharacters = true

    choose("a2")
    await waitFor(() => expect(parkedCharacters.some((read) => read.id === "a2")).toBe(true))
    choose("a3")
    await waitFor(() => expect(parkedCharacters.some((read) => read.id === "a3")).toBe(true))
    expect(where()).toBe("/app/alpha/characters/a3")

    parkCharacters = false
    await parkedFor("a3").answer("ok")
    const record = await heading("Character a3")
    await waitFor(() => expect(record).toHaveFocus())

    await parkedFor("a2").answer("ok")
    await settle()
    expect(screen.queryByRole("heading", { name: "Character a2" })).toBeNull()
    expect(record).toHaveFocus()
    expect(said).toEqual(["Viewing as Name a2.", "Viewing as Name a3."])
  })

  it("a choice answered Stay is superseded by the next one: only the accepted one is announced", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    typeDraft()
    watchAnnouncer()

    choose("a2")
    await answer("Stay")
    choose("a3")
    await answer("Leave")

    await heading("Character a3")
    await waitFor(() => expect(said).toEqual(["Viewing as Name a3."]))
    await settle()
    expect(said).toEqual(["Viewing as Name a3."])
    expect(where()).toBe("/app/alpha/characters/a3")
  })
})

describe("nothing that is not an accepted choice announces or moves focus", () => {
  it("the same value, Back to an earlier entry and a refresh that keeps the selection are silent", async () => {
    mount("/app/alpha/knowledge", false, { ctx: ctxOf("a1") })
    await heading("Knowledge")
    await waitFor(() => expect(select()).toHaveValue("a1"))
    watchAnnouncer()

    choose("a1")
    await act(async () => {
      control.publish!(bootstrapOf())
    })
    await settle()
    expect(said).toEqual([])
    expect(select()).toHaveFocus()

    choose("a2")
    await heading("Character a2")
    await waitFor(() => expect(stamp()).toMatchObject({ characterId: "a2" }))
    await waitFor(() => expect(said).toEqual(["Viewing as Name a2."]))
    await settle()
    expect(said).toEqual(["Viewing as Name a2."])

    await act(async () => {
      await router.navigate(-1)
    })
    await heading("Knowledge")
    await waitFor(() => expect(select()).toHaveValue("a1"))
    await waitFor(() => expect(said).toEqual(["Viewing as Name a2."]))
    await settle()
    expect(said).toEqual(["Viewing as Name a2."])
    expect(screen.getByRole("heading", { level: 1, name: "Knowledge" })).not.toHaveFocus()
  })

  it("a perspective lost before the choice is accepted is never named and the choice never takes effect", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    typeDraft()
    watchAnnouncer()

    choose("a2")
    await screen.findByRole("dialog", { name: "Discard your draft?" })
    await act(async () => {
      control.publish!(bootstrapOf(["a1", "a3"]))
    })
    await answer("Leave")

    await waitFor(() => expect(where()).toBe("/app/alpha/characters/a2"))
    await settle()
    expect(said).toEqual([])
    expect(document.body.textContent).not.toContain("Name a2")
    expect(select()).toHaveValue("")
  })
})

describe("a destination that refuses or fails", () => {
  it("a refused character names nobody and still takes focus on its heading", async () => {
    // "ghost" is authorized by the session but the read is refused for this reader.
    control.bootstrap = (() => {
      const next = bootstrapOf(["a1", "ghost"])
      return next
    })()
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    watchAnnouncer()

    choose("ghost")

    const refused = await heading("Character unavailable")
    await waitFor(() => expect(refused).toHaveFocus())
    await settle()
    // The announcement uses the session's own list; the refused page shows no name of the character.
    expect(said).toEqual(["Viewing as Name ghost."])
    expect(within(refused.closest("section")!).queryByText(/Name ghost|Character ghost/)).toBeNull()
  })

  it("a failed read has a focused heading and a usable retry", async () => {
    control.bootstrap = bootstrapOf(["a1", "broken"])
    mount("/app/alpha/knowledge")
    await heading("Knowledge")

    choose("broken")

    const failed = await heading("Character information unavailable")
    await waitFor(() => expect(failed).toHaveFocus())
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled()
  })

  it("a refused World names nothing it could not read and announces nothing", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    await waitFor(() => expect(within(level("World")).getByRole("option", { name: "World w3" })).toBeInTheDocument())
    // The world list offered it, but the detail read is refused.
    const original = globalThis.fetch
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString()
      return /\/worlds\/w3$/.test(url) ? json({ detail: "no" }, 403) : original(input, init)
    })
    watchAnnouncer()

    chooseLevel("World", "w3")

    const refused = await heading("World not available")
    await waitFor(() => expect(refused).toHaveFocus())
    await settle()
    expect(said).toEqual([])
    expect(document.querySelector(".campaign-workspace__content")!.textContent).not.toContain("World w3")
  })
})

// ---------------------------------------------------------------------------------------------------
// P02-5 second correction. An arrival belongs to the destination its note names, survives only its own
// stamp, and what it announced is withdrawn when the authority behind the words is lost. The Navbar
// menu's campaign choice is announced, the Campaign World explorer takes the heading focus, and the
// ordinary World/Timeline arrival (state.announce) neither repeats nor steals.
// ---------------------------------------------------------------------------------------------------

const campaignNote = (id: string) => ({ selection: { level: "campaign", id } })

describe("an arrival belongs to the destination its note names", () => {
  it.each([
    ["a campaign note", campaignNote("alpha")],
    ["a world note", { selection: { level: "world", id: "w1" } }],
    ["a character note", { selection: { level: "character", id: "a2", campaignId: "alpha" } }],
  ])("%s on an unrelated route announces nothing even when the store matches it", async (_name, note) => {
    mount("/app/alpha/characters/a2", false, { ctx: ctxOf("a2") })
    await heading("Character a2")
    await waitFor(() => expect(stamp()).toMatchObject({ characterId: "a2" }))
    act(() => (document.activeElement as HTMLElement | null)?.blur())
    watchAnnouncer()

    // The campaign, its world and (for the character note) the perspective are all already selected:
    // the store agrees with the note, the route does not.
    await act(async () => {
      await router.navigate("/app/alpha/characters/all", { state: { ...note, ctx: ctxOf("a2") } })
    })

    const browse = await heading("Characters")
    await waitFor(() => expect(stamp()).toBeDefined())
    await settle()
    expect(said).toEqual([])
    // The note claims nothing. The heading holds focus only because the navigation itself is an ordinary
    // link arrival (a PUSH, navigation/selectionArrival.ts `focusLinkArrival`), which the note neither
    // causes nor changes; the announcer being silent is what shows the note was refused.
    expect(browse).toHaveFocus()
  })

  describe("a same-path REPLACE that is not the entry's own stamp ends the arrival", () => {
    const base = () => router.state.location.state as Record<string, unknown>
    it.each([
      ["another query", () => ({ search: "?x=1", state: base() })],
      ["a hash", () => ({ hash: "#notes", state: base() })],
      ["no selection marker", () => ({ state: { ...base(), selection: undefined } })],
      ["another marker", () => ({ state: { ...base(), selection: { level: "character", id: "a3", campaignId: "alpha" } } })],
      ["another task", () => ({ state: { ...base(), task: { v: 1, root: "world", scope: { campaignId: "alpha" }, trail: [] } } })],
    ])("%s: the heading is not focused when the page settles", async (_name, replacement) => {
      mount("/app/alpha/knowledge")
      await heading("Knowledge")
      parkCharacters = true

      choose("a2")
      await waitFor(() => expect(parkedCharacters.some((read) => read.id === "a2")).toBe(true))
      await waitFor(() => expect(stamp()).toMatchObject({ characterId: "a2" }))
      const { search, hash, state } = { search: "", hash: "", ...replacement() }
      await act(async () => {
        await router.navigate({ pathname: where(), search, hash }, { replace: true, state })
      })
      expect(select()).toHaveFocus()

      parkCharacters = false
      await parkedFor("a2").answer("ok")
      const record = await heading("Character a2")
      await settle()

      expect(record).not.toHaveFocus()
      expect(select()).toHaveFocus()
    })
  })

  it("the entry's own stamp, which lands while the page loads, keeps the arrival (focus still follows)", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    parkCharacters = true

    choose("a2")
    await waitFor(() => expect(parkedCharacters.some((read) => read.id === "a2")).toBe(true))
    await waitFor(() => expect(stamp()).toMatchObject({ characterId: "a2" }))
    parkCharacters = false
    await parkedFor("a2").answer("ok")

    const record = await heading("Character a2")
    await waitFor(() => expect(record).toHaveFocus())
  })
})

describe("what an arrival announced is withdrawn when the authority behind it is lost", () => {
  const without = (...gone: string[]) => bootstrapOf(["a1", "a2", "a3"].filter((id) => !gone.includes(id)))

  async function announcedAs(name: string) {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    choose(name)
    await heading(`Character ${name}`)
    await waitFor(() => expect(regionText()).toBe(`Viewing as Name ${name}.`))
    await settle()
  }

  it("the selected character is revoked", async () => {
    await announcedAs("a2")

    await act(async () => {
      control.publish!(without("a2"))
    })

    await waitFor(() => expect(regionText()).not.toContain("Name a2"))
    expect(document.body.textContent).not.toContain("Viewing as Name a2")
  })

  it("the person's session is lost", async () => {
    await announcedAs("a2")

    await act(async () => {
      control.signOut!()
    })
    await settle()

    expect(screen.queryByTestId("authoring-announcer")?.textContent ?? "").not.toContain("Name a2")
    expect(document.body.textContent).not.toContain("Name a2")
  })

  it("the browser session or the user is replaced, and returning to the first does not bring it back (A, B, A)", async () => {
    await announcedAs("a2")

    await act(async () => {
      control.publish!({ ...bootstrapOf(), browser_session_id: "s2" })
    })
    await waitFor(() => expect(regionText()).toBe(""))

    await act(async () => {
      control.publish!(bootstrapOf())
    })
    await settle()
    expect(regionText()).toBe("")
    expect(said).not.toContain("Viewing as Name a2.")
  })

  it("a different user's bootstrap withdraws it and a different user's names are never spoken for it", async () => {
    await announcedAs("a2")

    await act(async () => {
      control.publish!({ ...bootstrapOf(), user: { user_id: "u2", display_name: "Other" } })
    })

    await waitFor(() => expect(regionText()).toBe(""))
  })

  it("a refresh that keeps the same names and the same session leaves it alone", async () => {
    await announcedAs("a2")

    await act(async () => {
      control.publish!(bootstrapOf())
    })
    await settle()

    expect(regionText()).toBe("Viewing as Name a2.")
  })

  it("a newer unrelated announcement survives the old cleanup", async () => {
    await announcedAs("a2")
    fireEvent.click(screen.getByRole("button", { name: "Say saved" }))
    expect(regionText()).toBe("Saved.")

    await act(async () => {
      control.publish!(without("a2"))
    })
    await settle()

    expect(regionText()).toBe("Saved.")
  })

  it("an older selection's cleanup does not remove the newer selection's message", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    choose("a2")
    await heading("Character a2")
    await waitFor(() => expect(regionText()).toBe("Viewing as Name a2."))
    choose("a3")
    await heading("Character a3")
    await waitFor(() => expect(regionText()).toBe("Viewing as Name a3."))

    // a2 was the earlier choice; losing it must not take the current message with it.
    await act(async () => {
      control.publish!(without("a2"))
    })
    await settle()

    expect(regionText()).toBe("Viewing as Name a3.")
  })

  it("the cleanup of a message already taken back does nothing a second time", async () => {
    await announcedAs("a2")
    await act(async () => {
      control.publish!(without("a2"))
    })
    await waitFor(() => expect(regionText()).not.toContain("Name a2"))
    fireEvent.click(screen.getByRole("button", { name: "Say saved" }))

    await act(async () => {
      control.publish!(without("a2", "a3"))
    })
    await settle()

    expect(regionText()).toBe("Saved.")
  })

  it("a generic message (no name was readable) names nothing and is not withdrawn for a name it never had", async () => {
    // The Infobox names the person's own world; the announcement is generic when it is not readable.
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    await waitFor(() => expect(within(level("World")).getByRole("option", { name: "World w3" })).toBeInTheDocument())
    chooseLevel("World", "w3")
    await heading("World w3")
    await waitFor(() => expect(regionText()).toBe("World changed to World w3. Campaign selection cleared."))
    expect(regionText()).not.toContain("Name ")
  })
})

// ---- The Navbar menu's campaign choice ------------------------------------------------------------

const main = () => within(screen.getByRole("navigation", { name: "Main" }))
const openCampaignMenu = () => {
  const disclosure = main().getByRole("button", { name: "Show campaign menu" })
  act(() => disclosure.focus())
  fireEvent.click(disclosure, { detail: 1 })
}
const menuCampaign = (name: string) => {
  const link = main().getByRole("link", { name })
  act(() => link.focus())
  fireEvent.pointerDown(link)
  fireEvent.click(link, { detail: 1 })
}

describe("the Navbar menu's campaign choice", () => {
  it("is announced once, after it is accepted and committed", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    watchAnnouncer()
    openCampaignMenu()

    menuCampaign("Campaign beta")

    await heading("Campaign Home")
    expect(where()).toBe("/app/beta/home")
    await waitFor(() => expect(said).toEqual(["Campaign changed to Campaign beta."]))
    await settle()
    expect(said).toEqual(["Campaign changed to Campaign beta."])
  })

  it("the campaign already in force is only a link: nothing is announced", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    watchAnnouncer()
    openCampaignMenu()

    menuCampaign("Campaign alpha")

    await heading("Campaign Home")
    expect(where()).toBe("/app/alpha/home")
    await settle()
    expect(said).toEqual([])
  })

  it("Stay announces nothing; the attempt that is accepted afterwards is announced once", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    typeDraft()
    watchAnnouncer()
    openCampaignMenu()

    menuCampaign("Campaign beta")
    await answer("Stay")
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    await settle()
    expect(said).toEqual([])
    expect(where()).toBe("/app/alpha/knowledge")

    if (main().queryByRole("link", { name: "Campaign beta" }) === null) openCampaignMenu()
    menuCampaign("Campaign beta")
    await answer("Leave")

    await heading("Campaign Home")
    await waitFor(() => expect(said).toEqual(["Campaign changed to Campaign beta."]))
    await settle()
    expect(said).toEqual(["Campaign changed to Campaign beta."])
  })

  it("a choice answered Stay and superseded by another announces only the accepted one", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    typeDraft()
    watchAnnouncer()
    openCampaignMenu()

    menuCampaign("Campaign beta")
    await answer("Stay")
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    if (main().queryByRole("link", { name: "Campaign gamma" }) === null) openCampaignMenu()
    menuCampaign("Campaign gamma")
    await answer("Leave")

    await heading("Campaign Home")
    expect(where()).toBe("/app/gamma/home")
    await waitFor(() => expect(said).toEqual(["Campaign changed to Campaign gamma."]))
    await settle()
    expect(said).toEqual(["Campaign changed to Campaign gamma."])
  })
})

// ---- The Campaign World explorer, the Infobox World fallback destination --------------------------

describe("the Infobox World choice that opens the Campaign World explorer (/app/:c/world)", () => {
  async function chooseExplorerWorld() {
    mount("/worlds/w3")
    await heading("World w3")
    await waitFor(() => expect(within(level("World")).getByRole("option", { name: "World w1" })).toBeInTheDocument())
    watchAnnouncer()
    chooseLevel("World", "w1")
    await waitFor(() => expect(where()).toBe("/app/alpha/world"))
  }

  it("a settled explorer takes the heading focus once and the world is announced once", async () => {
    await chooseExplorerWorld()

    const explorer = await heading("Campaign World")
    await waitFor(() => expect(explorer).toHaveFocus())
    await waitFor(() => expect(said).toEqual(["World changed to World w1."]))
    await settle()
    expect(said).toEqual(["World changed to World w1."])
    act(() => elsewhere().focus())
    await act(async () => {
      control.publish!(bootstrapOf())
    })
    await settle()
    expect(elsewhere()).toHaveFocus()
  })

  it("while the explorer is loading nothing takes the heading focus; the settled page does, once", async () => {
    worldSearch = "parked"
    await chooseExplorerWorld()

    const explorer = await heading("Campaign World")
    await waitFor(() => expect(parkedSearches.length).toBeGreaterThan(0))
    await waitFor(() => expect(said).toEqual(["World changed to World w1."]))
    await settle()
    expect(explorer).not.toHaveFocus()
    // (The shell was remounted for the new campaign scope, so focus is nowhere until the page settles.)
    expect(document.body).toHaveFocus()

    worldSearch = "ok"
    await parkedSearches.at(-1)!.answer("ok")
    await waitFor(() => expect(explorer).toHaveFocus())
    expect(said).toEqual(["World changed to World w1."])
  })

  it.each([
    ["unavailable", "missing", "World unavailable"],
    ["error", "broken", "World information unavailable"],
  ] as const)("an %s explorer takes the heading focus and keeps its message", async (_name, outcome, message) => {
    worldSearch = outcome
    await chooseExplorerWorld()

    const explorer = await heading("Campaign World")
    await screen.findByRole("heading", { level: 2, name: message })
    await waitFor(() => expect(explorer).toHaveFocus())
    await settle()
    expect(said).toEqual(["World changed to World w1."])
  })

  it("a person who moved focus away while it loaded keeps it", async () => {
    worldSearch = "parked"
    await chooseExplorerWorld()
    await heading("Campaign World")
    await waitFor(() => expect(parkedSearches.length).toBeGreaterThan(0))
    const other = elsewhere()
    act(() => other.focus())

    worldSearch = "ok"
    await parkedSearches.at(-1)!.answer("ok")
    await settle()

    expect(other).toHaveFocus()
  })
})

// ---- Ordinary World and Timeline arrival (state.announce) -----------------------------------------

describe("ordinary World and Timeline arrival with a confirmed-write message", () => {
  const go = async (to: string, state: unknown) => {
    await act(async () => {
      await router.navigate(to, { state })
    })
  }
  // The same entry restated by the owners that stamp it, as they do after the page has arrived: the real writer.
  const restate = writeStamp

  it.each([
    ["World", "/worlds/w1", "World w1"],
    ["Timeline", "/worlds/w1/timelines/t-w1", "Timeline w1"],
  ])("%s: announced once after a successful read, the heading focused once, a later restating of the entry neither repeats nor steals", async (_name, path, title) => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    watchAnnouncer()

    await go(path, { announce: "Saved the record." })

    const page = await heading(title)
    await waitFor(() => expect(page).toHaveFocus())
    await waitFor(() => expect(said).toEqual(["Saved the record."]))
    await waitFor(() => expect(stamp()).toBeDefined())
    await settle()

    const other = elsewhere()
    act(() => other.focus())
    await restate()
    await settle()

    expect(said).toEqual(["Saved the record."])
    expect(other).toHaveFocus()
  })

  it.each([
    ["World", "/worlds/w1", "broken", "World", "The world could not be loaded"],
    ["World", "/worlds/w1", "missing", "World not available", "This world does not exist"],
    ["Timeline", "/worlds/w1/timelines/t-w1", "broken", "Timeline", "The timeline could not be loaded"],
    ["Timeline", "/worlds/w1/timelines/t-w1", "missing", "Timeline not available", "This timeline does not exist"],
  ] as const)(
    "%s %s read that fails after a confirmed write (%s): the confirmed message is announced once, the heading is focused, nothing repeats",
    async (_noun, path, outcome, title, alert) => {
      mount("/app/alpha/knowledge")
      await heading("Knowledge")
      watchAnnouncer()
      worldRead = outcome

      await go(path, { announce: "Saved the record." })

      const page = await heading(title)
      await waitFor(() => expect(page).toHaveFocus())
      expect(await screen.findByRole("alert")).toHaveTextContent(alert)
      await waitFor(() => expect(said).toEqual(["Saved the record."]))
      await waitFor(() => expect(stamp()).toBeDefined())

      const other = elsewhere()
      act(() => other.focus())
      await restate()
      await settle()

      expect(said).toEqual(["Saved the record."])
      expect(other).toHaveFocus()
    },
  )

  it("a navigation that carries no message and fails to read still focuses the error heading once", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    watchAnnouncer()
    worldRead = "missing"

    await go("/worlds/w1", null)

    const page = await heading("World not available")
    await waitFor(() => expect(page).toHaveFocus())
    await settle()
    expect(said).toEqual([])
  })
})

// ---------------------------------------------------------------------------------------------------
// P02-5 third correction. One validated arrival: announcement and focus share the context eligibility.
// The Navbar menu's campaign choice focuses the settled destination heading. Page-arrival
// de-duplication is by operation, not by message text.
// ---------------------------------------------------------------------------------------------------

describe("announcement and focus share one eligibility (route shape matches, committed context does not)", () => {
  it("/app/:c/world with a marker naming another World neither announces nor claims the heading focus", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    act(() => (document.activeElement as HTMLElement | null)?.blur())
    watchAnnouncer()

    await act(async () => {
      await router.navigate("/app/alpha/world", { state: { selection: { level: "world", id: "w2" } } })
    })

    const explorer = await heading("Campaign World")
    await waitFor(() => expect(stamp()).toBeDefined())
    await settle()
    expect(said).toEqual([])
    expect(explorer).not.toHaveFocus()
  })

  it("a perspective that is not authorized (the store does not commit it) neither announces nor claims focus", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    act(() => (document.activeElement as HTMLElement | null)?.blur())
    watchAnnouncer()

    await act(async () => {
      await router.navigate("/app/alpha/characters/stranger", {
        state: { selection: { level: "character", id: "stranger", campaignId: "alpha" } },
      })
    })

    const page = await screen.findByRole("heading", { level: 1 })
    await settle()
    expect(said).toEqual([])
    expect(page).not.toHaveFocus()
  })

  it("a legitimate deferred arrival stays pending until its own context settles, then focuses once", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    watchAnnouncer()
    parkCharacters = true

    choose("a2")
    await waitFor(() => expect(parkedCharacters.some((read) => read.id === "a2")).toBe(true))
    parkCharacters = false
    await parkedFor("a2").answer("ok")

    const record = await heading("Character a2")
    await waitFor(() => expect(record).toHaveFocus())
    await waitFor(() => expect(said).toEqual(["Viewing as Name a2."]))
  })
})

// ---- Focus after an accepted Navbar-menu campaign change -------------------------------------------

describe("an accepted Navbar-menu campaign change focuses the settled destination heading", () => {
  it("menu: the Campaign Home heading takes focus once, from the activated link or from nowhere", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    openCampaignMenu()

    menuCampaign("Campaign beta")

    const home = await heading("Campaign Home")
    await waitFor(() => expect(home).toHaveFocus())
    expect(where()).toBe("/app/beta/home")
  })

  it("deferred: nothing is focused while the destination loads; the settled heading is, once", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    parkSummary = true
    openCampaignMenu()

    menuCampaign("Campaign beta")

    await waitFor(() => expect(parkedSummaries.length).toBeGreaterThan(0))
    const loading = await heading("Loading campaign")
    await settle()
    expect(loading).not.toHaveFocus()

    parkSummary = false
    await parkedSummaries.at(-1)!.answer()
    const home = await heading("Campaign Home")
    await waitFor(() => expect(home).toHaveFocus())
  })

  it("drawer: the drawer closes and the destination heading takes focus", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    fireEvent.click(screen.getByRole("button", { name: /Open navigation/ }))
    openCampaignMenu()

    menuCampaign("Campaign beta")

    const home = await heading("Campaign Home")
    await waitFor(() => expect(home).toHaveFocus())
    expect(screen.getByRole("navigation", { name: "Main" }).classList.contains("portal-sidebar--mobile-open")).toBe(false)
  })

  it("Stay returns focus to the activated link and focuses no heading; Leave then focuses the destination", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    typeDraft()
    openCampaignMenu()

    menuCampaign("Campaign beta")
    await answer("Stay")
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    await waitFor(() => expect(main().getByRole("link", { name: "Campaign beta" })).toHaveFocus())
    expect(screen.getByRole("heading", { level: 1, name: "Knowledge" })).not.toHaveFocus()

    menuCampaign("Campaign beta")
    await answer("Leave")

    const home = await heading("Campaign Home")
    await waitFor(() => expect(home).toHaveFocus())
  })

  it("a person who moved focus away while the destination loaded keeps it", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    parkSummary = true
    openCampaignMenu()

    menuCampaign("Campaign beta")
    await waitFor(() => expect(parkedSummaries.length).toBeGreaterThan(0))
    const other = elsewhere()
    act(() => other.focus())

    parkSummary = false
    await parkedSummaries.at(-1)!.answer()
    await heading("Campaign Home")
    await settle()

    expect(other).toHaveFocus()
  })

  it("a choice answered Stay and superseded by another focuses only the accepted destination, once", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    typeDraft()
    openCampaignMenu()

    menuCampaign("Campaign beta")
    await answer("Stay")
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    if (main().queryByRole("link", { name: "Campaign gamma" }) === null) openCampaignMenu()
    menuCampaign("Campaign gamma")
    await answer("Leave")

    const home = await heading("Campaign Home")
    expect(where()).toBe("/app/gamma/home")
    await waitFor(() => expect(home).toHaveFocus())
    await settle()
    expect(home).toHaveFocus()
  })

  it("an Infobox focus is not stolen by an unrelated menu link being focused", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    parkCharacters = true

    choose("a2")
    await waitFor(() => expect(parkedCharacters.some((read) => read.id === "a2")).toBe(true))
    openCampaignMenu()
    const link = main().getByRole("link", { name: "Campaign beta" })
    act(() => link.focus())
    parkCharacters = false
    await parkedFor("a2").answer("ok")
    await heading("Character a2")
    await settle()

    expect(link).toHaveFocus()
  })
})

// ---- Operation-aware de-duplication of an ordinary arrival ----------------------------------------

describe("two distinct successes that replace the same address with the same message", () => {
  const SAVED = "Saved the record."
  // A distinct operation: a REPLACE of the address the page is on, with the state its producer builds
  // (no context stamp: the stamp owners add it afterwards).
  const succeed = async () => {
    await act(async () => {
      await router.navigate({ pathname: "/worlds/w1" }, { replace: true, state: { announce: SAVED } })
    })
  }
  const restate = writeStamp

  async function firstSuccess() {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    watchAnnouncer()
    await act(async () => {
      await router.navigate("/worlds/w1", { state: { announce: SAVED } })
    })
    const page = await heading("World w1")
    await waitFor(() => expect(page).toHaveFocus())
    await waitFor(() => expect(said).toEqual([SAVED]))
    await waitFor(() => expect(stamp()).toBeDefined())
    await settle()
    return page
  }

  it("each gets its own feedback; the stamp that follows each adds none", async () => {
    const page = await firstSuccess()
    act(() => elsewhere().focus())

    await succeed()
    await waitFor(() => expect(said).toEqual([SAVED, SAVED]))
    await waitFor(() => expect(page).toHaveFocus())
    await waitFor(() => expect(stamp()).toBeDefined())
    await settle()
    expect(said).toEqual([SAVED, SAVED])

    // A stamp after the second, with focus deliberately elsewhere: nothing is repeated or restored.
    act(() => elsewhere().focus())
    await restate()
    await settle()
    expect(said).toEqual([SAVED, SAVED])
    expect(elsewhere()).toHaveFocus()

    await succeed()
    await waitFor(() => expect(said).toEqual([SAVED, SAVED, SAVED]))
  })

  it("a newer navigation after the second success restores no focus and repeats nothing", async () => {
    await firstSuccess()

    await succeed()
    await waitFor(() => expect(said).toEqual([SAVED, SAVED]))
    await act(async () => {
      await router.navigate("/app/alpha/knowledge")
    })
    const knowledge = await heading("Knowledge")
    await settle()

    expect(said).toEqual([SAVED, SAVED])
    expect(knowledge).not.toHaveFocus()
  })
})

// ---- A stamp is what the writer wrote, not what looks like one -------------------------------------

describe("the internal stamp is identified by the writer, never by resemblance", () => {
  const SAVED = "Saved the record."
  const retaining = async (extra: Record<string, unknown> = {}, address: { search?: string; hash?: string } = {}) => {
    const current = router.state.location
    await act(async () => {
      await router.navigate(
        { pathname: current.pathname, search: address.search ?? "", hash: address.hash ?? "" },
        { replace: true, state: { ...(current.state as object), announce: SAVED, ...extra } },
      )
    })
  }

  async function firstSuccess() {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    watchAnnouncer()
    await act(async () => {
      await router.navigate("/worlds/w1", { state: { announce: SAVED } })
    })
    const page = await heading("World w1")
    await waitFor(() => expect(page).toHaveFocus())
    await waitFor(() => expect(said).toEqual([SAVED]))
    await waitFor(() => expect(stamp()).toBeDefined())
    await settle()
    return page
  }

  it("a second same-address REPLACE that retains ctx and repeats the text is a new operation; each actual stamp adds nothing", async () => {
    const page = await firstSuccess()
    act(() => elsewhere().focus())

    // Retains exactly the ctx the first stamp wrote: nothing differs from a stamp but the writer.
    await retaining()
    await waitFor(() => expect(said).toEqual([SAVED, SAVED]))
    await waitFor(() => expect(page).toHaveFocus())

    // An actual stamp follows the second operation: no duplicate announcement, no focus restored.
    act(() => elsewhere().focus())
    await writeStamp(ctxOf("a1"))
    await settle()
    expect(said).toEqual([SAVED, SAVED])
    expect(elsewhere()).toHaveFocus()

    // And a third operation is again its own.
    await retaining()
    await waitFor(() => expect(said).toEqual([SAVED, SAVED, SAVED]))
  })

  it("a look-alike external replacement (a stamp's shape, written by someone else) gets its own feedback", async () => {
    await firstSuccess()

    await retaining({ ctx: ctxOf("a1") })

    await waitFor(() => expect(said).toEqual([SAVED, SAVED]))
  })

  it("an operation that supersedes a stamp before it lands is its own arrival and its later stamp is not another", async () => {
    await firstSuccess()
    const before = router.state.location

    await act(async () => {
      // The writer asks to stamp the entry the page is on; the operation replaces it first.
      replaceOwnEntry({
        router,
        navigate: vi.fn() as never,
        location: before,
        entryKey: "no-longer-current",
        next: (entry) => ({ search: entry.search, state: { ...(entry.state as object), ctx: ctxOf("a1") } }),
      })
      await router.navigate({ pathname: before.pathname }, { replace: true, state: { announce: SAVED } })
    })
    await waitFor(() => expect(said).toEqual([SAVED, SAVED]))
    await writeStamp(ctxOf("a1"))
    await settle()

    expect(said).toEqual([SAVED, SAVED])
  })

  it.each([
    ["a changed query", { search: "?x=1" }],
    ["a hash", { hash: "#notes" }],
  ])("%s with the same message is an operation of its own", async (_name, address) => {
    await firstSuccess()

    await retaining({}, address)

    await waitFor(() => expect(said).toEqual([SAVED, SAVED]))
  })

  it("a selection arrival survives its own stamp but not a look-alike replacement", async () => {
    mount("/app/alpha/knowledge")
    await heading("Knowledge")
    parkCharacters = true

    choose("a2")
    await waitFor(() => expect(parkedCharacters.some((read) => read.id === "a2")).toBe(true))
    await waitFor(() => expect(stamp()).toMatchObject({ characterId: "a2" }))
    // Not written by the stamp writer: the same entry with only ctx changed.
    const current = router.state.location
    await act(async () => {
      await router.navigate(
        { pathname: current.pathname, search: current.search, hash: current.hash },
        { replace: true, state: { ...(current.state as object), ctx: ctxOf("a1") } },
      )
    })
    parkCharacters = false
    await parkedFor("a2").answer("ok")
    const record = await heading("Character a2")
    await settle()

    expect(record).not.toHaveFocus()
    expect(select()).toHaveFocus()
  })
})

// ---- Nothing unmarked keeps a selection arrival; the staged page's own normalization does ----------

describe.each([
  ["plain", false],
  ["StrictMode", true],
])("the selection arrival's lifetime across same-address replacements (%s)", (_name, strict) => {
  async function deferredChoice() {
    mount("/app/alpha/knowledge", strict)
    await heading("Knowledge")
    parkCharacters = true
    choose("a2")
    await waitFor(() => expect(parkedCharacters.some((read) => read.id === "a2")).toBe(true))
    await waitFor(() => expect(stamp()).toMatchObject({ characterId: "a2" }))
  }
  const replaceWith = async (change: { search?: string; hash?: string }, state: unknown) => {
    const current = router.state.location
    await act(async () => {
      await router.navigate(
        { pathname: current.pathname, search: change.search ?? current.search, hash: change.hash ?? current.hash },
        { replace: true, state },
      )
    })
  }
  const settleDestination = async () => {
    parkCharacters = false
    await parkedFor("a2").answer("ok")
    const record = await heading("Character a2")
    await settle()
    return record
  }

  it("the real normalization of the missing section, with the stamp, keeps the arrival: the heading is focused once", async () => {
    await deferredChoice()

    const record = await settleDestination()

    await waitFor(() => expect(router.state.location.search).toBe("?section=sheet"))
    await waitFor(() => expect(record).toHaveFocus())
    expect(where()).toBe("/app/alpha/characters/a2")
  })

  it("an external REPLACE with exactly the same address and state ends it", async () => {
    await deferredChoice()
    const current = router.state.location

    await replaceWith({}, { ...(current.state as object) })
    const record = await settleDestination()

    expect(record).not.toHaveFocus()
    expect(select()).toHaveFocus()
  })

  it("an external look-alike of the section normalization (same section, same state shape) ends it", async () => {
    await deferredChoice()
    const current = router.state.location

    await replaceWith({ search: "?section=sheet" }, { ...(current.state as object) })
    const record = await settleDestination()

    expect(record).not.toHaveFocus()
    expect(select()).toHaveFocus()
  })

  it("a newer choice supersedes the arrival: a late normalization of the first neither focuses nor announces", async () => {
    mount("/app/alpha/knowledge", strict)
    await heading("Knowledge")
    watchAnnouncer()
    parkCharacters = true
    choose("a2")
    await waitFor(() => expect(parkedCharacters.some((read) => read.id === "a2")).toBe(true))
    choose("a3")
    await waitFor(() => expect(parkedCharacters.some((read) => read.id === "a3")).toBe(true))

    parkCharacters = false
    await parkedFor("a3").answer("ok")
    const record = await heading("Character a3")
    await waitFor(() => expect(record).toHaveFocus())
    await parkedFor("a2").answer("ok")
    await settle()

    expect(record).toHaveFocus()
    expect(said).toEqual(["Viewing as Name a2.", "Viewing as Name a3."])
  })
})
