import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { Link, MemoryRouter, Outlet, Route, Routes, useLocation, useNavigate } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { CharacterPerspectiveContext } from "../context/CharacterPerspectiveContext"
import { SessionContext } from "../context/SessionContext"
import { WorkspaceHierarchyProvider } from "../context/WorkspaceHierarchyProvider"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { CampaignLayout } from "../layouts/CampaignLayout"
import { WorldWorkspaceLayout } from "../layouts/WorldWorkspaceLayout"
import { installMockServer } from "../test/authoringHarness"
import type { MockServer } from "../test/authoringHarness"
import type { CampaignContext, SessionBootstrap } from "../types/bootstrap"

// Meaningful choice, reasons, retry and stale World options for the Infobox (docs/UI_DESIGN.md §4.8.12).
// The pure rules are in navigation/contextOptions.test.ts; this file proves what the person can perceive.

const { useCharacterMock } = vi.hoisted(() => ({ useCharacterMock: vi.fn() }))

vi.mock("../hooks/useCharacter", () => ({ useCharacter: useCharacterMock }))
vi.mock("../api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const base = sessionBootstrapFixture.campaigns[0]!

function campaignFor(
  id: string,
  worldId: string,
  worldName: string,
  timelineId: string,
  timelineName: string,
): CampaignContext {
  return {
    ...base,
    campaign_id: id,
    campaign_name: `Campaign ${id}`,
    world_id: worldId,
    world_name: worldName,
    timeline_id: timelineId,
    timeline_name: timelineName,
    character_perspectives: [],
    selected_character_id: null,
  }
}

const bootstrap: SessionBootstrap = {
  ...sessionBootstrapFixture,
  campaigns: [
    campaignFor("c1", "world-a", "World A", "timeline-a", "Main A"),
    campaignFor("c2", "world-a", "World A", "timeline-b", "Branch A"),
    campaignFor("c3", "world-b", "World B", "timeline-c", "Main B"),
  ],
}
const noCampaigns: SessionBootstrap = { ...bootstrap, campaigns: [] }

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

const OWNER = ["campaign.create", "timeline.manage", "world.manage", "world.view"]

function LocationProbe() {
  const navigate = useNavigate()
  return (
    <>
      <p data-testid="location">{useLocation().pathname}</p>
      <button type="button" onClick={() => navigate(-1)}>
        Back
      </button>
    </>
  )
}

let server: MockServer

function renderAt(path: string, session: SessionBootstrap = bootstrap) {
  return render(
    <SessionContext.Provider
      value={{
        state: { status: "authenticated", bootstrap: session },
        reload: vi.fn(),
        refresh: vi.fn(),
      }}
    >
      <CharacterPerspectiveContext.Provider
        value={{ getSelectedCharacterId: () => null, selectCharacter: vi.fn() }}
      >
        <MemoryRouter initialEntries={[path]}>
          <WorkspaceHierarchyProvider>
            <Routes>
              <Route element={<Outlet context={{ bootstrap: session, reload: vi.fn() }} />}>
                <Route element={<WorldWorkspaceLayout />}>
                  <Route path="/worlds" element={<h1>All worlds page</h1>} />
                  <Route
                    path="/worlds/:worldId"
                    element={
                      <>
                        <h1>World page</h1>
                        <Link to="/worlds/world-a/timelines">Open timelines</Link>
                      </>
                    }
                  />
                  <Route path="/worlds/:worldId/timelines" element={<h1>Timelines page</h1>} />
                  <Route
                    path="/worlds/:worldId/timelines/:timelineId"
                    element={<h1>Timeline page</h1>}
                  />
                </Route>
              </Route>
              <Route path="/app/:campaignId" element={<CampaignLayout bootstrap={session} />}>
                <Route path="home" element={<h1>Campaign home</h1>} />
                <Route path="world" element={<h1>Campaign world</h1>} />
                <Route path="characters/all" element={<h1>All characters</h1>} />
              </Route>
            </Routes>
            <LocationProbe />
          </WorkspaceHierarchyProvider>
        </MemoryRouter>
      </CharacterPerspectiveContext.Provider>
    </SessionContext.Provider>,
  )
}

function level(name: "World" | "Timeline" | "Campaign") {
  return screen.getByRole("combobox", { name })
}
const character = () => screen.getByRole("combobox", { name: "Character perspective" })
const shown = (select: HTMLElement) => (select as HTMLSelectElement).selectedOptions[0]?.textContent ?? ""
const optionNames = (select: HTMLElement) =>
  within(select)
    .getAllByRole("option")
    .map((option) => option.textContent ?? "")
const location = () => screen.getByTestId("location")

function gate<T>(): { promise: Promise<T>; release: (value: T) => void } {
  let release!: (value: T) => void
  const promise = new Promise<T>((resolve) => {
    release = resolve
  })
  return { promise, release }
}

const worldsList = (...items: [string, string][]) => ({
  body: {
    items: items.map(([world_id, name]) => ({ world_id, name, capabilities: OWNER })),
    next_cursor: null,
  },
})
const worldBody = (id: string, name: string, ...timelines: [string, string][]) => ({
  body: {
    world_id: id,
    name,
    capabilities: OWNER,
    timelines: timelines.map(([tid, tname]) => timeline(tid, tname)),
  },
})
const requestsSince = (count: number) =>
  server.calls.slice(count).map((call) => `${call.method} ${call.path}`)

beforeEach(() => {
  useCharacterMock.mockReset()
  useCharacterMock.mockReturnValue({ state: { status: "unavailable" }, retry: vi.fn(), authority: null })
  server = installMockServer()
  server.on("GET", /^\/worlds\?status=all/, worldsList(["world-a", "World A"], ["world-b", "World B"]))
  server.on("GET", "/worlds/world-a", worldBody("world-a", "World A", ["timeline-a", "Main A"], ["timeline-b", "Branch A"]))
  server.on("GET", "/worlds/world-b", worldBody("world-b", "World B", ["timeline-c", "Main B"]))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("meaningful choice (CN-2)", () => {
  it("disables a level whose sole option is already selected, with an accessible reason", async () => {
    server.on("GET", /^\/worlds\?status=all/, worldsList(["world-a", "World A"]))
    server.on("GET", "/worlds/world-a", worldBody("world-a", "World A", ["timeline-a", "Main A"]))
    // Only c1 is on world-a/timeline-a, so each level has exactly one option, and it is selected.
    renderAt("/app/c1/home", { ...bootstrap, campaigns: [bootstrap.campaigns[0]!] })

    await waitFor(() => expect(level("World")).toBeDisabled())
    expect(level("World")).toHaveAccessibleDescription("No other world available")
    expect(shown(level("World"))).toBe("World A")
    await waitFor(() => expect(level("Timeline")).toBeDisabled())
    await waitFor(() => expect(level("Timeline")).toHaveAccessibleDescription("No other timeline available"))
    expect(level("Campaign")).toBeDisabled()
    expect(level("Campaign")).toHaveAccessibleDescription("No other campaign available")
    expect(shown(level("Campaign"))).toBe("Campaign c1")
  })

  it("enables a sole option when nothing is selected, and says nothing about it", async () => {
    server.on("GET", /^\/worlds\?status=all/, worldsList(["world-a", "World A"]))
    renderAt("/worlds", noCampaigns)

    await waitFor(() => expect(level("World")).toBeEnabled())
    expect(level("World")).not.toHaveAccessibleDescription()
    expect(shown(level("World"))).toBe("No selection")
  })

  it("says 'No world available' when there is nothing to choose", async () => {
    server.on("GET", /^\/worlds\?status=all/, worldsList())
    renderAt("/worlds", noCampaigns)

    await waitFor(() => expect(level("World")).toHaveAccessibleDescription("No world available"))
    expect(level("World")).toBeDisabled()
  })

  it("Timeline: a sole timeline is enabled until it is the selected one", async () => {
    server.on("GET", "/worlds/world-a", worldBody("world-a", "World A", ["timeline-a", "Main A"]))
    const first = renderAt("/worlds/world-a", noCampaigns)
    await waitFor(() => expect(level("Timeline")).toBeEnabled())
    expect(level("Timeline")).not.toHaveAccessibleDescription()
    first.unmount()

    renderAt("/worlds/world-a/timelines/timeline-a", noCampaigns)
    await waitFor(() => expect(level("Timeline")).toHaveAccessibleDescription("No other timeline available"))
    expect(level("Timeline")).toBeDisabled()
    expect(shown(level("Timeline"))).toBe("Main A")
  })

  it("Campaign: asks for a timeline first until one is selected", async () => {
    renderAt("/worlds/world-a")
    await waitFor(() => expect(level("Timeline")).toBeEnabled())
    expect(level("Campaign")).toBeDisabled()
    expect(level("Campaign")).toHaveAccessibleDescription("Select a timeline first")
  })

  it("Campaign: 'No campaign available' for a timeline no campaign of the caller is on", async () => {
    server.on("GET", "/worlds/world-a", worldBody("world-a", "World A", ["timeline-z", "Unused"]))
    renderAt("/worlds/world-a/timelines/timeline-z")
    await waitFor(() => expect(shown(level("Timeline"))).toBe("Unused"))
    expect(level("Campaign")).toHaveAccessibleDescription("No campaign available")
  })

  it("gives the Character level its own reason when no campaign is selected", async () => {
    renderAt("/worlds/world-a")
    await waitFor(() => expect(level("World")).toBeEnabled())
    expect(character()).toBeDisabled()
    expect(character()).toHaveAccessibleDescription("Select a campaign first")
  })

  it("never lets a display-only current value be chosen", async () => {
    server.on("GET", /^\/worlds\?status=all/, worldsList(["world-b", "World B"]))
    renderAt("/worlds/world-a", noCampaigns)

    await waitFor(() => expect(shown(level("World"))).toBe("World A"))
    const current = within(level("World")).getByRole("option", { name: "World A" }) as HTMLOptionElement
    expect(current.disabled).toBe(true)
    fireEvent.change(level("World"), { target: { value: "world-a" } })
    expect(location()).toHaveTextContent("/worlds/world-a")
    fireEvent.change(level("World"), { target: { value: "world-b" } })
    expect(location()).toHaveTextContent("/worlds/world-b")
  })
})

describe("loading, failure and retry", () => {
  it("shows 'Loading worlds…' while the list is pending, with no campaign-derived entry yet", async () => {
    const list = gate<{ body: unknown }>()
    server.on("GET", /^\/worlds\?status=all/, () => list.promise)
    renderAt("/app/c3/home")

    expect(level("World")).toBeDisabled()
    expect(level("World")).toHaveAccessibleDescription("Loading worlds…")
    expect(optionNames(level("World"))).toEqual(["No selection", "World B"])
    list.release(worldsList(["world-a", "World A"], ["world-b", "World B"]))
    await waitFor(() => expect(level("World")).toBeEnabled())
  })

  it("distinguishes a failed worlds list from an empty one, and retries only that read", async () => {
    let attempts = 0
    server.on("GET", /^\/worlds\?status=all/, () => {
      attempts += 1
      return attempts === 1 ? { status: 500, body: {} } : worldsList(["world-z", "World Z"])
    })
    renderAt("/app/c1/home")

    await waitFor(() => expect(level("World")).toHaveAccessibleDescription("Your worlds could not be loaded."))
    // Campaign-derived entries stay offered, and the failure never reads as "no worlds".
    expect(level("World")).toBeEnabled()
    expect(optionNames(level("World"))).toEqual(["No selection", "World A", "World B"])
    const before = server.calls.length
    const retry = screen.getByRole("button", { name: "Try again" })
    retry.focus()
    fireEvent.click(retry)

    await waitFor(() => expect(screen.queryByRole("button", { name: "Try again" })).toBeNull())
    expect(requestsSince(before)).toEqual(["GET /worlds?status=all&limit=100"])
    expect(level("World")).not.toHaveAccessibleDescription()
    expect(optionNames(level("World"))).toContain("World Z")
    await waitFor(() => expect(level("World")).toHaveFocus())
    expect(location()).toHaveTextContent("/app/c1/home")
  })

  it("a failed retry leaves focus on the button and repeats nothing else", async () => {
    server.on("GET", /^\/worlds\?status=all/, { status: 500, body: {} })
    renderAt("/app/c1/home")
    const retry = await screen.findByRole("button", { name: "Try again" })
    retry.focus()
    const before = server.calls.length
    fireEvent.click(retry)

    await waitFor(() => expect(requestsSince(before)).toEqual(["GET /worlds?status=all&limit=100"]))
    await waitFor(() => expect(screen.getByRole("button", { name: "Try again" })).toHaveFocus())
    expect(location()).toHaveTextContent("/app/c1/home")
  })

  it("shows 'Loading timelines…' while the world's first read is pending", async () => {
    const pending = gate<{ body: unknown }>()
    server.on("GET", "/worlds/world-a", () => pending.promise)
    renderAt("/app/c1/home")

    await waitFor(() => expect(level("Timeline")).toHaveAccessibleDescription("Loading timelines…"))
    expect(level("Timeline")).toBeDisabled()
    expect(shown(level("Timeline"))).toBe("Main A")
  })

  it("distinguishes a transient world-read failure from a refusal, and retries only that read", async () => {
    let attempts = 0
    server.on("GET", "/worlds/world-a", () => {
      attempts += 1
      return attempts === 1
        ? { status: 500, body: {} }
        : worldBody("world-a", "World A", ["timeline-a", "Main A"], ["timeline-b", "Branch A"])
    })
    renderAt("/app/c1/home")

    await waitFor(() =>
      expect(level("Timeline")).toHaveAccessibleDescription("This world's timelines could not be loaded."),
    )
    const before = server.calls.length
    const retry = screen.getByRole("button", { name: "Try again" })
    retry.focus()
    fireEvent.click(retry)

    await waitFor(() => expect(level("Timeline")).toBeEnabled())
    expect(requestsSince(before)).toEqual(["GET /worlds/world-a"])
    expect(optionNames(level("Timeline"))).toEqual(["No selection", "Main A", "Branch A"])
    await waitFor(() => expect(level("Timeline")).toHaveFocus())
    expect(location()).toHaveTextContent("/app/c1/home")
  })

  it("a refusal is not a failure: no retry is offered, and the caller's own campaigns still lead somewhere", async () => {
    server.on("GET", "/worlds/world-a", { status: 404, body: {} })
    renderAt("/app/c1/home")

    await waitFor(() => expect(server.callsTo("GET", "/worlds/world-a")).not.toHaveLength(0))
    await waitFor(() => expect(optionNames(level("Timeline"))).toEqual(["No selection", "Branch A", "Main A"]))
    expect(level("Timeline")).not.toHaveAccessibleDescription()
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull()
  })
})

describe("stale World options", () => {
  it("withdraws an explicit World option once a newer world read is refused", async () => {
    server.on("GET", "/worlds/world-a", { status: 404, body: {} })
    renderAt("/worlds", noCampaigns)
    await waitFor(() => expect(optionNames(level("World"))).toEqual(["No selection", "World A", "World B"]))

    fireEvent.change(level("World"), { target: { value: "world-a" } })

    expect(location()).toHaveTextContent("/worlds/world-a")
    await waitFor(() => expect(optionNames(level("World"))).toEqual(["No selection", "World B"]))
  })

  it("keeps the world reachable through a campaign when only its explicit access is refused", async () => {
    server.on("GET", "/worlds/world-a", { status: 404, body: {} })
    renderAt("/worlds")
    await waitFor(() => expect(level("World")).toBeEnabled())

    fireEvent.change(level("World"), { target: { value: "world-a" } })

    await waitFor(() => expect(server.callsTo("GET", "/worlds/world-a")).not.toHaveLength(0))
    await waitFor(() => expect(level("World")).toBeEnabled())
    expect(optionNames(level("World"))).toContain("World A")
    // It now leads through the campaign's World page, never the refused world route.
    fireEvent.change(level("World"), { target: { value: "world-a" } })
    await waitFor(() => expect(location()).toHaveTextContent("/app/c1/world"))
  })

  it("ignores a refusal that STARTED before a later list read, however late it answers", async () => {
    const refusal = gate<{ status: number; body: unknown }>()
    let listAttempts = 0
    server.on("GET", /^\/worlds\?status=all/, () => {
      listAttempts += 1
      return listAttempts === 1 ? { status: 500, body: {} } : worldsList(["world-a", "World A"], ["world-b", "World B"])
    })
    server.on("GET", "/worlds/world-a", () => refusal.promise)
    renderAt("/worlds/world-a", noCampaigns)
    // The first list failed; "Try again" starts a NEWER list read, after the world read began.
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }))
    await waitFor(() => expect(level("World")).toBeEnabled())
    expect(optionNames(level("World"))).toEqual(["No selection", "World A", "World B"])

    // The older refusal now answers: it does not outrank the newer list.
    refusal.release({ status: 404, body: {} })
    await waitFor(() => expect(level("World")).toBeEnabled())
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(optionNames(level("World"))).toEqual(["No selection", "World A", "World B"])
  })

  it("restores the option when a LATER read of that world succeeds", async () => {
    let attempts = 0
    server.on("GET", "/worlds/world-a", () => {
      attempts += 1
      return attempts === 1 ? { status: 404, body: {} } : worldBody("world-a", "World A", ["timeline-a", "Main A"])
    })
    renderAt("/worlds", noCampaigns)
    await waitFor(() => expect(level("World")).toBeEnabled())
    fireEvent.change(level("World"), { target: { value: "world-a" } })
    await waitFor(() => expect(optionNames(level("World"))).toEqual(["No selection", "World B"]))

    // Moving within the same world makes the provider read it again (a newer read).
    fireEvent.click(screen.getByRole("link", { name: "Open timelines" }))

    await waitFor(() => expect(optionNames(level("World"))).toEqual(["No selection", "World A", "World B"]))
    expect(attempts).toBe(2)
  })

  it("records nothing when a read is aborted by moving to another world", async () => {
    const aborted = gate<{ status: number; body: unknown }>()
    server.on("GET", "/worlds/world-a", () => aborted.promise)
    renderAt("/worlds/world-a", noCampaigns)
    await waitFor(() => expect(level("World")).toBeEnabled())

    fireEvent.change(level("World"), { target: { value: "world-b" } })
    await waitFor(() => expect(location()).toHaveTextContent("/worlds/world-b"))
    aborted.release({ status: 404, body: {} })
    await waitFor(() => expect(level("Timeline")).toBeEnabled())
    await new Promise((resolve) => setTimeout(resolve, 20))

    expect(optionNames(level("World"))).toEqual(["No selection", "World A", "World B"])
  })

  it("a transient failure is not evidence: the explicit option stays", async () => {
    server.on("GET", "/worlds/world-a", { status: 500, body: {} })
    renderAt("/worlds", noCampaigns)
    await waitFor(() => expect(level("World")).toBeEnabled())

    fireEvent.change(level("World"), { target: { value: "world-a" } })
    await waitFor(() => expect(server.callsTo("GET", "/worlds/world-a")).not.toHaveLength(0))
    await waitFor(() => expect(level("Timeline")).toHaveAccessibleDescription("This world's timelines could not be loaded."))

    expect(optionNames(level("World"))).toEqual(["No selection", "World A", "World B"])
  })

  it("commits only the last of two rapid World choices", async () => {
    server.on(
      "GET",
      /^\/worlds\?status=all/,
      worldsList(["world-a", "World A"], ["world-b", "World B"], ["world-c", "World C"]),
    )
    const slow = gate<{ body: unknown }>()
    server.on("GET", "/worlds/world-b", () => slow.promise)
    server.on("GET", "/worlds/world-c", worldBody("world-c", "World C", ["timeline-d", "Main C"]))
    renderAt("/worlds", noCampaigns)
    await waitFor(() => expect(level("World")).toBeEnabled())

    fireEvent.change(level("World"), { target: { value: "world-b" } })
    fireEvent.change(level("World"), { target: { value: "world-c" } })
    slow.release(worldBody("world-b", "World B", ["timeline-c", "Main B"]))

    await waitFor(() => expect(shown(level("World"))).toBe("World C"))
    expect(location()).toHaveTextContent("/worlds/world-c")
    expect(optionNames(level("Timeline"))).toEqual(["No selection", "Main C"])
    expect(optionNames(level("World"))).toEqual(["No selection", "World A", "World B", "World C"])
  })

  it("does not revive a refused World option when Back returns to an earlier entry", async () => {
    server.on("GET", "/worlds/world-a", { status: 404, body: {} })
    renderAt("/worlds", noCampaigns)
    await waitFor(() => expect(level("World")).toBeEnabled())
    fireEvent.change(level("World"), { target: { value: "world-a" } })
    await waitFor(() => expect(optionNames(level("World"))).toEqual(["No selection", "World B"]))

    fireEvent.click(screen.getByRole("button", { name: "Back" }))

    await waitFor(() => expect(location()).toHaveTextContent("/worlds"))
    expect(location()).not.toHaveTextContent("world-a")
    expect(optionNames(level("World"))).toEqual(["No selection", "World B"])
  })
})
