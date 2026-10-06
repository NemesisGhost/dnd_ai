import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { createMemoryRouter, RouterProvider } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import App from "./App"
import { RouteSessionProvider } from "./context/RouteSessionProvider"
import { sessionBootstrapFixture } from "./fixtures/sessionBootstrap"
import { useSessionBootstrap } from "./hooks/useSessionBootstrap"
import { installMockServer } from "./test/authoringHarness"
import type { MockServer } from "./test/authoringHarness"
import { ThemeProvider } from "./themes/ThemeProvider"
import type { SessionBootstrap } from "./types/bootstrap"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const OPTIONS = {
  can_create: true,
  categories: [
    { code: "region", label: "Region", fields: [] },
    {
      code: "settlement",
      label: "Settlement",
      fields: [
        { name: "population", kind: "integer", label: "Population", max_length: null, minimum: 0, maximum: 2147483647 },
      ],
    },
  ],
  limits: { name_max_length: 200, summary_max_length: 4000, change_note_max_length: 1000 },
}

const AUTHORING_VIEW = {
  location_id: "l1",
  name: "Hollow",
  summary: null,
  category: { code: "region", label: "Region" },
  parent: null,
  population: null,
  building_use: null,
  canon_status: "draft",
  lifecycle_status: "active",
  row_version: 2,
  available_actions: ["update", "archive"],
  blocked_actions: [],
  field_locks: [],
}

const LOCATION_DETAIL = {
  location_id: "l1",
  name: "Hollow",
  summary: null,
  location_type_code: "region",
  parent_location_id: null,
  breadcrumbs: [],
  population: null,
  building_use: null,
  danger_level: null,
  is_searched: null,
  is_destroyed: null,
  alarm_level: null,
  condition_notes: null,
}

const bootstrap = (capabilities: string[]): SessionBootstrap => ({
  ...sessionBootstrapFixture,
  csrf_token: "csrf-from-session",
  campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, capabilities }],
})

let server: MockServer

function tree(entry: string) {
  const router = createMemoryRouter(
    [
      {
        path: "*",
        element: (
          <ThemeProvider>
            <RouteSessionProvider>
              <App />
            </RouteSessionProvider>
          </ThemeProvider>
        ),
      },
    ],
    { initialEntries: [entry] },
  )
  return { router, ui: <RouterProvider router={router} /> }
}

function open(entry: string, capabilities: string[] = ["access.manage", "canon.edit"]) {
  vi.mocked(useSessionBootstrap).mockReturnValue({
    state: { status: "authenticated", bootstrap: bootstrap(capabilities) },
    reload: vi.fn(),
    refresh: vi.fn(),
  })
  const { router, ui } = tree(entry)
  return { router, ...render(ui) }
}

beforeEach(() => {
  server = installMockServer()
  server.on("GET", "/campaigns/mundivita/authoring/locations/options", { body: OPTIONS })
  server.on("GET", "/campaigns/mundivita/authoring/locations/l1", { body: AUTHORING_VIEW })
  server.on("GET", /parent-options/, { body: { items: [], next_cursor: null } })
  server.on("GET", "/campaigns/mundivita/world/locations/l1", { body: LOCATION_DETAIL })
  server.on("GET", "/campaigns/mundivita/entities/l1/lifecycle", {
    body: {
      entity_id: "l1",
      entity_type_code: "region",
      canonical_name: "Hollow",
      canon_status: "draft",
      lifecycle_status: "active",
      row_version: 2,
      lifecycle_managed: true,
      superseded_by: null,
      available_actions: ["submit_for_review", "archive"],
      blocked_actions: [],
    },
  })
  server.on("GET", /^\/campaigns\/mundivita\/world\/search/, {
    body: { items: [], next_cursor: null },
  })
  server.on("GET", /^\/campaigns\/mundivita\/world(\?|$)/, { body: { items: [], next_cursor: null } })
  server.on("GET", /^\/campaigns\/mundivita\/summary/, { body: {} })
  server.on("GET", /^\/worlds\?/, { body: { items: [], next_cursor: null } })
  server.on("GET", "/worlds/world-mundivita", {
    body: {
      world_id: "world-mundivita",
      name: "Mundivita",
      description: null,
      lifecycle_status: "active",
      row_version: 1,
      primary_timeline_id: "timeline-primary",
      capabilities: ["campaign.create", "timeline.manage", "world.manage", "world.view"],
      allowed_rulesets: [],
      timelines: [
        {
          timeline_id: "timeline-primary",
          name: "Primary Timeline",
          description: null,
          is_primary: true,
          parent_timeline_id: null,
          branch_point: null,
          lifecycle_status: "active",
          row_version: 1,
        },
      ],
      managed_campaigns: [],
      available_actions: [],
      blocked_actions: [],
    },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("location authoring routes", () => {
  it("loads the creation form directly, and the static route beats the detail route", async () => {
    open("/app/mundivita/world/location/new")

    expect(await screen.findByRole("combobox", { name: /Category/ })).toBeInTheDocument()
    expect(screen.getAllByRole("main")).toHaveLength(1)
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
    expect(screen.getByRole("heading", { level: 1, name: "New location" })).toBeInTheDocument()
    expect(screen.queryByText(/Unexpected Application Error/i)).toBeNull()
    // "new" is never treated as an entity id.
    expect(server.calls.some((c) => c.path.includes("/world/locations/new"))).toBe(false)
  })

  it("loads the edit form directly from its own URL", async () => {
    open("/app/mundivita/world/location/l1/edit")

    expect(await screen.findByRole("textbox", { name: /Name/ })).toHaveValue("Hollow")
    expect(screen.getByRole("heading", { level: 1, name: "Edit location" })).toBeInTheDocument()
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
  })

  it("shows an editor the Edit link on the detail page", async () => {
    open("/app/mundivita/world/location/l1")

    const link = await screen.findByRole("link", { name: "Edit location" })
    expect(link).toHaveAttribute("href", "/app/mundivita/world/location/l1/edit")
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
  })

  it("shows a player neither the Edit link nor any authoring request", async () => {
    open("/app/mundivita/world/location/l1", ["campaign.view"])

    await screen.findByRole("heading", { level: 1, name: "Hollow" })
    expect(screen.queryByRole("link", { name: "Edit location" })).toBeNull()
    expect(server.calls.some((c) => c.path.includes("/authoring/"))).toBe(false)
  })

  it("explains why a location cannot be edited instead of hiding the reason", async () => {
    server.on("GET", "/campaigns/mundivita/authoring/locations/l1", {
      body: {
        ...AUTHORING_VIEW,
        canon_status: "proposed",
        available_actions: ["approve"],
        blocked_actions: [{ action: "update", reason: "review_in_progress" }],
      },
    })
    open("/app/mundivita/world/location/l1")

    expect(await screen.findByText(/Editing unavailable/)).toHaveTextContent("awaiting review")
    expect(screen.queryByRole("link", { name: "Edit location" })).toBeNull()
  })

  it("offers the World page's New location entry only to editors", async () => {
    const editor = open("/app/mundivita/world")
    expect(await screen.findByRole("link", { name: "New location" })).toHaveAttribute(
      "href",
      "/app/mundivita/world/location/new",
    )
    editor.unmount()

    open("/app/mundivita/world", ["campaign.view"])
    await screen.findByRole("heading", { level: 1, name: "World" })
    expect(screen.queryByRole("link", { name: "New location" })).toBeNull()
  })

  it("creates a draft, replaces history, and announces after the destination loads", async () => {
    server.on("POST", "/campaigns/mundivita/authoring/locations", {
      status: 201,
      body: { ...AUTHORING_VIEW, changed: true },
    })
    const { router } = open("/app/mundivita/world")
    fireEvent.click(await screen.findByRole("link", { name: "New location" }))
    await screen.findByRole("heading", { level: 1, name: "New location" })

    fireEvent.change(screen.getByRole("combobox", { name: /Category/ }), { target: { value: "region" } })
    fireEvent.change(screen.getByRole("textbox", { name: /Name/ }), { target: { value: "Hollow" } })
    fireEvent.click(screen.getByRole("button", { name: "Create location" }))

    expect(await screen.findByRole("heading", { level: 1, name: "Hollow" })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe("/app/mundivita/world/location/l1")
    await waitFor(() =>
      expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Location created as a draft"),
    )

    // Back skips the submitted form and lands on the World list.
    await act(async () => {
      await router.navigate(-1)
    })
    expect(router.state.location.pathname).toBe("/app/mundivita/world")
  })

  it("holds a dirty creation form when the user goes Back, and lets them stay", async () => {
    const { router } = open("/app/mundivita/world")
    fireEvent.click(await screen.findByRole("link", { name: "New location" }))
    await screen.findByRole("heading", { level: 1, name: "New location" })
    fireEvent.change(screen.getByRole("textbox", { name: /Name/ }), { target: { value: "Half" } })

    await act(async () => {
      void router.navigate(-1)
    })
    const dialog = await screen.findByRole("dialog", { name: "Discard this new location?" })
    fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
    expect(router.state.location.pathname).toBe("/app/mundivita/world/location/new")
    expect(screen.getByRole("textbox", { name: /Name/ })).toHaveValue("Half")
  })

  it("keeps the sidebar and hierarchy context on the authoring routes", async () => {
    open("/app/mundivita/world/location/new")
    await screen.findByRole("combobox", { name: /Category/ })
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument()
    expect(screen.getAllByRole("main")).toHaveLength(1)
  })
})
