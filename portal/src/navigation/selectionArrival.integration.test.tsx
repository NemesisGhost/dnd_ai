import { act, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { StrictMode, useState } from "react"
import { Route, RouterProvider, Routes, createMemoryRouter } from "react-router"
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
import { CharacterSheetRoutePage } from "../pages/CharacterSheetRoutePage"
import { TimelinePage } from "../pages/TimelinePage"
import { WorldOverviewPage } from "../pages/WorldOverviewPage"
import { ThemeProvider } from "../themes/ThemeProvider"
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

function tree(entry: { pathname: string; state?: unknown }) {
  router = createMemoryRouter(
    [
      {
        path: "*",
        element: (
          <RouteSessionProvider>
            <Routes>
              <Route element={<AuthenticatedAppLayout />}>
                <Route element={<WorldWorkspaceLayout />}>
                  <Route path="/worlds/:worldId" element={<WorldOverviewPage />} />
                  <Route path="/worlds/:worldId/timelines/:timelineId" element={<TimelinePage />} />
                </Route>
                <Route path="/app/:campaignId" element={<CampaignSessionBoundary />}>
                  <Route path="home" element={<CampaignHomePage />} />
                  <Route path="knowledge" element={<DraftPage />} />
                  <Route path="characters/all" element={<CampaignCharactersBrowsePage />} />
                  <Route path="characters/:characterId" element={<CharacterSheetRoutePage />} />
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
        return json({ current_session: null, previous_session_recap: null, recent_events: [] })
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
