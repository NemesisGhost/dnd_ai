import { fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const ORG_OPTIONS = {
  can_create: true,
  kinds: [
    { code: "government", label: "Government", needs_religion: false, fields: [] },
  ],
  limits: {
    name_max_length: 200,
    summary_max_length: 4000,
    description_max_length: 4000,
    change_note_max_length: 1000,
  },
  generic_types: [],
}
const ORG_VIEW = {
  organization_id: "o1",
  name: "The Crown",
  summary: null,
  kind: { code: "government", label: "Government" },
  organization_type: "government",
  public_description: null,
  internal_description: null,
  parent: null,
  headquarters: null,
  religion: null,
  typed: {},
  canon_status: "draft",
  lifecycle_status: "active",
  row_version: 2,
  available_actions: ["update"],
  blocked_actions: [],
  field_locks: [],
}
const ORG_DETAIL = {
  organization_id: "o1",
  name: "The Crown",
  summary: null,
  kind_code: "government",
  organization_type_code: "government",
  public_description: "Rules the realm.",
  parent: null,
  headquarters: null,
  religion: null,
  status_code: null,
  canon_status: "draft",
  lifecycle_status: "active",
}
const RELIGION_OPTIONS = {
  can_create: true,
  limits: {
    name_max_length: 200,
    summary_max_length: 4000,
    pantheon_max_length: 4000,
    change_note_max_length: 1000,
  },
}
const RELIGION_VIEW = {
  religion_id: "r1",
  name: "Old Way",
  summary: null,
  pantheon_structure: null,
  canon_status: "draft",
  lifecycle_status: "active",
  row_version: 2,
  available_actions: ["update"],
  blocked_actions: [],
  field_locks: [],
}
const RELIGION_DETAIL = {
  religion_id: "r1",
  name: "Old Way",
  summary: null,
  pantheon_structure: null,
  serving_organization_ids: [],
}

let server: MockServer

beforeEach(() => {
  server = installCampaignShellMocks()
  server.on("GET", "/campaigns/mundivita/authoring/organizations/options", { body: ORG_OPTIONS })
  server.on("GET", "/campaigns/mundivita/authoring/organizations/o1", { body: ORG_VIEW })
  server.on("GET", "/campaigns/mundivita/world/organizations/o1", { body: ORG_DETAIL })
  server.on("GET", "/campaigns/mundivita/authoring/religions/options", { body: RELIGION_OPTIONS })
  server.on("GET", "/campaigns/mundivita/authoring/religions/r1", { body: RELIGION_VIEW })
  server.on("GET", "/campaigns/mundivita/world/religions/r1", { body: RELIGION_DETAIL })
  server.on("GET", /\/entities\/(o1|r1)\/lifecycle$/, {
    body: {
      entity_id: "o1",
      entity_type_code: "government",
      canonical_name: "x",
      canon_status: "draft",
      lifecycle_status: "active",
      row_version: 2,
      lifecycle_managed: true,
      superseded_by: null,
      available_actions: ["archive"],
      blocked_actions: [],
    },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("organization and religion authoring routes", () => {
  it.each([
    ["/app/mundivita/world/organization/new", "New organization"],
    ["/app/mundivita/world/organization/o1/edit", "Edit organization"],
    ["/app/mundivita/world/religion/new", "New religion"],
    ["/app/mundivita/world/religion/r1/edit", "Edit religion"],
  ])("%s loads directly with one main and one h1", async (path, heading) => {
    openApp(path)
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument()
    expect(screen.getAllByRole("main")).toHaveLength(1)
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
    expect(screen.queryByText(/Unexpected Application Error/i)).toBeNull()
    expect(server.calls.some((c) => c.path.endsWith("/world/organizations/new"))).toBe(false)
    expect(server.calls.some((c) => c.path.endsWith("/world/religions/new"))).toBe(false)
  })

  it("opens an organization detail instead of failing closed, with an Edit link for editors", async () => {
    openApp("/app/mundivita/world/organization/o1")
    expect(await screen.findByRole("heading", { level: 1, name: "The Crown" })).toBeInTheDocument()
    expect(await screen.findByRole("link", { name: "Edit organization" })).toHaveAttribute(
      "href",
      "/app/mundivita/world/organization/o1/edit",
    )
  })

  it("keeps a player off the authoring reads", async () => {
    openApp("/app/mundivita/world/organization/o1", ["campaign.view"])
    await screen.findByRole("heading", { level: 1, name: "The Crown" })
    expect(screen.queryByRole("link", { name: "Edit organization" })).toBeNull()
    expect(server.calls.some((c) => c.path.includes("/authoring/"))).toBe(false)
  })

  it("offers every creation entry point to editors only", async () => {
    const editor = openApp("/app/mundivita/world")
    for (const name of ["New location", "New organization", "New religion"]) {
      expect(await screen.findByRole("link", { name })).toBeInTheDocument()
    }
    editor.unmount()
    openApp("/app/mundivita/world", ["campaign.view"])
    await screen.findByRole("heading", { level: 1, name: "Campaign World" })
    for (const name of ["New location", "New organization", "New religion"]) {
      expect(screen.queryByRole("link", { name })).toBeNull()
    }
  })

  it("creates an organization and lands on its detail, announced", async () => {
    server.on("POST", "/campaigns/mundivita/authoring/organizations", {
      status: 201,
      body: { ...ORG_VIEW, changed: true },
    })
    const { router } = openApp("/app/mundivita/world/organization/new")
    fireEvent.change(await screen.findByRole("combobox", { name: /^Kind/ }), {
      target: { value: "government" },
    })
    fireEvent.change(screen.getByRole("textbox", { name: /Name/ }), { target: { value: "The Crown" } })
    fireEvent.click(screen.getByRole("button", { name: "Create organization" }))

    expect(await screen.findByRole("heading", { level: 1, name: "The Crown" })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe("/app/mundivita/world/organization/o1")
    await waitFor(() =>
      expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Organization created as a draft"),
    )
  })
})
