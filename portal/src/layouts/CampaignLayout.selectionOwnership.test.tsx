import { act, configure, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { StrictMode, startTransition, useState } from "react"
import { Route, RouterProvider, Routes, createMemoryRouter, useLocation } from "react-router"
import type { DataRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { RouteSessionProvider } from "../context/RouteSessionProvider"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { ThemeProvider } from "../themes/ThemeProvider"
import type { CampaignContext, SessionBootstrap } from "../types/bootstrap"
import { AuthenticatedAppLayout } from "./AuthenticatedAppLayout"
import { CampaignSessionBoundary } from "./CampaignSessionBoundary"

// P02-0a selection ownership. The session answer that revokes the selected perspective and the
// accepted selection of another one land in the SAME React render (both published in one transition
// batch, from the router's own location notification). The session bootstrap is the only thing
// faked besides fetch: the shell, layout, perspective state, guards and router are the real ones, and
// there is no loader.

configure({ asyncUtilTimeout: 5000 })

const control = vi.hoisted(() => ({
  publish: null as null | ((bootstrap: unknown) => void),
  initial: null as unknown,
}))

vi.mock("../hooks/useSessionBootstrap", async () => {
  const react = await import("react")
  return {
    useSessionBootstrap: () => {
      const [bootstrap, setBootstrap] = react.useState(control.initial)
      control.publish = setBootstrap
      // Stable like the real hook's: resources re-read when `reload` changes identity.
      const refresh = react.useCallback(async () => true, [])
      const reload = react.useCallback(() => undefined, [])
      return { state: { status: "authenticated", bootstrap }, reload, refresh }
    },
  }
})

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

function bootstrapOf(perspectives: string[]): SessionBootstrap {
  return {
    user: { user_id: "u1", display_name: "Gina" },
    csrf_token: "csrf",
    browser_session_id: "s1",
    system_roles: ["player"],
    global_capabilities: [],
    startup_campaign_id: null,
    campaign_preferences: { startup_mode: "resume_last_visited", preferred_campaign_id: null, last_visited_campaign_id: null },
    campaigns: [campaign("alpha", perspectives), campaign("beta", ["char-c"])],
    features: { ask: false, ai_summaries: false, gm_briefs: false, cited_rules: false },
  }
}

const requests: string[] = []
const reads = () => requests.filter((r) => r.includes("/probe?")).map((r) => r.replace(/^.*character_id=/, ""))

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
}

function NotesPage() {
  const { getSelectedCharacterId } = usePerspective()
  const campaignId = useLocation().pathname.split("/")[2]!
  const perspective = getSelectedCharacterId(campaignId) ?? ""
  const [mountId] = useState(() => Math.random())
  const read = useAuthoringResource<{ who: string }>(`/campaigns/${campaignId}/probe?character_id=${perspective}`)
  return (
    <div>
      <h1>Notes</h1>
      <p data-testid="mount">{mountId}</p>
      <p data-testid="read">{read.state.kind === "ready" ? `ready:${read.state.data.who}` : read.state.kind}</p>
    </div>
  )
}

let router: DataRouter

function renderAt(strict: boolean) {
  router = createMemoryRouter(
    [
      {
        path: "*",
        element: (
          <RouteSessionProvider>
            <Routes>
              <Route element={<AuthenticatedAppLayout />}>
                <Route path="/app/:campaignId" element={<CampaignSessionBoundary />}>
                  <Route path="notes" element={<NotesPage />} />
                  {/* Where a deliberate perspective change lands (PD-6); the same probe page reads under it. */}
                  <Route path="characters/:characterId" element={<NotesPage />} />
                  <Route path="characters/all" element={<NotesPage />} />
                </Route>
              </Route>
            </Routes>
          </RouteSessionProvider>
        ),
      },
    ],
    { initialEntries: ["/app/alpha/notes"] },
  )
  const tree = (
    <ThemeProvider>
      <RouterProvider router={router} />
    </ThemeProvider>
  )
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree)
}

const select = () => screen.getByRole("combobox", { name: "Character perspective" }) as HTMLSelectElement
const choose = (value: string) => fireEvent.change(select(), { target: { value } })
const ctx = () => (router.state.location.state as { ctx?: unknown } | null)?.ctx

beforeEach(() => {
  requests.length = 0
  control.initial = bootstrapOf(["char-a", "char-b"])
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString()
      requests.push(url)
      const probe = /\/probe\?character_id=([^&]*)/.exec(url)
      if (probe !== null) return json({ who: decodeURIComponent(probe[1]!) })
      return json({ detail: "not found" }, 404)
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

// Selects B, then `target` (a perspective, or "" for none) with the answer that revokes B published in
// the same batch as the accepted location.
async function selectBThenTargetWithRevocationInTheSameBatch(target: string, stillAuthorized: string[]): Promise<void> {
  await screen.findByRole("heading", { name: "Notes" })
  await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("ready:"))
  choose("char-b")
  await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("ready:char-b"))

  let fired = false
  const unsubscribe = router.subscribe((state) => {
    const stamp = (state.location.state as { ctx?: { characterId?: string | null } } | null)?.ctx
    if (!fired && stamp !== undefined && stamp.characterId === (target === "" ? null : target)) {
      fired = true
      // The router's own subscriber has just queued the location; this lands in the same batch.
      startTransition(() => control.publish!(bootstrapOf(stillAuthorized)))
    }
  })
  await act(async () => {
    choose(target)
  })
  unsubscribe()
  expect(fired).toBe(true)
}

// Consecutive repeats collapsed (StrictMode runs effects, and so reads, twice).
const readOrder = () => reads().filter((value, index, all) => index === 0 || value !== all[index - 1])

async function settle(): Promise<void> {
  await act(async () => {
    await Promise.resolve()
  })
}

describe.each([
  ["plain", false],
  ["StrictMode", true],
])("a newer accepted selection supersedes the revocation of the old one (%s)", (_name, strict) => {
  it("same batch: A stays A, with reads B then A and none after", async () => {
    renderAt(strict)
    await selectBThenTargetWithRevocationInTheSameBatch("char-a", ["char-a"])

    await waitFor(() => expect(select()).toHaveValue("char-a"))
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("ready:char-a"))
    await waitFor(() => expect(ctx()).toMatchObject({ v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t1", characterId: "char-a" }))
    await settle()
    expect(select()).toHaveValue("char-a")
    expect(ctx()).toMatchObject({ v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t1", characterId: "char-a" })
    expect(readOrder()).toEqual(["", "char-b", "char-a"])
    expect(reads().at(-1)).toBe("char-a")
    expect(screen.queryByRole("status")).toBeNull()
  })

  it("same batch: a newer explicit none wins and is not reported as a loss", async () => {
    renderAt(strict)
    await selectBThenTargetWithRevocationInTheSameBatch("", ["char-a"])

    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("ready:"))
    await waitFor(() => expect(ctx()).toMatchObject({ v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t1", characterId: null }))
    await settle()
    expect(select()).toHaveValue("")
    expect(readOrder()).toEqual(["", "char-b", ""])
    expect(screen.queryByRole("status")).toBeNull()
  })

  it("ordinary revocation with nothing newer still clears to explicit none, with the notice", async () => {
    renderAt(strict)
    await screen.findByRole("heading", { name: "Notes" })
    choose("char-b")
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("ready:char-b"))

    await act(async () => {
      startTransition(() => control.publish!(bootstrapOf(["char-a"])))
    })

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("no longer available"))
    await waitFor(() => expect(ctx()).toMatchObject({ v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t1", characterId: null }))
    expect(select()).toHaveValue("")
    expect(readOrder()).toEqual(["", "char-b", ""])
  })

  it("re-authorization after the clearing completed does not resurrect the lost selection", async () => {
    renderAt(strict)
    await screen.findByRole("heading", { name: "Notes" })
    choose("char-b")
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent("ready:char-b"))
    await act(async () => {
      startTransition(() => control.publish!(bootstrapOf(["char-a"])))
    })
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("no longer available"))
    await waitFor(() => expect(screen.getByTestId("read")).toHaveTextContent(/^ready:$/))
    const before = reads().length
    const mountBefore = screen.getByTestId("mount").textContent

    await act(async () => {
      startTransition(() => control.publish!(bootstrapOf(["char-a", "char-b"])))
    })
    await settle()

    expect(select()).toHaveValue("")
    expect(ctx()).toMatchObject({ v: 1, campaignId: "alpha", worldId: "w1", timelineId: "t1", characterId: null })
    expect(screen.getByTestId("mount").textContent).toBe(mountBefore)
    expect(reads()).toHaveLength(before)
  })
})
