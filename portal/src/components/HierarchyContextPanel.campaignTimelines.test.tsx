import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { useEffect, useState } from "react"
import { MemoryRouter, Outlet, Route, Routes, useLocation, useNavigate } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { AnnouncerContext } from "./authoring/announcer"
import { CharacterPerspectiveContext } from "../context/CharacterPerspectiveContext"
import { SessionContext } from "../context/SessionContext"
import { WorkspaceHierarchyProvider } from "../context/WorkspaceHierarchyProvider"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { CampaignLayout } from "../layouts/CampaignLayout"
import { WorldWorkspaceLayout } from "../layouts/WorldWorkspaceLayout"
import { installMockServer } from "../test/authoringHarness"
import type { MockServer } from "../test/authoringHarness"
import type { CampaignContext, SessionBootstrap } from "../types/bootstrap"

// Campaign-only Timeline navigation and the inline campaign chooser (docs/UI_DESIGN.md §4.8.12, CN-1).
// jsdom proves the structure and the rules; keyboard, focus visibility and screen-reader behavior are
// real-browser checks that stay pending (plan §6).

const { useCharacterMock } = vi.hoisted(() => ({ useCharacterMock: vi.fn() }))

vi.mock("../hooks/useCharacter", () => ({ useCharacter: useCharacterMock }))
vi.mock("../api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const base = sessionBootstrapFixture.campaigns[0]!

function campaignFor(
  id: string,
  timelineId: string,
  timelineName: string,
  worldCapabilities: string[],
): CampaignContext {
  return {
    ...base,
    campaign_id: id,
    campaign_name: `Campaign ${id}`,
    world_id: "world-a",
    world_name: "World A",
    timeline_id: timelineId,
    timeline_name: timelineName,
    world_capabilities: worldCapabilities,
    character_perspectives: [],
    selected_character_id: null,
  }
}

// A caller who holds no world.view: only their campaigns lead anywhere. C1 and C2 are on Main, C3 on Branch.
const campaignOnly = (...ids: string[]): SessionBootstrap => ({
  ...sessionBootstrapFixture,
  campaigns: [
    campaignFor("c1", "timeline-a", "Main A", []),
    campaignFor("c2", "timeline-a", "Main A", []),
    campaignFor("c3", "timeline-b", "Branch A", []),
  ].filter((item) => ids.length === 0 || ids.includes(item.campaign_id)),
})
// The same campaigns for a caller who also holds world.view, so the world read is sent.
const mixed = (): SessionBootstrap => ({
  ...sessionBootstrapFixture,
  campaigns: [
    campaignFor("c1", "timeline-a", "Main A", ["world.view"]),
    campaignFor("c2", "timeline-a", "Main A", ["world.view"]),
    campaignFor("c3", "timeline-b", "Branch A", ["world.view"]),
  ],
})

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
const worldBody = {
  body: {
    world_id: "world-a",
    name: "World A",
    capabilities: OWNER,
    timelines: [timeline("timeline-a", "Main A"), timeline("timeline-b", "Branch A")],
  },
}

let server: MockServer
let setSession: (session: SessionBootstrap) => void
let seenKeys: Set<string>
const announceOwned = vi.fn()
const withdraw = vi.fn()

function Probe() {
  const location = useLocation()
  const navigate = useNavigate()
  seenKeys.add(location.key)
  return (
    <>
      <button type="button" onClick={() => navigate(location.pathname, { replace: true, state: { restamped: true } })}>
        Restamp this entry
      </button>
      <button type="button" onClick={() => navigate(location.pathname + "?other=1")}>
        Push the same page with a query
      </button>
      <button type="button" onClick={() => navigate("/app/c3/world")}>
        Go to another page
      </button>
      <p data-testid="location">{location.pathname}</p>
      <p data-testid="state">{JSON.stringify(location.state ?? null)}</p>
    </>
  )
}

function Harness({ initial, path }: { initial: SessionBootstrap; path: string }) {
  const [session, update] = useState(initial)
  useEffect(() => {
    setSession = update
  }, [update])
  return (
    <AnnouncerContext.Provider value={{ announce: vi.fn(), announceOwned }}>
      <SessionContext.Provider
        value={{ state: { status: "authenticated", bootstrap: session }, reload: vi.fn(), refresh: vi.fn() }}
      >
        <CharacterPerspectiveContext.Provider
          value={{ getSelectedCharacterId: () => null, selectCharacter: vi.fn() }}
        >
          <MemoryRouter initialEntries={[path]}>
            <WorkspaceHierarchyProvider>
              <Routes>
                <Route element={<Outlet context={{ bootstrap: session, reload: vi.fn() }} />}>
                  <Route element={<WorldWorkspaceLayout />}>
                    <Route path="/worlds/:worldId" element={<h1>World page</h1>} />
                    <Route path="/worlds/:worldId/timelines/:timelineId" element={<h1>Timeline page</h1>} />
                  </Route>
                </Route>
                <Route path="/app/:campaignId" element={<CampaignLayout bootstrap={session} />}>
                  <Route path="home" element={<h1>Campaign home</h1>} />
                  <Route path="world" element={<h1>Campaign world</h1>} />
                </Route>
              </Routes>
              <Probe />
            </WorkspaceHierarchyProvider>
          </MemoryRouter>
        </CharacterPerspectiveContext.Provider>
      </SessionContext.Provider>
    </AnnouncerContext.Provider>
  )
}

const renderAt = (path: string, initial: SessionBootstrap = campaignOnly()) =>
  render(<Harness initial={initial} path={path} />)

const level = (name: "World" | "Timeline" | "Campaign") => screen.getByRole("combobox", { name })
const shown = (select: HTMLElement) => (select as HTMLSelectElement).selectedOptions[0]?.textContent ?? ""
const optionNames = (select: HTMLElement) =>
  within(select)
    .getAllByRole("option")
    .map((option) => option.textContent ?? "")
const location = () => screen.getByTestId("location")
const stateOf = () => JSON.parse(screen.getByTestId("state").textContent ?? "null") as {
  selection?: { level: string; id: string }
  task?: { root: string }
} | null
const chooser = () => screen.queryByRole("group", { name: /^Choose a campaign to open/ })
const chooserLinks = () => within(chooser()!).getAllByRole("link").map((link) => link.textContent)

beforeEach(() => {
  seenKeys = new Set()
  announceOwned.mockReset()
  withdraw.mockReset()
  announceOwned.mockReturnValue(withdraw)
  useCharacterMock.mockReset()
  useCharacterMock.mockReturnValue({ state: { status: "unavailable" }, retry: vi.fn(), authority: null })
  server = installMockServer()
  server.on("GET", /^\/worlds\?status=all/, { body: { items: [], next_cursor: null } })
  server.on("GET", "/worlds/world-a", { status: 404, body: {} })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("campaign-only Timeline destinations", () => {
  it("never reads the world, offers the timelines the caller's campaigns represent, and links no world route", async () => {
    renderAt("/app/c1/home")

    await waitFor(() => expect(level("Timeline")).toBeEnabled())
    expect(server.callsTo("GET", "/worlds/world-a")).toHaveLength(0)
    expect(shown(level("Timeline"))).toBe("Main A")
    expect(optionNames(level("Timeline"))).toEqual(["No selection", "Branch A", "Main A"])
    expect(level("Timeline")).not.toHaveAccessibleDescription()
    for (const anchor of document.querySelectorAll("a")) {
      expect(anchor.getAttribute("href") ?? "").not.toMatch(/^\/worlds\/world-a\/timelines\//)
    }
  })

  it("opens the only campaign on a timeline as a campaign task with the campaign note", async () => {
    renderAt("/app/c1/home")
    await waitFor(() => expect(level("Timeline")).toBeEnabled())

    fireEvent.change(level("Timeline"), { target: { value: "timeline-b" } })

    await waitFor(() => expect(location()).toHaveTextContent("/app/c3/home"))
    expect(stateOf()?.selection).toEqual({ level: "campaign", id: "c3" })
    expect(stateOf()?.task?.root).toBe("campaign")
    expect(chooser()).toBeNull()
  })

  it("disables the level when the only timeline is the one already selected", async () => {
    renderAt("/app/c3/home", campaignOnly("c3"))
    await waitFor(() => expect(level("Timeline")).toBeDisabled())
    expect(level("Timeline")).toHaveAccessibleDescription("No other timeline available")
  })
})

describe("the inline campaign chooser", () => {
  async function openChooser(path = "/app/c3/home") {
    renderAt(path)
    await waitFor(() => expect(level("Timeline")).toBeEnabled())
    act(() => level("Timeline").focus())
    fireEvent.change(level("Timeline"), { target: { value: "timeline-a" } })
    await screen.findByRole("group", { name: "Choose a campaign to open Main A" })
  }

  it("opens beneath the select for a timeline with several campaigns, changing nothing", async () => {
    renderAt("/app/c3/home")
    await waitFor(() => expect(level("Timeline")).toBeEnabled())
    act(() => level("Timeline").focus())
    const requests = server.calls.length
    const entries = seenKeys.size

    fireEvent.change(level("Timeline"), { target: { value: "timeline-a" } })

    const group = await screen.findByRole("group", { name: "Choose a campaign to open Main A" })
    expect(chooserLinks()).toEqual(["Campaign c1", "Campaign c2"])
    expect(within(group).getByRole("button", { name: "Cancel" })).toBeInTheDocument()
    // Not a dialog, and nothing navigated, was requested, committed or moved.
    expect(screen.queryByRole("dialog")).toBeNull()
    expect(location()).toHaveTextContent("/app/c3/home")
    expect(seenKeys.size).toBe(entries)
    expect(server.calls).toHaveLength(requests)
    expect(shown(level("Timeline"))).toBe("Branch A")
    expect(level("Timeline")).toHaveFocus()
    expect(level("Timeline")).toHaveAccessibleDescription("Choose a campaign to open Main A")
    // Directly beneath the Timeline select, before its Campaign section.
    expect(level("Timeline").compareDocumentPosition(group) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    // Announced once, politely, as an owned message.
    expect(announceOwned).toHaveBeenCalledTimes(1)
    expect(announceOwned).toHaveBeenCalledWith("Choose a campaign to open Main A")
  })

  it("lists campaign links with the same request as the Campaign select, and picks nothing itself", async () => {
    await openChooser()

    fireEvent.click(within(chooser()!).getByRole("link", { name: "Campaign c2" }))

    await waitFor(() => expect(location()).toHaveTextContent("/app/c2/home"))
    expect(stateOf()?.selection).toEqual({ level: "campaign", id: "c2" })
    expect(stateOf()?.task?.root).toBe("campaign")
    await waitFor(() => expect(chooser()).toBeNull())
  })

  it("Cancel closes it and returns focus to the select, withdrawing the announcement", async () => {
    await openChooser()

    fireEvent.click(within(chooser()!).getByRole("button", { name: "Cancel" }))

    expect(chooser()).toBeNull()
    expect(level("Timeline")).toHaveFocus()
    expect(withdraw).toHaveBeenCalledTimes(1)
    expect(location()).toHaveTextContent("/app/c3/home")
    expect(level("Timeline")).not.toHaveAccessibleDescription()
  })

  it("Escape closes it without propagating, and returns focus to the select", async () => {
    await openChooser()
    const outer = vi.fn()
    document.addEventListener("keydown", outer)

    const link = within(chooser()!).getByRole("link", { name: "Campaign c1" })
    act(() => link.focus())
    fireEvent.keyDown(link, { key: "Escape" })
    document.removeEventListener("keydown", outer)

    expect(chooser()).toBeNull()
    expect(level("Timeline")).toHaveFocus()
    expect(outer).not.toHaveBeenCalled()
  })

  it("choosing the committed timeline again closes it", async () => {
    await openChooser()

    fireEvent.change(level("Timeline"), { target: { value: "timeline-b" } })

    expect(chooser()).toBeNull()
    expect(location()).toHaveTextContent("/app/c3/home")
  })

  it("a pointer press outside does not close it", async () => {
    await openChooser()

    fireEvent.mouseDown(document.body)
    fireEvent.click(document.body)

    expect(chooser()).not.toBeNull()
  })

  it("any location change closes it, and a reload does not restore it", async () => {
    await openChooser()
    fireEvent.click(within(chooser()!).getByRole("link", { name: "Campaign c1" }))
    await waitFor(() => expect(location()).toHaveTextContent("/app/c1/home"))
    expect(chooser()).toBeNull()

    document.body.replaceChildren()
    renderAt("/app/c3/home")
    await waitFor(() => expect(level("Timeline")).toBeEnabled())
    expect(chooser()).toBeNull()
  })

  it("rides through a REPLACE of the same address (a context stamp), but not a PUSH or another page", async () => {
    await openChooser()

    fireEvent.click(screen.getByRole("button", { name: "Restamp this entry" }))
    await waitFor(() => expect(stateOf()).toMatchObject({ restamped: true }))
    expect(chooser()).not.toBeNull()
    expect(chooserLinks()).toEqual(["Campaign c1", "Campaign c2"])

    fireEvent.click(screen.getByRole("button", { name: "Push the same page with a query" }))
    await waitFor(() => expect(chooser()).toBeNull())
  })

  it("is closed by moving to another page", async () => {
    await openChooser()

    fireEvent.click(screen.getByRole("button", { name: "Go to another page" }))

    await waitFor(() => expect(location()).toHaveTextContent("/app/c3/world"))
    expect(chooser()).toBeNull()
  })

  it("is derived from the current bootstrap: removing one campaign updates it and navigates nothing", async () => {
    await openChooser()

    act(() => setSession(campaignOnly("c1", "c3")))

    await waitFor(() => expect(chooserLinks()).toEqual(["Campaign c1"]))
    // One remaining stays a link the person must choose.
    expect(location()).toHaveTextContent("/app/c3/home")
    expect(chooser()).not.toBeNull()
  })

  it("moves focus to the instruction when the focused entry is removed", async () => {
    await openChooser()
    const link = within(chooser()!).getByRole("link", { name: "Campaign c2" })
    act(() => link.focus())
    expect(link).toHaveFocus()

    act(() => setSession(campaignOnly("c1", "c3")))

    await waitFor(() => expect(chooserLinks()).toEqual(["Campaign c1"]))
    expect(screen.getByText("Choose a campaign to open Main A")).toHaveFocus()
  })

  it("closes with a reason and returns focus to the select when no campaign remains", async () => {
    await openChooser()
    act(() => within(chooser()!).getByRole("link", { name: "Campaign c1" }).focus())

    act(() => setSession(campaignOnly("c3")))

    await waitFor(() => expect(chooser()).toBeNull())
    expect(level("Timeline")).toHaveAccessibleDescription("That timeline is no longer available.")
    // Only the selected timeline is left, so the select is disabled: focus goes to the reason that explains it.
    expect(level("Timeline")).toBeDisabled()
    expect(screen.getByText("That timeline is no longer available.")).toHaveFocus()
    expect(location()).toHaveTextContent("/app/c3/home")
    expect(withdraw).toHaveBeenCalled()
    // Restored access does not reopen what the person did not open again.
    act(() => setSession(campaignOnly()))
    expect(chooser()).toBeNull()
  })
})

describe("a caller with explicit world access as well", () => {
  it("offers world routes when the world read succeeds, even with campaigns on the timelines", async () => {
    server.on("GET", "/worlds/world-a", worldBody)
    renderAt("/app/c3/home", mixed())
    await waitFor(() => expect(optionNames(level("Timeline"))).toEqual(["No selection", "Main A", "Branch A"]))

    fireEvent.change(level("Timeline"), { target: { value: "timeline-a" } })

    await waitFor(() => expect(location()).toHaveTextContent("/worlds/world-a/timelines/timeline-a"))
    expect(chooser()).toBeNull()
  })

  it.each([403, 404])("falls back to the caller's campaigns when the read returns %i", async (status) => {
    server.on("GET", "/worlds/world-a", { status, body: {} })
    renderAt("/app/c3/home", mixed())

    await waitFor(() => expect(server.callsTo("GET", "/worlds/world-a")).not.toHaveLength(0))
    await waitFor(() => expect(optionNames(level("Timeline"))).toEqual(["No selection", "Branch A", "Main A"]))
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull()
    fireEvent.change(level("Timeline"), { target: { value: "timeline-a" } })
    expect(await screen.findByRole("group", { name: "Choose a campaign to open Main A" })).toBeInTheDocument()
    expect(location()).toHaveTextContent("/app/c3/home")
  })

  it("keeps the campaigns and offers one retry when the read fails, and a successful retry closes the chooser", async () => {
    let attempts = 0
    server.on("GET", "/worlds/world-a", () => {
      attempts += 1
      return attempts === 1 ? { status: 500, body: {} } : worldBody
    })
    renderAt("/app/c3/home", mixed())
    await waitFor(() =>
      expect(level("Timeline")).toHaveAccessibleDescription("This world's timelines could not be loaded."),
    )
    expect(level("Timeline")).toBeEnabled()
    fireEvent.change(level("Timeline"), { target: { value: "timeline-a" } })
    await screen.findByRole("group", { name: "Choose a campaign to open Main A" })

    const before = server.calls.length
    fireEvent.click(screen.getByRole("button", { name: "Try again" }))

    await waitFor(() => expect(chooser()).toBeNull())
    expect(server.calls.slice(before).map((call) => `${call.method} ${call.path}`)).toEqual(["GET /worlds/world-a"])
    expect(location()).toHaveTextContent("/app/c3/home")
    // The timeline now has a world destination.
    await waitFor(() => expect(level("Timeline")).toBeEnabled())
    fireEvent.change(level("Timeline"), { target: { value: "timeline-a" } })
    await waitFor(() => expect(location()).toHaveTextContent("/worlds/world-a/timelines/timeline-a"))
  })
})
