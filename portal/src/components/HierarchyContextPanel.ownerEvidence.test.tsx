import { render, screen, waitFor, within } from "@testing-library/react"
import type { ReactElement } from "react"
import { MemoryRouter, Outlet, Route, Routes } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { CharacterPerspectiveContext } from "../context/CharacterPerspectiveContext"
import { SessionContext } from "../context/SessionContext"
import { WorkspaceHierarchyProvider } from "../context/WorkspaceHierarchyProvider"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { WorldWorkspaceLayout } from "../layouts/WorldWorkspaceLayout"
import { installMockServer } from "../test/authoringHarness"
import type { MockServer } from "../test/authoringHarness"
import type { SessionBootstrap } from "../types/bootstrap"

// World evidence belongs to the owner (user + browser session) under which the read STARTED
// (docs/UI_DESIGN.md §4.8.12). A result that settled under a previous owner is never recorded for the next
// one, and the next owner's read of the same world path produces its own evidence.

const { useCharacterMock } = vi.hoisted(() => ({ useCharacterMock: vi.fn() }))
vi.mock("../hooks/useCharacter", () => ({ useCharacter: useCharacterMock }))
vi.mock("../api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const ownerA: SessionBootstrap = { ...sessionBootstrapFixture, campaigns: [] }
const otherUser: SessionBootstrap = {
  ...ownerA,
  user: { ...ownerA.user, user_id: "someone-else" },
}
const otherBrowserSession: SessionBootstrap = { ...ownerA, browser_session_id: "another-browser-session" }

const OWNER = ["campaign.create", "timeline.manage", "world.manage", "world.view"]
const worldBody = {
  body: {
    world_id: "world-a",
    name: "World A",
    capabilities: OWNER,
    timelines: [
      {
        timeline_id: "timeline-a",
        name: "Main A",
        description: null,
        is_primary: false,
        parent_timeline_id: null,
        branch_point: null,
        lifecycle_status: "active",
        row_version: 1,
      },
    ],
  },
}
const refusal = { status: 404, body: {} }

let server: MockServer
// Stable, as in the real provider: a new reload function would itself restart every read.
const reload = vi.fn()
const refresh = vi.fn()
const perspective = { getSelectedCharacterId: () => null, selectCharacter: vi.fn() }

function tree(session: SessionBootstrap): ReactElement {
  return (
    <SessionContext.Provider
      value={{ state: { status: "authenticated", bootstrap: session }, reload, refresh }}
    >
      <CharacterPerspectiveContext.Provider
        value={perspective}
      >
        <MemoryRouter initialEntries={["/worlds/world-a"]}>
          <WorkspaceHierarchyProvider>
            <Routes>
              <Route element={<Outlet context={{ bootstrap: session, reload }} />}>
                <Route element={<WorldWorkspaceLayout />}>
                  <Route path="/worlds/:worldId" element={<h1>World page</h1>} />
                </Route>
              </Route>
            </Routes>
          </WorkspaceHierarchyProvider>
        </MemoryRouter>
      </CharacterPerspectiveContext.Provider>
    </SessionContext.Provider>
  )
}

const worldSelect = () => screen.getByRole("combobox", { name: "World" })
const worldOptions = () =>
  within(worldSelect())
    .getAllByRole("option")
    .map((option) => option.textContent ?? "")
const WITH = ["No selection", "World A"]
const WITHOUT = ["No selection"]

function gate<T>(): { promise: Promise<T>; release: (value: T) => void } {
  let release!: (value: T) => void
  const promise = new Promise<T>((resolve) => {
    release = resolve
  })
  return { promise, release }
}

beforeEach(() => {
  useCharacterMock.mockReset()
  useCharacterMock.mockReturnValue({ state: { status: "unavailable" }, retry: vi.fn(), authority: null })
  server = installMockServer()
  server.on("GET", /^\/worlds\?status=all/, {
    body: { items: [{ world_id: "world-a", name: "World A", capabilities: OWNER }], next_cursor: null },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const changes: [string, SessionBootstrap][] = [
  ["a different user", otherUser],
  ["a different browser session of the same user", otherBrowserSession],
]

describe.each(changes)("World evidence when the owner changes to %s on the same world path", (_name, next) => {
  it("does not let the old owner's refusal suppress the new owner's World option, and restores it on success", async () => {
    let reads = 0
    server.on("GET", "/worlds/world-a", () => (++reads === 1 ? refusal : worldBody))
    const view = render(tree(ownerA))
    await waitFor(() => expect(worldOptions()).toEqual(WITHOUT))

    view.rerender(tree(next))

    // The new owner's own read succeeds: the option is back, though the old refusal was still on screen.
    await waitFor(() => expect(worldOptions()).toEqual(WITH))
    expect(server.callsTo("GET", "/worlds/world-a")).toHaveLength(2)
  })

  it("does not carry the old refusal over while the new owner's read is still in flight", async () => {
    const second = gate<typeof worldBody>()
    let reads = 0
    server.on("GET", "/worlds/world-a", () => (++reads === 1 ? refusal : second.promise))
    const view = render(tree(ownerA))
    await waitFor(() => expect(worldOptions()).toEqual(WITHOUT))

    view.rerender(tree(next))
    await waitFor(() => expect(server.callsTo("GET", "/worlds/world-a")).toHaveLength(2))
    // Nothing is known about the new owner yet: the option is not withdrawn on the old owner's word.
    expect(worldOptions()).toEqual(WITH)

    second.release(worldBody)
    await waitFor(() => expect(worldOptions()).toEqual(WITH))
  })

  it("does not let the old owner's success stand in for the new owner's refusal, and a new refusal still withdraws", async () => {
    let reads = 0
    server.on("GET", "/worlds/world-a", () => (++reads === 1 ? worldBody : refusal))
    const view = render(tree(ownerA))
    await waitFor(() => expect(server.callsTo("GET", "/worlds/world-a")).toHaveLength(1))
    await waitFor(() => expect(worldOptions()).toEqual(WITH))

    view.rerender(tree(next))

    await waitFor(() => expect(worldOptions()).toEqual(WITHOUT))
  })

  it("ignores an old owner's request that completes after the owner changed", async () => {
    const old = gate<{ status: number; body: unknown }>()
    let reads = 0
    server.on("GET", "/worlds/world-a", () => (++reads === 1 ? old.promise : worldBody))
    const view = render(tree(ownerA))
    await waitFor(() => expect(server.callsTo("GET", "/worlds/world-a")).toHaveLength(1))

    view.rerender(tree(next))
    await waitFor(() => expect(server.callsTo("GET", "/worlds/world-a")).toHaveLength(2))
    await waitFor(() => expect(worldOptions()).toEqual(WITH))

    // The old owner's refusal answers last, after the new owner's success: it records nothing.
    old.release(refusal)
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(worldOptions()).toEqual(WITH)
  })

  it("ignores an old owner's success that completes after the new owner's refusal", async () => {
    const old = gate<typeof worldBody>()
    let reads = 0
    server.on("GET", "/worlds/world-a", () => (++reads === 1 ? old.promise : refusal))
    const view = render(tree(ownerA))
    await waitFor(() => expect(server.callsTo("GET", "/worlds/world-a")).toHaveLength(1))

    view.rerender(tree(next))
    await waitFor(() => expect(worldOptions()).toEqual(WITHOUT))

    old.release(worldBody)
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(worldOptions()).toEqual(WITHOUT)
  })
})
