import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { useSyncExternalStore } from "react"
import { RouterProvider, createMemoryRouter, useLocation } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import App from "./App"
import { RouteSessionProvider } from "./context/RouteSessionProvider"
import { sessionBootstrapFixture } from "./fixtures/sessionBootstrap"
import { useSessionBootstrap } from "./hooks/useSessionBootstrap"
import type { SessionBootstrapState } from "./hooks/useSessionBootstrap"
import { installMockServer } from "./test/authoringHarness"
import type { MockServer } from "./test/authoringHarness"
import { ThemeProvider } from "./themes/ThemeProvider"
import type { SessionBootstrap } from "./types/bootstrap"
import { resolvePostLoginDestination } from "./utils/postLoginDestination"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const CSRF = "csrf-from-session"
const RULESETS = {
  items: [
    {
      ruleset_id: "r1",
      code: "dnd5e_2024",
      display_name: "D&D 5e (2024)",
      description: null,
      current_versions: [{ ruleset_version_id: "rv1", version_label: "1" }],
    },
  ],
}

const authenticated = (overrides: Partial<SessionBootstrap> = {}): SessionBootstrapState => ({
  status: "authenticated",
  bootstrap: {
    ...sessionBootstrapFixture,
    csrf_token: CSRF,
    global_capabilities: ["world.create"],
    ...overrides,
  },
})

let server: MockServer
let sessionState: SessionBootstrapState
const reload = vi.fn()

function LocationProbe() {
  const location = useLocation()
  return <p data-testid="location">{location.pathname}</p>
}

// A data router, as in main.tsx (the authoring forms use useBlocker): one splat
// route renders the whole application.
function tree(entry = "/worlds/new") {
  const router = createMemoryRouter(
    [
      {
        path: "*",
        element: (
          <>
            <ThemeProvider>
              <RouteSessionProvider>
                <App />
              </RouteSessionProvider>
            </ThemeProvider>
            <LocationProbe />
          </>
        ),
      },
    ],
    { initialEntries: [entry] },
  )
  return <RouterProvider router={router} />
}

// A subscribable session so a test can complete a login without rebuilding the
// router (the real hook updates its state the same way).
const listeners = new Set<() => void>()

function useState_(state: SessionBootstrapState) {
  sessionState = state
  listeners.forEach((listener) => listener())
}

beforeEach(() => {
  reload.mockReset()
  useState_(authenticated())
  vi.mocked(useSessionBootstrap).mockImplementation(() => ({
    state: useSyncExternalStore(
      (listener) => {
        listeners.add(listener)
        return () => listeners.delete(listener)
      },
      () => sessionState,
    ),
    reload,
    refresh: vi.fn(),
  }))
  server = installMockServer()
  server.on("GET", "/rulesets", { body: RULESETS })
  server.on("GET", /^\/worlds\?status=/, { body: { items: [], next_cursor: null } })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("/worlds/new inside the authenticated shell", () => {
  it("renders the creation form from the existing session, with no error boundary and no bootstrap request", async () => {
    render(tree())

    expect(await screen.findByRole("textbox", { name: /World name/ })).toBeInTheDocument()
    expect(screen.queryByText(/Unexpected Application Error/i)).toBeNull()
    expect(screen.getAllByRole("main")).toHaveLength(1)
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
    // The session is read from the shell; this page requests no bootstrap.
    expect(server.calls.some((call) => call.path.startsWith("/auth"))).toBe(false)
    expect(useSessionBootstrap).toHaveBeenCalled()
  })

  it("makes no creation request merely from opening the page", async () => {
    render(tree())
    await screen.findByRole("textbox", { name: /World name/ })

    expect(server.callsTo("POST", /./)).toEqual([])
  })

  it("submits with the session's CSRF token and same-origin credentials", async () => {
    server.on("POST", "/worlds", {
      status: 201,
      body: { world_id: "w-new", primary_timeline_id: "t-new", row_version: 1 },
    })
    server.on("GET", "/worlds/w-new", { status: 404 })
    render(tree())
    fireEvent.change(await screen.findByRole("textbox", { name: /World name/ }), {
      target: { value: "Eberron" },
    })
    // The single ruleset is preselected.
    fireEvent.click(screen.getByRole("button", { name: "Create world" }))

    await waitFor(() => expect(server.callsTo("POST", "/worlds")).toHaveLength(1))
    expect(server.callsTo("POST", "/worlds")[0]!.headers["X-CSRF-Token"]).toBe(CSRF)
    const init = vi
      .mocked(fetch)
      .mock.calls.find(([, options]) => options?.method === "POST")?.[1]
    expect(init?.credentials).toBe("same-origin")
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/worlds/w-new"),
    )
  })

  it("renders not-found for a direct visit without world.create and never requests rulesets", async () => {
    useState_(authenticated({ global_capabilities: [] }))
    render(tree())

    expect(
      await screen.findByRole("heading", { level: 1, name: "Page not found" }),
    ).toBeInTheDocument()
    expect(screen.getByTestId("location")).toHaveTextContent("/worlds/new")
    expect(screen.queryByRole("heading", { name: "Create a world" })).toBeNull()
    expect(screen.queryByRole("textbox", { name: /World name/ })).toBeNull()
    expect(screen.queryByRole("button", { name: "Create world" })).toBeNull()
    expect(server.callsTo("GET", "/rulesets")).toEqual([])
    expect(server.callsTo("POST", /./)).toEqual([])
    // The workspace keeps its single <main>.
    expect(screen.getAllByRole("main")).toHaveLength(1)
  })

  it("keeps the New world navigation slot visible but disabled for a player", async () => {
    useState_(authenticated({ global_capabilities: [] }))
    render(tree("/worlds"))
    await screen.findByRole("heading", { level: 1, name: "Worlds" })

    const nav = screen.getByRole("navigation", { name: "Main" })
    const slot = within(nav)
      .getByText("New world", { selector: "[aria-disabled='true'] .portal-sidebar__label" })
      .closest("[aria-disabled]")
    expect(slot).not.toBeNull()
    expect(slot).toHaveAttribute("aria-disabled", "true")
    expect(slot?.tagName).not.toBe("A")
    expect(slot).not.toHaveAttribute("href")
    expect(slot).not.toHaveAttribute("tabindex")
    expect(within(nav).queryByRole("link", { name: "New world", hidden: true })).toBeNull()
    // And no contextual creation action anywhere on the page.
    expect(screen.queryByRole("link", { name: "Create world" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Create world" })).toBeNull()
  })

  it("uses the established session recovery when the session has expired", async () => {
    server.on("GET", "/rulesets", { status: 401 })
    render(tree())

    await waitFor(() => expect(reload).toHaveBeenCalled())
  })

  it("sends an unauthenticated visit to login and returns to /worlds/new after sign-in", async () => {
    useState_({ status: "unauthenticated" })
    // Signing in asks whether an invitation continuation is pending; none is.
    server.on("GET", "/campaign-invitations/onboarding/status", { status: 404 })
    render(tree())

    expect(await screen.findByRole("heading", { name: "D&D AI World" })).toBeInTheDocument()
    expect(screen.getByTestId("location")).toHaveTextContent("/login")
    expect(server.calls).toEqual([])

    act(() => useState_(authenticated()))

    expect(await screen.findByRole("textbox", { name: /World name/ })).toBeInTheDocument()
    expect(screen.getByTestId("location")).toHaveTextContent("/worlds/new")
  })

  it("keeps the world collection route working", async () => {
    render(tree("/worlds"))

    expect(await screen.findByRole("heading", { level: 1, name: "Worlds" })).toBeInTheDocument()
  })
})

const worldDetail = (overrides: object = {}) => ({
  world_id: "w1",
  name: "Eberron",
  description: null,
  lifecycle_status: "active",
  row_version: 2,
  primary_timeline_id: "t1",
  capabilities: ["campaign.create", "timeline.manage", "world.manage", "world.view"],
  default_ruleset_id: null,
  allowed_rulesets: [],
  timelines: [],
  managed_campaigns: [],
  available_actions: ["update", "archive"],
  blocked_actions: [],
  ...overrides,
})

describe("/worlds/:worldId/edit inside the authenticated shell", () => {
  it("opens the edit form for a world the server lets the caller update", async () => {
    server.on("GET", "/worlds/w1", { body: worldDetail() })
    render(tree("/worlds/w1/edit"))

    expect(await screen.findByRole("textbox", { name: /World name/ })).toHaveValue("Eberron")
    expect(screen.getAllByRole("main")).toHaveLength(1)
  })

  it.each([
    ["a viewer", { capabilities: ["world.view"], available_actions: [] }],
    ["an owner of an archived world", { available_actions: ["restore"] }],
  ])("renders not-found and never mounts the form for %s", async (_label, overrides) => {
    server.on("GET", "/worlds/w1", { body: worldDetail(overrides) })
    render(tree("/worlds/w1/edit"))

    expect(
      await screen.findByRole("heading", { level: 1, name: "Page not found" }),
    ).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "Edit world" })).toBeNull()
    expect(screen.queryByRole("textbox", { name: /World name/ })).toBeNull()
    expect(screen.queryByRole("link", { name: "Edit world" })).toBeNull()
    expect(server.callsTo("POST", /./)).toEqual([])
    expect(screen.getAllByRole("main")).toHaveLength(1)
  })

  it("renders the same not-found for an unknown or undisclosed world", async () => {
    server.on("GET", "/worlds/w1", { status: 404 })
    render(tree("/worlds/w1/edit"))

    expect(
      await screen.findByRole("heading", { level: 1, name: "Page not found" }),
    ).toBeInTheDocument()
    expect(screen.queryByRole("textbox", { name: /World name/ })).toBeNull()
  })
})

describe("post-login continuation for world routes", () => {
  it.each(["/worlds", "/worlds/new", "/worlds/w1/timelines/t1"])("allows %s", (from) => {
    expect(resolvePostLoginDestination({ from })).toBe(from)
  })

  it("still rejects look-alike prefixes", () => {
    expect(resolvePostLoginDestination({ from: "/worldsX" })).toBe("/home")
  })
})
