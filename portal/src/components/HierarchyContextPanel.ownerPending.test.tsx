import { act, render, screen, waitFor, within } from "@testing-library/react"
import type { ReactElement } from "react"
import { MemoryRouter, Outlet, Route, Routes, useLocation } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { CharacterPerspectiveContext } from "../context/CharacterPerspectiveContext"
import { SessionContext } from "../context/SessionContext"
import { WorkspaceHierarchyProvider } from "../context/WorkspaceHierarchyProvider"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { CampaignLayout } from "../layouts/CampaignLayout"
import { WorldWorkspaceLayout } from "../layouts/WorldWorkspaceLayout"
import type { SessionBootstrapState as SessionState } from "../hooks/useSessionBootstrap"
import { installMockServer } from "../test/authoringHarness"
import type { MockResponse, MockServer } from "../test/authoringHarness"
import type { CampaignContext, SessionBootstrap } from "../types/bootstrap"

// While a NEW owner's reads are pending, nothing the previous owner's reads said may supply displayed
// world or timeline details, permission decisions, selector options or actionable destinations
// (docs/UI_DESIGN.md §4.8.12). The panel is observed in the pending interval itself, with deferred
// responses, then as the new reads settle in either order.

const { useCharacterMock } = vi.hoisted(() => ({ useCharacterMock: vi.fn() }))
vi.mock("../hooks/useCharacter", () => ({ useCharacter: useCharacterMock }))
vi.mock("../api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const OWNER_CAPS = ["campaign.create", "timeline.manage", "world.manage", "world.view"]
const base = sessionBootstrapFixture.campaigns[0]!

const campaign: CampaignContext = {
  ...base,
  campaign_id: "c-new",
  campaign_name: "Campaign New",
  world_id: "world-new",
  world_name: "Bootstrap World New",
  timeline_id: "timeline-new",
  timeline_name: "Bootstrap Timeline New",
  character_perspectives: [],
  selected_character_id: null,
}

const ownerA: SessionBootstrap = { ...sessionBootstrapFixture, campaigns: [] }
const otherUser: SessionBootstrap = { ...ownerA, user: { ...ownerA.user, user_id: "someone-else" } }
const otherBrowserSession: SessionBootstrap = { ...ownerA, browser_session_id: "another-browser-session" }
// What the new owner's session leads to, as the current bootstrap says it.
const withCampaign = (session: SessionBootstrap): SessionBootstrap => ({ ...session, campaigns: [campaign] })

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
const worldBody = (id: string, name: string, timelineId: string, timelineName: string): MockResponse => ({
  body: { world_id: id, name, capabilities: OWNER_CAPS, timelines: [timeline(timelineId, timelineName)] },
})
const listBody = (id: string, name: string): MockResponse => ({
  body: { items: [{ world_id: id, name, capabilities: OWNER_CAPS }], next_cursor: null },
})
const refusal: MockResponse = { status: 404, body: {} }
const failedList: MockResponse = { status: 500, body: {} }

const OLD_WORLD = "Old Owner World Label"
const OLD_TIMELINE = "Old Owner Timeline Label"
const NEW_WORLD = "New Owner World Label"
const NEW_TIMELINE = "New Owner Timeline Label"

function gate<T>(): { promise: Promise<T>; release: (value: T) => void } {
  let release!: (value: T) => void
  const promise = new Promise<T>((resolve) => {
    release = resolve
  })
  return { promise, release }
}

// Reads are answered in order by the owner that asks: the first answer for the old owner, the second for the
// new one, each possibly held back by a gate.
function sequence(first: MockResponse | Promise<MockResponse>, second: MockResponse | Promise<MockResponse>) {
  let calls = 0
  return () => (++calls === 1 ? first : second)
}

let server: MockServer
const reload = vi.fn()
const refresh = vi.fn()
const perspective = { getSelectedCharacterId: () => null, selectCharacter: vi.fn() }

function Where() {
  return <p data-testid="location">{useLocation().pathname}</p>
}

function tree(state: SessionState, path: string): ReactElement {
  const bootstrap = state.status === "authenticated" ? state.bootstrap : ownerA
  return (
    <SessionContext.Provider value={{ state, reload, refresh }}>
      <CharacterPerspectiveContext.Provider value={perspective}>
        <MemoryRouter initialEntries={[path]}>
          <WorkspaceHierarchyProvider>
            <Routes>
              <Route element={<Outlet context={{ bootstrap, reload }} />}>
                <Route element={<WorldWorkspaceLayout />}>
                  <Route path="/worlds/:worldId" element={<h1>World page</h1>} />
                  <Route path="/worlds/:worldId/timelines" element={<h1>Timelines page</h1>} />
                  <Route path="/worlds/:worldId/timelines/:timelineId" element={<h1>Timeline page</h1>} />
                </Route>
              </Route>
              <Route path="/app/:campaignId" element={<CampaignLayout bootstrap={bootstrap} />}>
                <Route path="home" element={<h1>Campaign home</h1>} />
              </Route>
            </Routes>
            <Where />
          </WorkspaceHierarchyProvider>
        </MemoryRouter>
      </CharacterPerspectiveContext.Provider>
    </SessionContext.Provider>
  )
}
const signedIn = (bootstrap: SessionBootstrap): SessionState => ({ status: "authenticated", bootstrap })

const level = (name: "World" | "Timeline" | "Campaign") => screen.getByRole("combobox", { name })
const optionNames = (select: HTMLElement) =>
  within(select)
    .queryAllByRole("option")
    .map((option) => option.textContent ?? "")
const page = () => document.body.textContent ?? ""
const hrefs = () => [...document.querySelectorAll("a[href]")].map((a) => a.getAttribute("href") ?? "")
const optionValues = () =>
  [...document.querySelectorAll("select option")].map((option) => (option as HTMLOptionElement).value)
const calls = (match: string | RegExp) => server.callsTo("GET", match).length

const ROUTE = "/worlds/world-old/timelines/timeline-old"

beforeEach(() => {
  useCharacterMock.mockReset()
  useCharacterMock.mockReturnValue({ state: { status: "unavailable" }, retry: vi.fn(), authority: null })
  server = installMockServer()
})
afterEach(() => {
  vi.unstubAllGlobals()
})

const changes: [string, SessionBootstrap][] = [
  ["a different user", otherUser],
  ["a different browser session of the same user", otherBrowserSession],
]

async function settleOldOwner(listHandler: () => MockResponse | Promise<MockResponse>, detail: () => MockResponse | Promise<MockResponse>) {
  server.on("GET", /^\/worlds\?status=all/, listHandler)
  server.on("GET", "/worlds/world-old", detail)
  const view = render(tree(signedIn(ownerA), ROUTE))
  await waitFor(() => expect(optionNames(level("World"))).toContain(OLD_WORLD))
  await waitFor(() => expect(level("Timeline")).toBeDisabled())
  expect(page()).toContain(OLD_TIMELINE)
  expect(optionValues()).toEqual(expect.arrayContaining(["world-old", "timeline-old"]))
  return view
}

function expectNoOldOwnerData(ids = true) {
  expect(page()).not.toContain(OLD_WORLD)
  expect(page()).not.toContain(OLD_TIMELINE)
  if (ids) {
    expect(optionValues()).not.toContain("timeline-old")
    expect(optionValues()).not.toContain("world-old")
  }
  // Neither the old world nor its timeline is an actionable destination.
  expect(hrefs().filter((href) => href.startsWith("/worlds/world-old"))).toEqual([])
}

describe.each(changes)("pending reads after the owner changes to %s", (_name, next) => {
  it("stops showing, offering and routing by the old owner's reads at once, and does not let them return", async () => {
    const detailGate = gate<MockResponse>()
    const listGate = gate<MockResponse>()
    const view = await settleOldOwner(
      sequence(listBody("world-old", OLD_WORLD), listGate.promise),
      sequence(worldBody("world-old", OLD_WORLD, "timeline-old", OLD_TIMELINE), detailGate.promise),
    )

    view.rerender(tree(signedIn(next), ROUTE))

    // The same commit: nothing waited for an effect or an answer.
    expectNoOldOwnerData()
    expect(level("World")).toBeDisabled()
    expect(level("Timeline")).toBeDisabled()
    expect(optionNames(level("Timeline"))).toEqual(["No selection"])

    await waitFor(() => expect(calls("/worlds/world-old")).toBe(2))
    await waitFor(() => expect(calls(/^\/worlds\?status=all/)).toBe(2))
    expectNoOldOwnerData()

    // The new owner's answers, in the order list then detail, each a success under new labels.
    await act(async () => listGate.release(listBody("world-old", NEW_WORLD)))
    await waitFor(() => expect(optionNames(level("World"))).toContain(NEW_WORLD))
    expect(page()).not.toContain(OLD_WORLD)
    expect(level("Timeline")).toBeDisabled()
    await act(async () => detailGate.release(worldBody("world-old", NEW_WORLD, "timeline-old", NEW_TIMELINE)))
    await waitFor(() => expect(page()).toContain(NEW_TIMELINE))
    expect(page()).not.toContain(OLD_TIMELINE)
    expect(page()).not.toContain(OLD_WORLD)
  })

  it("settles a new owner's refusal, with the detail answering before the list", async () => {
    const detailGate = gate<MockResponse>()
    const listGate = gate<MockResponse>()
    const view = await settleOldOwner(
      sequence(listBody("world-old", OLD_WORLD), listGate.promise),
      sequence(worldBody("world-old", OLD_WORLD, "timeline-old", OLD_TIMELINE), detailGate.promise),
    )
    view.rerender(tree(signedIn(next), ROUTE))
    await waitFor(() => expect(calls("/worlds/world-old")).toBe(2))
    await waitFor(() => expect(calls(/^\/worlds\?status=all/)).toBe(2))

    await act(async () => detailGate.release(refusal))
    await waitFor(() => expect(level("Timeline")).toBeDisabled())
    expectNoOldOwnerData()
    await act(async () => listGate.release(listBody("world-old", NEW_WORLD)))
    await waitFor(() => expect(page()).not.toContain("Loading worlds"))
    // The new owner was refused the world: its option is withdrawn and nothing old comes back.
    expect(optionNames(level("World"))).not.toContain(NEW_WORLD)
    expectNoOldOwnerData()
  })

  it("settles a new owner's failed list while the detail succeeds", async () => {
    const detailGate = gate<MockResponse>()
    const listGate = gate<MockResponse>()
    const view = await settleOldOwner(
      sequence(listBody("world-old", OLD_WORLD), listGate.promise),
      sequence(worldBody("world-old", OLD_WORLD, "timeline-old", OLD_TIMELINE), detailGate.promise),
    )
    view.rerender(tree(signedIn(next), ROUTE))
    await waitFor(() => expect(calls("/worlds/world-old")).toBe(2))
    await waitFor(() => expect(calls(/^\/worlds\?status=all/)).toBe(2))

    await act(async () => listGate.release(failedList))
    await act(async () => detailGate.release(worldBody("world-old", NEW_WORLD, "timeline-old", NEW_TIMELINE)))
    await waitFor(() => expect(page()).toContain(NEW_TIMELINE))
    expect(page()).not.toContain(OLD_WORLD)
    expect(page()).not.toContain(OLD_TIMELINE)
  })

  it("keeps the current bootstrap's campaign destinations while the new owner's reads are pending", async () => {
    const detailGate = gate<MockResponse>()
    const listGate = gate<MockResponse>()
    server.on("GET", /^\/worlds\?status=all/, sequence(listBody("world-new", OLD_WORLD), listGate.promise))
    server.on("GET", "/worlds/world-new", sequence(worldBody("world-new", OLD_WORLD, "timeline-new", OLD_TIMELINE), detailGate.promise))
    const view = render(tree(signedIn(withCampaign(ownerA)), "/app/c-new/home"))
    await waitFor(() => expect(page()).toContain(OLD_TIMELINE))

    view.rerender(tree(signedIn(withCampaign(next)), "/app/c-new/home"))

    expect(page()).not.toContain(OLD_WORLD)
    expect(page()).not.toContain(OLD_TIMELINE)
    expect(hrefs().filter((href) => href.startsWith("/worlds/world-new"))).toEqual([])
    // What the CURRENT bootstrap says is still shown and usable.
    expect(level("Campaign")).toHaveDisplayValue("Campaign New")
    expect(screen.getByTestId("location")).toHaveTextContent("/app/c-new/home")

    await waitFor(() => expect(calls("/worlds/world-new")).toBe(2))
    await act(async () => detailGate.release(refusal))
    await act(async () => listGate.release(listBody("world-new", NEW_WORLD)))
    await waitFor(() => expect(optionNames(level("Timeline"))).toContain("Bootstrap Timeline New"))
    expect(page()).not.toContain(OLD_TIMELINE)
  })

  it("ignores old-owner answers that arrive after the owner changed", async () => {
    const oldDetail = gate<MockResponse>()
    const oldList = gate<MockResponse>()
    server.on("GET", /^\/worlds\?status=all/, sequence(oldList.promise, listBody("world-old", NEW_WORLD)))
    server.on("GET", "/worlds/world-old", sequence(oldDetail.promise, worldBody("world-old", NEW_WORLD, "timeline-old", NEW_TIMELINE)))
    const view = render(tree(signedIn(ownerA), ROUTE))
    await waitFor(() => expect(calls("/worlds/world-old")).toBe(1))
    await waitFor(() => expect(calls(/^\/worlds\?status=all/)).toBe(1))

    view.rerender(tree(signedIn(next), ROUTE))
    await waitFor(() => expect(calls("/worlds/world-old")).toBe(2))
    await waitFor(() => expect(optionNames(level("World"))).toContain(NEW_WORLD))

    // The old owner's answers arrive last and carry the distinctive old labels.
    await act(async () => oldList.release(listBody("world-old", OLD_WORLD)))
    await act(async () => oldDetail.release(worldBody("world-old", OLD_WORLD, "timeline-old", OLD_TIMELINE)))
    await new Promise((resolve) => setTimeout(resolve, 30))
    // The new owner's own answers reuse the ids; only the old owner's labels must not come back.
    expectNoOldOwnerData(false)
    expect(optionNames(level("World"))).toContain(NEW_WORLD)
    expect(page()).toContain(NEW_TIMELINE)
  })
})

describe("sign-out and sign-in", () => {
  it("hides the previous owner's data while signed out and while the next sign-in's reads are pending", async () => {
    const detailGate = gate<MockResponse>()
    const listGate = gate<MockResponse>()
    const view = await settleOldOwner(
      sequence(listBody("world-old", OLD_WORLD), listGate.promise),
      sequence(worldBody("world-old", OLD_WORLD, "timeline-old", OLD_TIMELINE), detailGate.promise),
    )

    view.rerender(tree({ status: "unauthenticated" }, ROUTE))
    expect(page()).not.toContain(OLD_WORLD)
    expect(page()).not.toContain(OLD_TIMELINE)

    view.rerender(tree(signedIn(otherUser), ROUTE))
    expectNoOldOwnerData()
    await waitFor(() => expect(calls("/worlds/world-old")).toBe(2))
    expectNoOldOwnerData()

    await act(async () => listGate.release(listBody("world-old", NEW_WORLD)))
    await act(async () => detailGate.release(worldBody("world-old", NEW_WORLD, "timeline-old", NEW_TIMELINE)))
    await waitFor(() => expect(page()).toContain(NEW_TIMELINE))
    expect(page()).not.toContain(OLD_TIMELINE)
  })

  it("does not bring an earlier owner's data back when the same owner signs in again", async () => {
    const detailGate = gate<MockResponse>()
    const listGate = gate<MockResponse>()
    const view = await settleOldOwner(
      sequence(listBody("world-old", OLD_WORLD), listGate.promise),
      sequence(worldBody("world-old", OLD_WORLD, "timeline-old", OLD_TIMELINE), detailGate.promise),
    )
    view.rerender(tree(signedIn(otherUser), ROUTE))
    view.rerender(tree(signedIn(ownerA), ROUTE))
    // Back under the first owner, but with that owner's reads pending again, not the earlier result.
    expectNoOldOwnerData()
  })
})

describe("the same owner", () => {
  it("keeps its data on screen, and starts no new read, when only the bootstrap object changes", async () => {
    server.on("GET", /^\/worlds\?status=all/, listBody("world-old", OLD_WORLD))
    server.on("GET", "/worlds/world-old", worldBody("world-old", OLD_WORLD, "timeline-old", OLD_TIMELINE))
    const view = render(tree(signedIn(ownerA), ROUTE))
    await waitFor(() => expect(optionNames(level("World"))).toContain(OLD_WORLD))
    await waitFor(() => expect(page()).toContain(OLD_TIMELINE))

    // The same owner, a new bootstrap object (a session refresh): not an owner change.
    view.rerender(tree(signedIn({ ...ownerA }), ROUTE))
    expect(page()).toContain(OLD_TIMELINE)
    expect(optionNames(level("World"))).toContain(OLD_WORLD)
    expect(calls("/worlds/world-old")).toBe(1)
  })
})
