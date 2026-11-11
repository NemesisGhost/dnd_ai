import { act, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { StrictMode, useState } from "react"
import { Link, Route, RouterProvider, Routes, createMemoryRouter, useLocation, useSearchParams } from "react-router"
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
  // As the Knowledge and Quest pages do: an address that names a character is what the page asks as.
  const asCharacter = useSearchParams()[0].get("character_id") ?? perspective
  const read = useAuthoringResource<{ who: string }>(`/campaigns/${campaignId}/probe?character_id=${asCharacter}`)
  return (
    <div>
      <h1>Notes</h1>
      <p data-testid="mount">{mountId}</p>
      <p data-testid="read">{read.state.kind === "ready" ? `ready:${read.state.data.who}` : read.state.kind}</p>
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
      <button type="button" onClick={() => syncCharacterFromUrl?.(campaignId, "char-a")}>
        Sync char-a from URL
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
function renderAt(path: string, state?: unknown, { strict = false }: { strict?: boolean } = {}) {
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
  const tree = (
    <ThemeProvider>
      <RouterProvider router={router} />
    </ThemeProvider>
  )
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree)
}

function TestRoutes() {
  return (
    <Routes>
      <Route element={<AuthenticatedAppLayout />}>
        <Route path="/app/:campaignId" element={<CampaignSessionBoundary />}>
          <Route path="home" element={<HomePage />} />
          <Route path="notes" element={<NotesPage />} />
                  {/* Where a deliberate perspective change lands (PD-6); the same probe page reads under it. */}
                  <Route path="characters/:characterId" element={<NotesPage />} />
                  <Route path="characters/all" element={<NotesPage />} />
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
    // The deliberate change is a departure to the character's Characters details (PD-6).
    expect(router.state.location.pathname).toBe("/app/alpha/characters/char-b")
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
    fireEvent.click(within(nav).getByRole("button", { name: "Show campaign menu" }))
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
    await waitFor(() => expect((router.state.location.state as { ctx?: unknown } | null)?.ctx).toMatchObject({ v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t1", characterId: null }))
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
      expect((router.state.location.state as { ctx?: unknown } | null)?.ctx).toMatchObject({ v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t1", characterId: "char-b" }),
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
    expect(screen.getByRole("status")).toHaveTextContent("Your selected character is no longer available.")
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

describe("revocation is an explicit, lasting clear", () => {
  async function selectBThenRevoke() {
    renderAt("/app/alpha/notes")
    await settled()
    choosePerspective("char-b")
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("char-b"))
    await waitFor(() => expect(sessionRequests()).toBe(2))
    server.campaigns = [campaign("alpha", ["char-a"]), campaign("beta", ["char-c"])]
    fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("no longer available"))
  }

  it("re-authorization alone neither restores the lost perspective nor remounts away a new draft", async () => {
    await selectBThenRevoke()
    expect(perspectiveSelect()).toHaveValue("")
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent(/^ready:$/))
    const mountsNow = screen.getByTestId("mount").textContent
    type("work after the loss")

    // Eligibility comes back, and the server default now names the lost character as well.
    server.campaigns = [{ ...campaign("alpha", ["char-a", "char-b"]), selected_character_id: "char-b" }, campaign("beta", ["char-c"])]
    fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))
    await waitFor(() => expect(sessionRequests()).toBe(4))

    expect(perspectiveSelect()).toHaveValue("")
    expect(screen.getByLabelText("Draft")).toHaveValue("work after the loss")
    expect(screen.getByTestId("mount")).toHaveTextContent(mountsNow!)
    expect(question()).toBeNull()
    // Choosing it again is the ordinary, guarded selection.
    choosePerspective("char-b")
    expect(await screen.findByText("Leave this page?")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Stay" }))
    expect(perspectiveSelect()).toHaveValue("")
  })

  it("the history entry agrees: it records no perspective, and Back to a stamped older entry is an ordinary guarded return", async () => {
    await selectBThenRevoke()
    await waitFor(() =>
      expect((router.state.location.state as { ctx?: unknown } | null)?.ctx).toMatchObject({ v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t1", characterId: null }),
    )
    expect(router.state.historyAction).toBe("REPLACE")
  })

  it("a default that is revoked is cleared too, and not restored by its return", async () => {
    server.campaigns = [{ ...campaign("alpha", ["char-a", "char-b"]), selected_character_id: "char-a" }, campaign("beta", ["char-c"])]
    renderAt("/app/alpha/notes")
    await settled()
    expect(perspectiveSelect()).toHaveValue("char-a")
    server.campaigns = [{ ...campaign("alpha", ["char-b"]), selected_character_id: null }, campaign("beta", ["char-c"])]
    fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("no longer available"))
    expect(perspectiveSelect()).toHaveValue("")

    server.campaigns = [{ ...campaign("alpha", ["char-a", "char-b"]), selected_character_id: "char-a" }, campaign("beta", ["char-c"])]
    fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))
    await waitFor(() => expect(sessionRequests()).toBe(3))
    expect(perspectiveSelect()).toHaveValue("")
  })

  it("cleans a revoked address, reads once under none and never again as the lost character", async () => {
    renderAt("/app/alpha/notes?character_id=char-b&party_id=p1&section=x", { ctx: { v: 1, characterId: "char-b" } })
    await settled()
    expect(perspectiveSelect()).toHaveValue("char-b")
    const readsAsB = () => probeRequests().filter((r) => r.endsWith("character_id=char-b")).length
    const before = readsAsB()

    server.campaigns = [campaign("alpha", ["char-a"]), campaign("beta", ["char-c"])]
    fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))

    await waitFor(() => expect(router.state.location.search).toBe("?section=x"))
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent(/^ready:$/))
    expect(router.state.location.pathname).toBe("/app/alpha/notes")
    expect(perspectiveSelect()).toHaveValue("")
    expect(readsAsB()).toBe(before)
    expect(probeRequests().filter((r) => r.endsWith("character_id="))).toHaveLength(1)
    await waitFor(() =>
      expect((router.state.location.state as { ctx?: unknown } | null)?.ctx).toMatchObject({ v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t1", characterId: null }),
    )
    expect(router.state.historyAction).toBe("REPLACE")
  })

  it("a late answer to the lost perspective's read cannot restore private content", async () => {
    const lateB = deferred()
    server.probeGates.set("char-b", lateB.promise)
    renderAt("/app/alpha/notes?character_id=char-b&section=x", { ctx: { v: 1, characterId: "char-b" } })
    await screen.findByRole("heading", { name: "Notes" })
    await waitFor(() => expect(probeRequests().some((r) => r.endsWith("character_id=char-b"))).toBe(true))

    server.campaigns = [campaign("alpha", ["char-a"]), campaign("beta", ["char-c"])]
    fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))
    await waitFor(() => expect(router.state.location.search).toBe("?section=x"))
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent(/^ready:$/))
    await act(async () => {
      lateB.release()
    })

    expect(screen.getByTestId("read")).not.toHaveTextContent("char-b")
    expect(perspectiveSelect()).toHaveValue("")
  })
})

describe("permission loss completes over a guarded page", () => {
  async function openAddressedPage() {
    renderAt("/app/alpha/notes?character_id=char-b&party_id=p1&section=x", { ctx: { v: 1, characterId: "char-b" } })
    await settled()
    expect(perspectiveSelect()).toHaveValue("char-b")
    type("draft that belongs to the lost perspective")
  }
  function revokeB() {
    server.campaigns = [campaign("alpha", ["char-a"]), campaign("beta", ["char-c"])]
    fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))
  }
  async function expectSafePage() {
    await waitFor(() => expect(router.state.location.search).toBe("?section=x"))
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent(/^ready:$/))
    expect(screen.getByRole("status")).toHaveTextContent("Your selected character is no longer available.")
    expect(perspectiveSelect()).toHaveValue("")
    expect(screen.getByLabelText("Draft")).toHaveValue("")
    expect(question()).toBeNull()
    expect(router.state.location.pathname).toBe("/app/alpha/notes")
    expect((router.state.location.state as { ctx?: unknown } | null)?.ctx).toMatchObject({ v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t1", characterId: null })
  }

  it("A: revocation while the page's own question is open completes, without approving that departure", async () => {
    await openAddressedPage()
    choosePerspective("char-a")
    expect(await screen.findByText("Leave this page?")).toBeInTheDocument()

    revokeB()

    await expectSafePage()
    // The blocked departure was cancelled, not approved: still on b's former address, on the same path.
    expect(router.state.historyAction).toBe("REPLACE")
    expect(probeRequests().filter((r) => r.endsWith("character_id=char-a"))).toHaveLength(0)
  })

  it("B: revocation of a dirty addressed page with no question yet completes the cleanup", async () => {
    await openAddressedPage()

    revokeB()

    await expectSafePage()
  })

  it("dirty work entered afterwards is guarded again by ordinary navigation", async () => {
    await openAddressedPage()
    revokeB()
    await expectSafePage()
    type("new work")

    choosePerspective("char-a")
    expect(await screen.findByText("Leave this page?")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Stay" }))
    expect(screen.getByLabelText("Draft")).toHaveValue("new work")
    fireEvent.click(screen.getByRole("link", { name: "Section two" }))
    await waitFor(() => expect(router.state.location.search).toBe("?section=2"))
    expect(question()).toBeNull()
  })
})

describe("permission loss: ownership and the held departure", () => {
  it("a newer navigation supersedes the cleanup, and its own address is validated in turn", async () => {
    renderAt("/app/alpha/notes?character_id=char-b&section=x", { ctx: { v: 1, characterId: "char-b" } })
    await settled()
    type("draft")
    const gate = deferred()
    server.sessionGates.set(2, gate.promise)
    server.campaigns = [campaign("alpha", ["char-a"]), campaign("beta", ["char-c"])]
    fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))

    // While that answer is pending the person follows a link that still names the lost character.
    await act(async () => {
      await router.navigate({ search: "?character_id=char-b&section=9" }, { state: { ctx: { v: 1, characterId: "char-b" } } })
    })
    expect(question()).toBeNull()
    await act(async () => {
      gate.release()
    })

    await waitFor(() => expect(router.state.location.search).toBe("?section=9"))
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent(/^ready:$/))
    expect(perspectiveSelect()).toHaveValue("")
    expect(screen.getByRole("status")).toHaveTextContent("no longer available")
    expect(question()).toBeNull()
  })

  it("the held departure is cancelled, not approved: nothing navigates and no question returns", async () => {
    renderAt("/app/alpha/notes?character_id=char-b&section=x", { ctx: { v: 1, characterId: "char-b" } })
    await settled()
    type("draft")
    choosePerspective("char-a")
    expect(await screen.findByText("Leave this page?")).toBeInTheDocument()
    server.campaigns = [campaign("alpha", ["char-a"]), campaign("beta", ["char-c"])]
    fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("no longer available"))
    await act(async () => {
      await Promise.resolve()
    })
    expect(question()).toBeNull()
    expect(perspectiveSelect()).toHaveValue("")
    expect(router.state.location.pathname).toBe("/app/alpha/notes")
    expect([...router.state.blockers.values()].some((b) => b.state === "blocked" || b.state === "proceeding")).toBe(false)
  })
})

describe("a bootstrap default only initializes the selection", () => {
  it("default A revoked while B becomes the new default: read as A, then with no perspective, never as B", async () => {
    server.campaigns = [{ ...campaign("alpha", ["char-a"]), selected_character_id: "char-a" }, campaign("beta", ["char-c"])]
    renderAt("/app/alpha/notes")
    await settled()
    expect(perspectiveSelect()).toHaveValue("char-a")
    expect(probeRequests().map((r) => r.replace(/^.*character_id=/, ""))).toEqual(["char-a"])

    server.campaigns = [{ ...campaign("alpha", ["char-b"]), selected_character_id: "char-b" }, campaign("beta", ["char-c"])]
    fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("no longer available"))
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent(/^ready:$/))

    expect(perspectiveSelect()).toHaveValue("")
    expect(probeRequests().map((r) => r.replace(/^.*character_id=/, ""))).toEqual(["char-a", ""])
    expect(router.state.location.pathname).toBe("/app/alpha/notes")
    expect((router.state.location.state as { ctx?: unknown } | null)?.ctx).toMatchObject({ v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t1", characterId: null })
  })

  it("re-authorization, and a default that comes back, cannot resurrect the lost selection", async () => {
    server.campaigns = [{ ...campaign("alpha", ["char-a"]), selected_character_id: "char-a" }, campaign("beta", ["char-c"])]
    renderAt("/app/alpha/notes")
    await settled()
    server.campaigns = [{ ...campaign("alpha", ["char-b"]), selected_character_id: "char-b" }, campaign("beta", ["char-c"])]
    fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("no longer available"))
    type("new work")
    const reads = probeRequests().length

    server.campaigns = [{ ...campaign("alpha", ["char-a", "char-b"]), selected_character_id: "char-a" }, campaign("beta", ["char-c"])]
    fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))
    await waitFor(() => expect(sessionRequests()).toBe(3))

    expect(perspectiveSelect()).toHaveValue("")
    expect(screen.getByLabelText("Draft")).toHaveValue("new work")
    expect(probeRequests()).toHaveLength(reads)
  })

  it("an uninitialized start still uses the authorized default, and a later default does not replace it", async () => {
    server.campaigns = [{ ...campaign("alpha", ["char-a", "char-b"]), selected_character_id: "char-a" }, campaign("beta", ["char-c"])]
    renderAt("/app/alpha/notes")
    await settled()
    expect(perspectiveSelect()).toHaveValue("char-a")

    server.campaigns = [{ ...campaign("alpha", ["char-a", "char-b"]), selected_character_id: "char-b" }, campaign("beta", ["char-c"])]
    fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))
    await waitFor(() => expect(sessionRequests()).toBe(2))

    expect(perspectiveSelect()).toHaveValue("char-a")
    expect(screen.getByTestId("mount")).toHaveTextContent("1")
  })
})

describe("selection ownership: a newer accepted selection supersedes a pending revocation", () => {
  // Consecutive repeats collapsed (StrictMode runs effects, and so reads, twice).
  const readsInOrder = () =>
    probeRequests()
      .map((r) => r.replace(/^.*character_id=/, ""))
      .filter((value, index, all) => index === 0 || value !== all[index - 1])

  // B is selected and its refresh (request 2) is held; that answer revokes B but keeps A.
  async function bSelectedWithRevokingRefreshPending(strict: boolean) {
    renderAt("/app/alpha/notes", undefined, { strict })
    await settled()
    const gate = deferred()
    server.sessionGates.set(2, gate.promise)
    server.campaigns = [campaign("alpha", ["char-a"]), campaign("beta", ["char-c"])]
    choosePerspective("char-b")
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("char-b"))
    await waitFor(() => expect(sessionRequests()).toBe(2))
    return gate
  }

  async function expectFinal(perspective: string) {
    await waitFor(() => expect(perspectiveSelect()).toHaveValue(perspective))
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent(`ready:${perspective}`))
    await waitFor(() =>
      expect((router.state.location.state as { ctx?: unknown } | null)?.ctx).toMatchObject({
        v: 1,
        campaignId: "alpha",
        worldId: "w1",
        timelineId: "t1",
        characterId: perspective === "" ? null : perspective,
      }),
    )
    expect(perspectiveSelect()).toHaveValue(perspective)
  }

  it.each([
    ["plain", false],
    ["StrictMode", true],
  ])("A accepted with the revoking answer released together (separate renders) stays A (%s)", async (_name, strict) => {
    const gate = await bSelectedWithRevokingRefreshPending(strict)

    await act(async () => {
      choosePerspective("char-a")
      gate.release()
    })

    await expectFinal("char-a")
    expect(readsInOrder()).toEqual(["", "char-b", "char-a"])
    expect(screen.queryByRole("status")).toBeNull()
    expect(router.state.location.pathname).toBe("/app/alpha/characters/char-a")
  })

  it("A accepted before the revoking answer arrives stays A, and the answer then changes nothing", async () => {
    const gate = await bSelectedWithRevokingRefreshPending(false)

    choosePerspective("char-a")
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("char-a"))
    await act(async () => {
      gate.release()
    })

    await expectFinal("char-a")
    expect(readsInOrder()).toEqual(["", "char-b", "char-a"])
    expect(screen.queryByRole("status")).toBeNull()
  })

  it("a newer explicit none wins over the pending revocation", async () => {
    const gate = await bSelectedWithRevokingRefreshPending(false)

    await act(async () => {
      choosePerspective("")
      gate.release()
    })

    await expectFinal("")
    expect(readsInOrder()).toEqual(["", "char-b", ""])
    expect(screen.queryByRole("status")).toBeNull()
  })

  it("with no intervening selection the revocation still clears to explicit none", async () => {
    const gate = await bSelectedWithRevokingRefreshPending(false)

    await act(async () => {
      gate.release()
    })

    await expectFinal("")
    expect(readsInOrder()).toEqual(["", "char-b", ""])
    expect(screen.getByRole("status")).toHaveTextContent("no longer available")
  })

  it("a proposal naming the already-revoked selection never wins", async () => {
    const gate = await bSelectedWithRevokingRefreshPending(false)
    await act(async () => {
      gate.release()
    })
    await expectFinal("")

    await act(async () => {
      await router.navigate({ pathname: "/app/alpha/notes" }, { state: { ctx: { v: 1, characterId: "char-b" } } })
    })

    await expectFinal("")
    expect(readsInOrder().filter((r) => r === "char-b")).toHaveLength(1)
  })

  it("a superseding campaign transition is not undone by the late answer", async () => {
    const gate = await bSelectedWithRevokingRefreshPending(false)

    fireEvent.change(campaignSelect(), { target: { value: "beta" } })
    expect(await screen.findByRole("heading", { name: "Home of beta as nobody" })).toBeInTheDocument()
    await act(async () => {
      gate.release()
    })

    expect(router.state.location.pathname).toBe("/app/beta/home")
    expect(screen.getByRole("heading", { name: "Home of beta as nobody" })).toBeInTheDocument()
    expect(screen.queryByRole("status")).toBeNull()
  })

  it("re-authorization after the clearing completed does not resurrect the lost selection", async () => {
    const gate = await bSelectedWithRevokingRefreshPending(false)
    await act(async () => {
      gate.release()
    })
    await expectFinal("")
    const reads = probeRequests().length

    server.campaigns = [campaign("alpha", ["char-a", "char-b"]), campaign("beta", ["char-c"])]
    fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))
    await waitFor(() => expect(sessionRequests()).toBe(3))

    expect(perspectiveSelect()).toHaveValue("")
    expect(probeRequests()).toHaveLength(reads)
  })

  it("an adopted URL character also supersedes a pending revocation", async () => {
    const gate = await bSelectedWithRevokingRefreshPending(false)

    fireEvent.click(screen.getByRole("button", { name: "Sync char-a from URL" }))
    await act(async () => {
      gate.release()
    })

    await expectFinal("char-a")
  })
})

describe("initial entry and stamp ownership", () => {
  it("honors an authorized initial stamp before anything reads under the default", async () => {
    renderAt("/app/alpha/notes", { ctx: { v: 1, characterId: "char-b" } })
    await screen.findByRole("heading", { name: "Notes" })
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("char-b"))

    expect(perspectiveSelect()).toHaveValue("char-b")
    expect(probeRequests().every((r) => r.endsWith("character_id=char-b"))).toBe(true)
    expect(screen.getByTestId("mount")).toHaveTextContent("1")
  })

  it("restores the stamped perspective on Back from another campaign", async () => {
    renderAt("/app/alpha/notes")
    await settled()
    choosePerspective("char-b")
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("char-b"))
    await waitFor(() =>
      expect((router.state.location.state as { ctx?: unknown } | null)?.ctx).toMatchObject({ v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t1", characterId: "char-b" }),
    )

    fireEvent.change(campaignSelect(), { target: { value: "beta" } })
    expect(await screen.findByRole("heading", { name: "Home of beta as nobody" })).toBeInTheDocument()
    await act(async () => {
      await router.navigate(-1)
    })

    await waitFor(() => expect(perspectiveSelect()).toHaveValue("char-b"))
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("char-b"))
    expect(router.state.location.pathname).toBe("/app/alpha/characters/char-b")
  })

  it.each([
    ["missing", undefined],
    ["null", null],
    ["malformed", { ctx: "char-b" }],
    ["a wrong version", { ctx: { v: 2, characterId: "char-b" } }],
    ["a wrong type", { ctx: { v: 1, characterId: 7 } }],
    ["an unauthorized id", { ctx: { v: 1, characterId: "someone-else" } }],
    ["a foreign campaign's character", { ctx: { v: 1, characterId: "char-c" } }],
  ])("keeps the default and repairs the stamp when the initial entry state is %s", async (_name, state) => {
    renderAt("/app/alpha/notes", state)
    await settled()
    expect(perspectiveSelect()).toHaveValue("")
    await waitFor(() =>
      expect((router.state.location.state as { ctx?: unknown } | null)?.ctx).toMatchObject({ v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t1", characterId: null }),
    )
  })

  it("an immediate click during initial stamping is not overwritten, and adds no entry or question", async () => {
    renderAt("/app/alpha/notes")
    await screen.findByRole("heading", { name: "Notes" })
    type("draft")

    fireEvent.click(screen.getByRole("link", { name: "Section two" }))
    expect(router.state.location.search).toBe("?section=2")

    await waitFor(() =>
      expect((router.state.location.state as { ctx?: unknown } | null)?.ctx).toMatchObject({ v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t1", characterId: null }),
    )
    expect(router.state.location.search).toBe("?section=2")
    expect(question()).toBeNull()
    expect(screen.getByTestId("mount")).toHaveTextContent("1")
    expect(sessionRequests()).toBe(1)
    // One PUSH on top of the initial entry: Back returns to it, not to a stamping leftover.
    await act(async () => {
      await router.navigate(-1)
    })
    expect(router.state.location.search).toBe("")
  })

  it("never lets a stamp apply while a blocked transition waits for its answer", async () => {
    renderAt("/app/alpha/notes")
    await settled()
    type("draft")
    choosePerspective("char-b")
    expect(await screen.findByText("Leave this page?")).toBeInTheDocument()
    const held = router.state.location

    await act(async () => {
      await Promise.resolve()
    })
    expect(router.state.location).toBe(held)
    fireEvent.click(screen.getByRole("button", { name: "Stay" }))
    expect(router.state.location).toBe(held)
    expect(perspectiveSelect()).toHaveValue("")
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
      expect((router.state.location.state as { ctx?: unknown } | null)?.ctx).toMatchObject({ v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t1", characterId: "char-b" }),
    )
    expect(router.state.location.key).not.toBe(locationKey)
    expect(router.state.historyAction).toBe("REPLACE")
    expect(perspectiveSelect()).toHaveValue("char-b")
  })
})

describe("a replacement never asks for a perspective", () => {
  it("a page rewriting its query with older state does not turn back an adopted URL character", async () => {
    renderAt("/app/alpha/notes")
    await settled()
    fireEvent.click(screen.getByRole("button", { name: "Sync char-b from URL" }))
    await waitFor(() => expect(perspectiveSelect()).toHaveValue("char-b"))

    await act(async () => {
      await router.navigate({ search: "?x=1" }, { replace: true, state: { ctx: { v: 1, characterId: null } } })
    })

    await waitFor(() =>
      expect((router.state.location.state as { ctx?: unknown } | null)?.ctx).toMatchObject({ v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t1", characterId: "char-b" }),
    )
    expect(perspectiveSelect()).toHaveValue("char-b")
    expect(router.state.location.search).toBe("?x=1")
    expect(sessionRequests()).toBe(1)
  })
})

describe("query-carried perspective", () => {
  it("starts the character's details with none of the page's query, so nothing can reverse the transition", async () => {
    renderAt("/app/alpha/notes?character_id=char-a&party_id=p1&section=x")
    await settled()

    choosePerspective("char-b")

    await waitFor(() => expect(router.state.location.pathname).toBe("/app/alpha/characters/char-b"))
    // Neither the old pair nor the page-specific `section` is carried into the new task.
    expect(router.state.location.search).toBe("")
    expect(perspectiveSelect()).toHaveValue("char-b")
  })
})
