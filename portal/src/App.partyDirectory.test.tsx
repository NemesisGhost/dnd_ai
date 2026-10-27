import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const party = (id: string, name: string) => ({
  party_id: id,
  name,
  description: `About ${name}`,
  lifecycle_status: "active",
  row_version: 2,
})

const ROSTER = "/campaigns/mundivita/parties/p1/roster"

let server: MockServer

beforeEach(() => {
  server = installCampaignShellMocks()
  server.on("GET", /\/campaigns\/mundivita\/parties(\?.*)?$/, {
    body: { can_create: false, items: [party("p1", "The Company"), party("p2", "Second Crew")] },
  })
  server.on("GET", ROSTER, {
    body: {
      party: party("p1", "The Company"),
      member_count: 2,
      members: [
        { character_id: "c1", character_name: "Aldric" },
        { character_id: "c2", character_name: "Bryn" },
      ],
    },
  })
})

describe("campaign party directory for a campaign.view user", () => {
  it("is reachable from the sidebar without a character or a party", async () => {
    // Start on a campaign page that needs no extra mocks; no character is selected anywhere.
    openApp("/app/mundivita/parties/p1", ["campaign.view"])
    const nav = await screen.findByRole("navigation", { name: "Main" })
    const link = within(nav).getByRole("link", { name: "Parties" })
    expect(link).toHaveAttribute("href", "/app/mundivita/parties")
    fireEvent.click(link)
    expect(await screen.findByRole("heading", { level: 1, name: "Parties" })).toBeInTheDocument()
    expect(await screen.findByText("The Company")).toBeInTheDocument()
    expect(screen.getByText("Second Crew")).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "New party" })).toBeNull()
  })

  it("opens a read-only roster with no management controls", async () => {
    openApp("/app/mundivita/parties", ["campaign.view"])
    const view = await screen.findByRole("link", { name: "View The Company" })
    expect(view).toHaveAttribute("href", "/app/mundivita/parties/p1")
    fireEvent.click(view)
    expect(await screen.findByRole("heading", { level: 1, name: "The Company" })).toBeInTheDocument()
    expect(await screen.findByRole("heading", { level: 2, name: "Current members (2)" })).toBeInTheDocument()
    expect(screen.getByText("Aldric")).toBeInTheDocument()
    const main = within(screen.getByRole("main"))
    expect(main.getByRole("link", { name: "Parties" })).toHaveAttribute("href", "/app/mundivita/parties")
    expect(main.queryByRole("button")).toBeNull()
    expect(screen.queryByText(/Add a member/)).toBeNull()
    expect(screen.queryByRole("button", { name: /End membership/ })).toBeNull()
    expect(server.calls.filter((c) => c.method !== "GET")).toEqual([])
    expect(server.calls.some((c) => c.path.endsWith("/members"))).toBe(false)
  })

  it("serves a direct link to the roster", async () => {
    openApp("/app/mundivita/parties/p1", ["campaign.view"])
    expect(await screen.findByText("Bryn")).toBeInTheDocument()
    await waitFor(() => expect(server.callsTo("GET", ROSTER)).toHaveLength(1))
  })

  it("shows an empty roster as such", async () => {
    server.on("GET", ROSTER, { body: { party: party("p1", "The Company"), member_count: 0, members: [] } })
    openApp("/app/mundivita/parties/p1", ["campaign.view"])
    expect(await screen.findByText("No current members.")).toBeInTheDocument()
  })

  it("keeps the management page and actions for editors", async () => {
    server.on("GET", "/campaigns/mundivita/parties/p1/members", {
      body: {
        party: { ...party("p1", "The Company"), available_actions: ["update", "archive"] },
        members: [],
      },
    })
    server.on("GET", /\/campaigns\/mundivita\/world-times/, { body: { items: [], next_cursor: null } })
    server.on("GET", "/campaigns/mundivita/calendars", { body: { calendars: [] } })
    openApp("/app/mundivita/parties/p1")
    expect(await screen.findByRole("heading", { name: "Add a member" })).toBeInTheDocument()
    expect(server.callsTo("GET", ROSTER)).toHaveLength(0)
  })
})
