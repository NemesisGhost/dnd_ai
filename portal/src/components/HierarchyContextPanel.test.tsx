import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { MemoryRouter, Outlet, Route, Routes, useLocation } from "react-router"
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
    character_perspectives: [
      { character_id: `${id}-hero`, character_name: `Hero of ${id}`, authorized_parties: [] },
      { character_id: `${id}-ally`, character_name: `Ally of ${id}`, authorized_parties: [] },
    ],
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

const selectCharacter = vi.fn()

function LocationProbe() {
  return <p data-testid="location">{useLocation().pathname}</p>
}

let server: MockServer

function renderAt(
  path: string,
  selectedCharacterId: string | null = null,
  session: SessionBootstrap = bootstrap,
) {
  return render(
    <SessionContext.Provider
      value={{
        state: { status: "authenticated", bootstrap: session },
        reload: vi.fn(),
        refresh: vi.fn(),
      }}
    >
      <CharacterPerspectiveContext.Provider
        value={{ getSelectedCharacterId: () => selectedCharacterId, selectCharacter }}
      >
        <MemoryRouter initialEntries={[path]}>
          <WorkspaceHierarchyProvider>
            <Routes>
              {/* The shell supplies the authenticated outlet context. */}
              <Route element={<Outlet context={{ bootstrap: session, reload: vi.fn() }} />}>
              <Route element={<WorldWorkspaceLayout />}>
                <Route path="/worlds" element={<h1>All worlds page</h1>} />
                <Route path="/worlds/:worldId" element={<h1>World page</h1>} />
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

// The selected option's text, so "No selection" is observable.
function shown(select: HTMLElement): string {
  return (select as HTMLSelectElement).selectedOptions[0]?.textContent ?? ""
}

function optionNames(select: HTMLElement): string[] {
  return within(select)
    .getAllByRole("option")
    .map((option) => option.textContent ?? "")
}

// world_owner's server-computed world capabilities.
const OWNER = ["campaign.create", "timeline.manage", "world.manage", "world.view"]

beforeEach(() => {
  selectCharacter.mockReset()
  useCharacterMock.mockReset()
  useCharacterMock.mockReturnValue({ state: { status: "unavailable" }, retry: vi.fn() })
  server = installMockServer()
  server.on("GET", /^\/worlds\?status=all/, {
    body: {
      items: [
        { world_id: "world-a", name: "World A", capabilities: OWNER },
        { world_id: "world-b", name: "World B", capabilities: OWNER },
      ],
      next_cursor: null,
    },
  })
  server.on("GET", "/worlds/world-a", {
    body: {
      world_id: "world-a",
      name: "World A",
      capabilities: OWNER,
      timelines: [timeline("timeline-a", "Main A"), timeline("timeline-b", "Branch A")],
    },
  })
  server.on("GET", "/worlds/world-b", {
    body: {
      world_id: "world-b",
      name: "World B",
      capabilities: OWNER,
      timelines: [timeline("timeline-c", "Main B")],
    },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("HierarchyContextPanel placement and levels", () => {
  it("renders the four hierarchy levels in order on every world and campaign page", async () => {
    for (const path of [
      "/worlds",
      "/worlds/world-a",
      "/worlds/world-a/timelines",
      "/worlds/world-a/timelines/timeline-a",
      "/app/c1/home",
    ]) {
      const { unmount } = renderAt(path)
      expect(
        screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent),
        path,
      ).toEqual(["World", "Timeline", "Campaign", "Character"])
      expect(screen.getAllByRole("main"), path).toHaveLength(1)
      expect(screen.getAllByRole("heading", { level: 1 }), path).toHaveLength(1)
      await waitFor(() => expect(level("World")).toBeEnabled())
      unmount()
    }
  })

  it("All Worlds selects nothing and disables the lower levels", async () => {
    renderAt("/worlds")

    await waitFor(() => expect(level("World")).toBeEnabled())
    expect(shown(level("World"))).toBe("No selection")
    expect(optionNames(level("World"))).toEqual(["No selection", "World A", "World B"])
    for (const name of ["Timeline", "Campaign"] as const) {
      expect(level(name)).toBeDisabled()
      expect(shown(level(name))).toBe("No selection")
    }
    expect(character()).toBeDisabled()
  })

  it("World Overview selects the world, offers its timelines, and disables the rest", async () => {
    renderAt("/worlds/world-a")

    await waitFor(() => expect(level("Timeline")).toBeEnabled())
    expect(shown(level("World"))).toBe("World A")
    expect(shown(level("Timeline"))).toBe("No selection")
    expect(optionNames(level("Timeline"))).toEqual(["No selection", "Main A", "Branch A"])
    expect(level("Campaign")).toBeDisabled()
    expect(character()).toBeDisabled()
  })

  it("the Timelines collection selects the world and no timeline", async () => {
    renderAt("/worlds/world-a/timelines")

    await waitFor(() => expect(level("Timeline")).toBeEnabled())
    expect(shown(level("World"))).toBe("World A")
    expect(shown(level("Timeline"))).toBe("No selection")
    expect(level("Campaign")).toBeDisabled()
    expect(character()).toBeDisabled()
  })

  it("Timeline Overview selects world and timeline and offers only that timeline's authorized campaigns", async () => {
    renderAt("/worlds/world-a/timelines/timeline-a")

    await waitFor(() => expect(level("Campaign")).toBeEnabled())
    expect(shown(level("World"))).toBe("World A")
    expect(shown(level("Timeline"))).toBe("Main A")
    expect(shown(level("Campaign"))).toBe("No selection")
    expect(optionNames(level("Campaign"))).toEqual(["No selection", "Campaign c1"])
    expect(character()).toBeDisabled()
  })

  it("a campaign page selects all three levels and offers only that campaign's perspectives", async () => {
    renderAt("/app/c1/home")

    await waitFor(() => expect(level("Timeline")).toBeEnabled())
    expect(shown(level("World"))).toBe("World A")
    expect(shown(level("Timeline"))).toBe("Main A")
    expect(shown(level("Campaign"))).toBe("Campaign c1")
    expect(character()).toBeEnabled()
    expect(optionNames(character())).toEqual([
      "No character perspective selected",
      "Hero of c1",
      "Ally of c1",
    ])
    expect(screen.queryByText(/Hero of c3/)).toBeNull()
  })

  it("keeps character perspective Campaign-scoped: reports changes for the route campaign only", () => {
    renderAt("/app/c1/home", "c1-hero")

    expect(character()).toHaveValue("c1-hero")
    fireEvent.change(character(), { target: { value: "c1-ally" } })
    expect(selectCharacter).toHaveBeenCalledWith("c1", "c1-ally")
  })

  it("shows character detail only when a perspective is selected", () => {
    const { unmount } = renderAt("/app/c1/home")
    expect(useCharacterMock).not.toHaveBeenCalled()
    unmount()

    renderAt("/app/c1/home", "c1-hero")
    expect(useCharacterMock).toHaveBeenCalledWith("c1", "c1-hero")
  })
})

describe("HierarchyContextPanel party memberships", () => {
  it("shows a collapsed Parties (N) disclosure under the selector only for a selected character", async () => {
    server.on("GET", "/campaigns/c1/characters/c1-hero/parties", {
      body: {
        character_id: "c1-hero",
        can_open: false,
        items: [
          { party_id: "p1", name: "The Company" },
          { party_id: "p2", name: "The Watch" },
        ],
      },
    })
    const { unmount } = renderAt("/app/c1/home")
    expect(screen.queryByText(/Parties \(/)).toBeNull()
    expect(screen.queryByText("Loading parties…")).toBeNull()
    expect(server.callsTo("GET", /\/parties$/)).toHaveLength(0)
    unmount()

    renderAt("/app/c1/home", "c1-hero")
    const summary = await screen.findByText("Parties (2)")
    expect(summary.closest("details")).not.toHaveAttribute("open")
    // Directly beneath the character selector.
    expect(
      character().compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    // The rest of the Character area is still there.
    expect(useCharacterMock).toHaveBeenCalledWith("c1", "c1-hero")
    // Expanding changes no selection and asks for nothing else.
    fireEvent.click(summary)
    expect(selectCharacter).not.toHaveBeenCalled()
    expect(server.callsTo("GET", /\/parties$/)).toHaveLength(1)
  })
})

describe("HierarchyContextPanel cascade", () => {
  it("choosing a world navigates to its overview and removes the campaign and character", async () => {
    renderAt("/app/c1/home", "c1-hero")
    await waitFor(() => expect(level("World")).toBeEnabled())
    useCharacterMock.mockClear()

    fireEvent.change(level("World"), { target: { value: "world-b" } })

    expect(screen.getByTestId("location")).toHaveTextContent("/worlds/world-b")
    expect(screen.queryByRole("heading", { name: "Campaign home" })).toBeNull()
    expect(shown(level("Campaign"))).toBe("No selection")
    expect(level("Campaign")).toBeDisabled()
    expect(character()).toBeDisabled()
    expect(screen.queryByText(/Hero of c1/)).toBeNull()
    expect(useCharacterMock).not.toHaveBeenCalledWith("c1", expect.anything())
  })

  it("never shows the previous world's timelines while the next world loads", async () => {
    let release: (() => void) | undefined
    server.on("GET", "/worlds/world-b", async () => {
      await new Promise<void>((resolve) => {
        release = resolve
      })
      return {
        body: {
          world_id: "world-b",
          name: "World B",
          capabilities: OWNER,
          timelines: [timeline("timeline-c", "Main B")],
        },
      }
    })
    renderAt("/worlds/world-a")
    await waitFor(() => expect(level("Timeline")).toBeEnabled())

    fireEvent.change(level("World"), { target: { value: "world-b" } })

    // Pending: the new world is not yet confirmed, so nothing is selected,
    // no stale options remain, and nothing below is enabled.
    expect(shown(level("World"))).toBe("No selection")
    expect(level("Timeline")).toBeDisabled()
    expect(screen.queryByText("Main A")).toBeNull()
    expect(screen.queryByText("Branch A")).toBeNull()

    release?.()
    await waitFor(() => expect(level("Timeline")).toBeEnabled())
    expect(shown(level("World"))).toBe("World B")
    expect(optionNames(level("Timeline"))).toEqual(["No selection", "Main B"])
  })

  it("choosing a timeline navigates to its overview and clears the campaign", async () => {
    renderAt("/app/c1/home")
    await waitFor(() => expect(level("Timeline")).toBeEnabled())

    fireEvent.change(level("Timeline"), { target: { value: "timeline-b" } })

    expect(screen.getByTestId("location")).toHaveTextContent(
      "/worlds/world-a/timelines/timeline-b",
    )
    expect(shown(level("Campaign"))).toBe("No selection")
    expect(character()).toBeDisabled()
  })

  it("choosing a campaign opens its home and clears the previous campaign's perspective", async () => {
    renderAt("/worlds/world-a/timelines/timeline-b")
    await waitFor(() => expect(level("Campaign")).toBeEnabled())

    fireEvent.change(level("Campaign"), { target: { value: "c2" } })

    expect(selectCharacter).toHaveBeenCalledWith("c2", null)
    expect(screen.getByTestId("location")).toHaveTextContent("/app/c2/home")
  })

  it("ignores re-choosing the placeholder", async () => {
    renderAt("/worlds/world-a")
    await waitFor(() => expect(level("Timeline")).toBeEnabled())

    fireEvent.change(level("Timeline"), { target: { value: "" } })

    expect(screen.getByTestId("location")).toHaveTextContent("/worlds/world-a")
  })
})

describe("HierarchyContextPanel disclosure", () => {
  it("shows no world, timeline, or id for a world the server does not authorize", async () => {
    renderAt("/worlds/ghost-world/timelines/ghost-timeline")

    await waitFor(() => expect(level("World")).toBeEnabled())
    expect(shown(level("World"))).toBe("No selection")
    expect(level("Timeline")).toBeDisabled()
    expect(level("Campaign")).toBeDisabled()
    expect(screen.getByRole("main").innerHTML).not.toContain("ghost")
    // Only the authorized worlds are offered.
    expect(optionNames(level("World"))).toEqual(["No selection", "World A", "World B"])
  })

  it("offers only worlds returned with world access, and no timeline choice for a view-only world", async () => {
    server.on("GET", /^\/worlds\?status=all/, {
      body: {
        items: [
          { world_id: "world-a", name: "World A", capabilities: ["world.view"] },
          { world_id: "world-b", name: "World B", capabilities: OWNER },
          { world_id: "world-z", name: "World Z", capabilities: [] },
        ],
        next_cursor: null,
      },
    })
    server.on("GET", "/worlds/world-a", {
      body: {
        world_id: "world-a",
        name: "World A",
        capabilities: ["world.view"],
        timelines: [timeline("timeline-a", "Main A")],
      },
    })
    renderAt("/worlds/world-a")

    await waitFor(() => expect(shown(level("World"))).toBe("World A"))
    expect(optionNames(level("World"))).toEqual(["No selection", "World A", "World B"])
    // Choosing a timeline would open a timeline-authoring route.
    expect(level("Timeline")).toBeDisabled()
  })

  it("treats a timeline from another world as no selection", async () => {
    renderAt("/worlds/world-a/timelines/timeline-c")

    await waitFor(() => expect(level("Timeline")).toBeEnabled())
    expect(shown(level("World"))).toBe("World A")
    expect(shown(level("Timeline"))).toBe("No selection")
    expect(screen.queryByText("Main B")).toBeNull()
    expect(level("Campaign")).toBeDisabled()
  })

  it("never invents timeline options when the world read is denied, on a campaign page", async () => {
    server.on("GET", "/worlds/world-a", { status: 403, body: { detail: "no" } })
    renderAt("/app/c1/home")

    await waitFor(() => expect(server.callsTo("GET", "/worlds/world-a")).not.toHaveLength(0))
    // The campaign's own authorized timeline stays shown, but cannot be changed.
    expect(shown(level("Timeline"))).toBe("Main A")
    await waitFor(() => expect(level("Timeline")).toBeDisabled())
    expect(screen.queryByText("Branch A")).toBeNull()
  })

  it("renders no raw identifiers", async () => {
    renderAt("/app/c1/home", "c1-hero")
    await waitFor(() => expect(level("Timeline")).toBeEnabled())

    for (const text of ["timeline-a", "world-a"]) {
      expect(screen.queryByText(text)).toBeNull()
    }
  })

  it("keeps the disclosure summary open and describes the campaign context", async () => {
    renderAt("/app/c1/home", "c1-hero")

    const summary = screen.getByText(
      "Campaign context: World A › Main A › Campaign c1 — Viewing as Hero of c1",
      { selector: "summary" },
    )
    expect(summary.closest("details")).toHaveAttribute("open")
  })
})

describe("HierarchyContextPanel world choices across authority sources", () => {
  // The observed account: explicit world_owner of "test 1", and a player in a
  // campaign on a different world it holds no world role on.
  const player: SessionBootstrap = {
    ...sessionBootstrapFixture,
    global_capabilities: [],
    campaigns: [
      {
        ...campaignFor("c-play", "world-hosted", "Hosted World", "timeline-h", "Main H"),
        roles: ["player"],
        capabilities: ["campaign.view"],
      },
    ],
  }

  beforeEach(() => {
    server.on("GET", /^\/worlds\?status=all/, {
      body: {
        items: [{ world_id: "world-owned", name: "test 1", capabilities: OWNER }],
        next_cursor: null,
      },
    })
    server.on("GET", "/worlds/world-hosted", { status: 404, body: {} })
    server.on("GET", "/worlds/world-owned", {
      body: {
        world_id: "world-owned",
        name: "test 1",
        capabilities: OWNER,
        timelines: [timeline("timeline-o", "Main O")],
      },
    })
  })

  it("offers the same deduplicated worlds on All Worlds and on campaign routes", async () => {
    const all = renderAt("/worlds", null, player)
    await waitFor(() => expect(level("World")).toBeEnabled())
    const onAllWorlds = optionNames(level("World"))
    all.unmount()

    renderAt("/app/c-play/home", null, player)
    await waitFor(() => expect(shown(level("World"))).toBe("Hosted World"))
    await waitFor(() => expect(optionNames(level("World"))).toEqual(onAllWorlds))
    expect(onAllWorlds).toEqual(["No selection", "Hosted World", "test 1"])
  })

  it("opens a campaign-visible world through its campaign, never a /worlds route", async () => {
    renderAt("/worlds", null, player)
    await waitFor(() => expect(level("World")).toBeEnabled())

    fireEvent.change(level("World"), { target: { value: "world-hosted" } })

    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/app/c-play/world"))
    expect(screen.getByTestId("location")).not.toHaveTextContent("/worlds/")
  })

  it("opens an explicitly owned world on its own overview", async () => {
    renderAt("/app/c-play/home", null, player)
    await waitFor(() => expect(optionNames(level("World"))).toContain("test 1"))

    fireEvent.change(level("World"), { target: { value: "world-owned" } })

    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/worlds/world-owned"))
  })

  it("never offers timeline authoring for a campaign-visible world", async () => {
    renderAt("/app/c-play/home", null, player)
    await waitFor(() => expect(server.callsTo("GET", "/worlds/world-hosted")).not.toHaveLength(0))
    expect(shown(level("Timeline"))).toBe("Main H")
    expect(level("Timeline")).toBeDisabled()
  })
})

