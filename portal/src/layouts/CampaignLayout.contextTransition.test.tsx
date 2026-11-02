import { act, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { useState } from "react"
import { Link, Route, RouterProvider, Routes, createMemoryRouter, useLocation } from "react-router"
import type { DataRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { RouteSessionProvider } from "../context/RouteSessionProvider"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import { useSession } from "../context/SessionContext"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useNavigationHold } from "../hooks/navigationHolds"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import { ThemeProvider } from "../themes/ThemeProvider"
import type { CampaignContext, SessionBootstrap } from "../types/bootstrap"
import { AuthenticatedAppLayout } from "./AuthenticatedAppLayout"
import { CampaignSessionBoundary } from "./CampaignSessionBoundary"

// P02-0a (CTX-1 / CTX-2): a perspective or campaign change is a context transition that the one
// departure guard must approve BEFORE anything is selected, cleared, refreshed or reloaded. The real
// session provider, shell, layout and guard run together; only the server is faked at fetch.

configure({ asyncUtilTimeout: 5000 })

function campaign(id: string, perspectives: string[]): CampaignContext {
  return {
    campaign_id: id,
    campaign_name: `Campaign ${id}`,
    world_id: "w1",
    world_name: "World w1",
    timeline_id: "t1",
    timeline_name: "Timeline t1",
    roles: ["campaign_owner"],
    character_perspectives: perspectives.map((p) => ({
      character_id: p,
      character_name: `Name ${p}`,
      authorized_parties: [],
    })),
    selected_character_id: null,
    capabilities: ["access.manage"],
  }
}

interface FakeServer {
  campaigns: CampaignContext[]
  requests: string[]
  // Holds the Nth (1-based) /auth/session answer until released.
  sessionGates: Map<number, Promise<void>>
  // Holds a probe read for a given `character_id` until released.
  probeGates: Map<string, Promise<void>>
}

let server: FakeServer

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
}

function deferred(): { promise: Promise<void>; release: () => void } {
  let release: () => void = () => undefined
  const promise = new Promise<void>((resolve) => {
    release = resolve
  })
  return { promise, release }
}

function sessionRequests(): number {
  return server.requests.filter((r) => r === "GET /auth/session").length
}
function probeRequests(): string[] {
  return server.requests.filter((r) => r.includes("/probe?"))
}

function installFakeServer(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString()
      server.requests.push(`${init?.method ?? "GET"} ${url}`)
      if (url === "/auth/session") {
        const nth = sessionRequests()
        await server.sessionGates.get(nth)
        const bootstrap: SessionBootstrap = {
          user: { user_id: "u1", display_name: "Gina" },
          csrf_token: "csrf",
          browser_session_id: "s1",
          system_roles: ["player"],
          global_capabilities: [],
          startup_campaign_id: null,
          campaign_preferences: {
            startup_mode: "resume_last_visited",
            preferred_campaign_id: null,
            last_visited_campaign_id: null,
          },
          campaigns: server.campaigns,
          features: { ask: false, ai_summaries: false, gm_briefs: false, cited_rules: false },
        }
        return json(bootstrap)
      }
      const probe = /\/probe\?character_id=([^&]*)/.exec(url)
      if (probe !== null) {
        const who = decodeURIComponent(probe[1]!)
        await server.probeGates.get(who)
        return json({ who })
      }
      return json({ detail: "not found" }, 404)
    }),
  )
}

let mounts = 0

// A perspective-dependent page: a form guarded like every authoring page, and one authorized read
// whose `character_id` is the perspective the page runs under.
function NotesPage() {
  const { getSelectedCharacterId, syncCharacterFromUrl } = usePerspective()
  const { refresh } = useSession()
  const campaignId = useLocation().pathname.split("/")[2]!
  const perspective = getSelectedCharacterId(campaignId) ?? ""
  const [mountId] = useState(() => ++mounts)
  const [draft, setDraft] = useState("")
  const [hold, setHold] = useState(false)
  const guard = useUnsavedChangesGuard(draft !== "")
  useNavigationHold(hold)
  const read = useAuthoringResource<{ who: string }>(`/campaigns/${campaignId}/probe?character_id=${perspective}`)
  return (
    <div>
      <h1>Notes</h1>
      <p data-testid="mount">{mountId}</p>
      <p data-testid="read">{read.state.kind === "ready" ? read.state.data.who : read.state.kind}</p>
      <textarea aria-label="Draft" value={draft} onChange={(e) => setDraft(e.target.value)} />
      <button type="button" onClick={() => setHold(true)}>
        Hold
      </button>
      <Link to="?section=2">Section two</Link>
      <button type="button" onClick={() => void refresh()}>
        Refresh session
      </button>
      <button type="button" onClick={() => syncCharacterFromUrl?.(campaignId, "char-b")}>
        Sync char-b from URL
      </button>
      <ConfirmDialog
        open={guard.blocked}
        title="Leave this page?"
        description="Your edits will be lost."
        confirmLabel="Leave"
        cancelLabel="Stay"
        onConfirm={guard.discard}
        onCancel={guard.stay}
      />
    </div>
  )
}

function HomePage() {
  const { getSelectedCharacterId } = usePerspective()
  const campaignId = useLocation().pathname.split("/")[2]!
  return <h1>Home of {campaignId} as {getSelectedCharacterId(campaignId) ?? "nobody"}</h1>
}

let router: DataRouter
function renderAt(path: string, state?: unknown) {
  router = createMemoryRouter(
    [
      {
        path: "*",
        element: (
          <RouteSessionProvider>
            <TestRoutes />
          </RouteSessionProvider>
        ),
      },
    ],
    { initialEntries: [{ pathname: path.split("?")[0]!, search: path.includes("?") ? `?${path.split("?")[1]}` : "", state }] },
  )
  return render(
    <ThemeProvider>
      <RouterProvider router={router} />
    </ThemeProvider>,
  )
}

function TestRoutes() {
  return (
    <Routes>
      <Route element={<AuthenticatedAppLayout />}>
        <Route path="/app/:campaignId" element={<CampaignSessionBoundary />}>
          <Route path="home" element={<HomePage />} />
          <Route path="notes" element={<NotesPage />} />
        </Route>
      </Route>
    </Routes>
  )
}

function perspectiveSelect() {
  return screen.getByRole("combobox", { name: "Character perspective" }) as HTMLSelectElement
}
function campaignSelect() {
  return screen.getByRole("combobox", { name: "Campaign" }) as HTMLSelectElement
}
async function settled() {
  await screen.findByRole("heading", { name: "Notes" })
  await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent(/^(?!loading)/))
}
function choosePerspective(value: string) {
  fireEvent.change(perspectiveSelect(), { target: { value } })
}
function type(text: string) {
  fireEvent.change(screen.getByLabelText("Draft"), { target: { value: text } })
}
function question() {
  return screen.queryByRole("alertdialog") ?? screen.queryByRole("dialog", { name: "Leave this page?" })
}

beforeEach(() => {
  mounts = 0
  server = {
    campaigns: [campaign("alpha", ["char-a", "char-b"]), campaign("beta", ["char-c"])],
    requests: [],
    sessionGates: new Map(),
    probeGates: new Map(),
  }
  installFakeServer()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("CTX-1: perspective change (guard before side effects)", () => {
  it("[original defect] a dirty page is not unmounted by the perspective change; the guard asks and Stay keeps everything", async () => {
    renderAt("/app/alpha/notes")
    await settled()
    type("precious draft")
    const locationBefore = router.state.location
    const sessionsBefore = sessionRequests()

    choosePerspective("char-b")

    // The question appears (HEAD: the page is replaced by "Loading portal" and nothing asks).
    expect(await screen.findByText("Leave this page?")).toBeInTheDocument()
    expect(screen.queryByText("Loading portal")).not.toBeInTheDocument()
    expect(router.state.location).toBe(locationBefore)
    expect(sessionRequests()).toBe(sessionsBefore)

    fireEvent.click(screen.getByRole("button", { name: "Stay" }))

    expect(screen.queryByText("Leave this page?")).not.toBeInTheDocument()
    expect(screen.getByLabelText("Draft")).toHaveValue("precious draft")
    expect(perspectiveSelect()).toHaveValue("")
    expect(router.state.location.pathname).toBe("/app/alpha/notes")
    expect(sessionRequests()).toBe(sessionsBefore)
    expect(screen.getByTestId("mount")).toHaveTextContent("1")
    expect(probeRequests()).toHaveLength(1)
  })

  it("Discard commits the perspective, remounts the page and re-reads under it, with one background refresh", async () => {
    renderAt("/app/alpha/notes")
    await settled()
    type("draft")
    const sessionsBefore = sessionRequests()

    choosePerspective("char-b")
    fireEvent.click(await screen.findByRole("button", { name: "Leave" }))

    await waitFor(() => expect(perspectiveSelect()).toHaveValue("char-b"))
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("char-b"))
    expect(screen.getByLabelText("Draft")).toHaveValue("")
    expect(screen.getByTestId("mount")).toHaveTextContent("2")
    expect(probeRequests().some((r) => r.endsWith("character_id=char-b"))).toBe(true)
    // Nothing was ever read under char-b with the old key, and the sidebar never went away.
    expect(probeRequests().filter((r) => r.endsWith("character_id=char-b"))).toHaveLength(1)
    expect(screen.queryByText("Loading portal")).not.toBeInTheDocument()
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument()
    await waitFor(() => expect(sessionRequests()).toBe(sessionsBefore + 1))
    expect(router.state.location.pathname).toBe("/app/alpha/notes")
  })

  it("a pristine page changes perspective at once, without the portal loading state", async () => {
    renderAt("/app/alpha/notes")
    await settled()
    const sessionsBefore = sessionRequests()
    const nav = screen.getByRole("navigation", { name: "Main" })

    choosePerspective("char-a")

    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("char-a"))
    expect(screen.queryByText("Loading portal")).not.toBeInTheDocument()
    expect(screen.getByRole("navigation", { name: "Main" })).toBe(nav)
    expect(perspectiveSelect()).toHaveValue("char-a")
    await waitFor(() => expect(sessionRequests()).toBe(sessionsBefore + 1))
  })
})

describe("CTX-2: campaign switch (guard before side effects)", () => {
  it("[original defect] a dirty page asks before the campaign changes; Stay changes nothing", async () => {
    renderAt("/app/alpha/notes")
    await settled()
    type("precious draft")
    const sessionsBefore = sessionRequests()
    const locationBefore = router.state.location

    fireEvent.change(campaignSelect(), { target: { value: "beta" } })

    expect(await screen.findByText("Leave this page?")).toBeInTheDocument()
    expect(screen.queryByText("Loading portal")).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Stay" }))

    expect(router.state.location).toBe(locationBefore)
    expect(screen.getByLabelText("Draft")).toHaveValue("precious draft")
    expect(campaignSelect()).toHaveValue("alpha")
    expect(sessionRequests()).toBe(sessionsBefore)
  })

  it("Discard lands on the new campaign's Home with no perspective carried over", async () => {
    renderAt("/app/alpha/notes")
    await settled()
    choosePerspective("char-a")
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("char-a"))
    type("draft")

    fireEvent.change(campaignSelect(), { target: { value: "beta" } })
    fireEvent.click(await screen.findByRole("button", { name: "Leave" }))

    expect(await screen.findByRole("heading", { name: "Home of beta as nobody" })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe("/app/beta/home")
  })

  it("a pristine page switches campaign at once", async () => {
    renderAt("/app/alpha/notes")
    await settled()
    fireEvent.change(campaignSelect(), { target: { value: "beta" } })
    expect(await screen.findByRole("heading", { name: "Home of beta as nobody" })).toBeInTheDocument()
  })

  it("the sidebar campaign list is guarded the same way", async () => {
    renderAt("/app/alpha/notes")
    await settled()
    type("draft")
    const nav = screen.getByRole("navigation", { name: "Main" })
    fireEvent.click(within(nav).getByRole("button", { name: "Choose campaign" }))
    fireEvent.click(within(nav).getByRole("link", { name: "Campaign beta" }))

    expect(await screen.findByText("Leave this page?")).toBeInTheDocument()
    expect(router.state.location.pathname).toBe("/app/alpha/notes")
    fireEvent.click(screen.getByRole("button", { name: "Stay" }))
    expect(screen.getByLabelText("Draft")).toHaveValue("draft")
  })
})

describe("history and stamping", () => {
  it("stamps the initial entry by replacement: no prompt, no remount, no extra entry, no refresh", async () => {
    renderAt("/app/alpha/notes")
    await settled()
    type("draft")
    await waitFor(() => expect((router.state.location.state as { ctx?: unknown } | null)?.ctx).toEqual({ v: 1, characterId: null }))
    expect(router.state.historyAction).toBe("REPLACE")
    expect(question()).toBeNull()
    expect(screen.getByTestId("mount")).toHaveTextContent("1")
    expect(sessionRequests()).toBe(1)
    expect(router.state.location.pathname).toBe("/app/alpha/notes")
  })

  it("same-path Back across a perspective change is guarded after the transition markers are gone", async () => {
    renderAt("/app/alpha/notes")
    await settled()
    choosePerspective("char-b")
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("char-b"))
    await waitFor(() =>
      expect((router.state.location.state as { ctx?: unknown } | null)?.ctx).toEqual({ v: 1, characterId: "char-b" }),
    )
    type("draft")
    const sessionsBefore = sessionRequests()

    await act(async () => {
      await router.navigate(-1)
    })

    expect(await screen.findByText("Leave this page?")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Stay" }))
    expect(perspectiveSelect()).toHaveValue("char-b")
    expect(screen.getByLabelText("Draft")).toHaveValue("draft")
    expect(sessionRequests()).toBe(sessionsBefore)

    await act(async () => {
      await router.navigate(-1)
    })
    fireEvent.click(await screen.findByRole("button", { name: "Leave" }))
    await waitFor(() => expect(perspectiveSelect()).toHaveValue(""))
    expect(screen.getByLabelText("Draft")).toHaveValue("")
  })

  it("a query-only link stays unguarded while dirty, with a non-default perspective committed", async () => {
    renderAt("/app/alpha/notes")
    await settled()
    choosePerspective("char-b")
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("char-b"))
    type("draft")

    fireEvent.click(screen.getByRole("link", { name: "Section two" }))

    await waitFor(() => expect(router.state.location.search).toBe("?section=2"))
    expect(question()).toBeNull()
    expect(screen.getByLabelText("Draft")).toHaveValue("draft")
    expect(perspectiveSelect()).toHaveValue("char-b")
  })
})

describe("unresolved operations", () => {
  it("a navigation hold (pending or unknown write, open picker) makes a clean page ask; Stay keeps it", async () => {
    renderAt("/app/alpha/notes")
    await settled()
    fireEvent.click(screen.getByRole("button", { name: "Hold" }))

    choosePerspective("char-b")

    expect(await screen.findByText("Leave this page?")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Stay" }))
    expect(perspectiveSelect()).toHaveValue("")
    expect(screen.getByTestId("mount")).toHaveTextContent("1")
  })
})

describe("authorization and late responses", () => {
  it("a perspective the refreshed bootstrap no longer lists is cleared at once, even over a dirty page", async () => {
    renderAt("/app/alpha/notes")
    await settled()
    choosePerspective("char-b")
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("char-b"))
    await waitFor(() => expect(sessionRequests()).toBe(2))
    type("draft")

    // The next read of the session no longer lists char-b: permission loss never waits for a decision.
    server.campaigns = [campaign("alpha", ["char-a"]), campaign("beta", ["char-c"])]
    fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))

    await waitFor(() => expect(perspectiveSelect()).toHaveValue(""))
    expect(question()).toBeNull()
    expect(screen.queryByText("Loading portal")).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId("mount")).toHaveTextContent("3"))
    expect(screen.getByLabelText("Draft")).toHaveValue("")
    // The guard now compares against what is really committed: a query-only link is still unguarded.
    type("again")
    fireEvent.click(screen.getByRole("link", { name: "Section two" }))
    await waitFor(() => expect(router.state.location.search).toBe("?section=2"))
    expect(question()).toBeNull()
  })

  it("repeated transitions: the latest accepted perspective wins over an older, slower refresh", async () => {
    renderAt("/app/alpha/notes")
    await settled()
    const gate = deferred()
    server.sessionGates.set(2, gate.promise)

    choosePerspective("char-a")
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("char-a"))
    choosePerspective("char-b")
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("char-b"))
    await act(async () => {
      gate.release()
    })

    expect(perspectiveSelect()).toHaveValue("char-b")
    expect(screen.getByTestId("read")).toHaveTextContent("char-b")
  })

  it("a late read from the old perspective does not reach the new page", async () => {
    renderAt("/app/alpha/notes")
    const old = deferred()
    server.probeGates.set("", old.promise)
    await screen.findByRole("heading", { name: "Notes" })

    choosePerspective("char-b")
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("char-b"))
    await act(async () => {
      old.release()
    })

    expect(screen.getByTestId("read")).toHaveTextContent("char-b")
    expect(screen.getByTestId("mount")).toHaveTextContent("2")
  })
})

describe("syncCharacterFromUrl", () => {
  it("adopts an authorized URL character without navigating, reloading or refreshing", async () => {
    renderAt("/app/alpha/notes")
    await settled()
    const sessionsBefore = sessionRequests()
    const locationKey = router.state.location.key

    fireEvent.click(screen.getByRole("button", { name: "Sync char-b from URL" }))

    await waitFor(() => expect(perspectiveSelect()).toHaveValue("char-b"))
    expect(router.state.location.pathname).toBe("/app/alpha/notes")
    expect(screen.queryByText("Loading portal")).not.toBeInTheDocument()
    expect(sessionRequests()).toBe(sessionsBefore)
    // The entry is re-stamped, never turned back: the old stamp is not a request.
    await waitFor(() =>
      expect((router.state.location.state as { ctx?: unknown } | null)?.ctx).toEqual({ v: 1, characterId: "char-b" }),
    )
    expect(router.state.location.key).not.toBe(locationKey)
    expect(router.state.historyAction).toBe("REPLACE")
    expect(perspectiveSelect()).toHaveValue("char-b")
  })
})

describe("query-carried perspective", () => {
  it("drops the old character_id/party_id from the target so the query cannot reverse the transition", async () => {
    renderAt("/app/alpha/notes?character_id=char-a&party_id=p1&section=x")
    await settled()

    choosePerspective("char-b")

    await waitFor(() => expect(router.state.location.search).toBe("?section=x"))
    expect(perspectiveSelect()).toHaveValue("char-b")
    expect(router.state.location.pathname).toBe("/app/alpha/notes")
  })
})
