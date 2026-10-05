import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const MEMBERS = "/campaigns/mundivita/parties/p1/members"

const TIME = (id: string, display: string) => ({
  world_time_id: id,
  calendar_id: null,
  year: null,
  month_number: null,
  day: null,
  hour: null,
  minute: null,
  label: display,
  precision: "narrative",
  sort_key: 1,
  display,
})

const member = (id: string, name: string, current: boolean) => ({
  party_membership_id: id,
  character_id: `c-${id}`,
  character_name: name,
  joined_at: "Year 1",
  left_at: current ? null : "Year 3",
  joined_reason: null,
  left_reason: null,
  is_current: current,
})

function listing(status = "active", members = [member("m1", "Aldric", true), member("m2", "Bryn", false)]) {
  return {
    party: {
      party_id: "p1",
      name: "The Company",
      description: null,
      lifecycle_status: status,
      row_version: 4,
      available_actions: status === "active" ? ["update", "archive"] : ["restore"],
    },
    members,
  }
}

let server: MockServer

beforeEach(() => {
  server = installCampaignShellMocks()
  server.on("GET", /\/campaigns\/mundivita\/world-times/, {
    body: { items: [TIME("t2", "Year 2"), TIME("t1", "Year 1")], next_cursor: null },
  })
  server.on("GET", "/campaigns/mundivita/calendars", { body: { calendars: [] } })
  server.on("GET", /\/campaigns\/mundivita\/world\/search/, {
    body: {
      items: [
        {
          entity_id: "ch1",
          category: "character",
          entity_type_code: "player_character",
          name: "Cael",
          summary: null,
        },
      ],
      next_cursor: null,
    },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("party members page", () => {
  it("shows current members and history in tables", async () => {
    server.on("GET", MEMBERS, { body: listing() })
    openApp("/app/mundivita/parties/p1")
    expect(await screen.findByRole("heading", { level: 1, name: "The Company" })).toBeInTheDocument()
    expect(screen.getAllByRole("main")).toHaveLength(1)
    const current = await screen.findByRole("table", { name: "Current members" })
    expect(within(current).getByRole("rowheader", { name: "Aldric" })).toBeInTheDocument()
    const past = screen.getByRole("table", { name: "Past members" })
    expect(within(past).getByRole("rowheader", { name: "Bryn" })).toBeInTheDocument()
    expect(within(past).getByText("Year 3")).toBeInTheDocument()
  })

  it("ends a membership at a chosen time with the party version it saw", async () => {
    let state = listing()
    server.on("GET", MEMBERS, () => ({ body: state }))
    server.on("POST", `${MEMBERS}/m1/end`, () => {
      state = listing("active", [member("m1", "Aldric", false)])
      return {
        body: {
          party_id: "p1",
          party_membership_id: "m1",
          row_version: 5,
          event_id: "ev",
          created: false,
          changed: true,
        },
      }
    })
    openApp("/app/mundivita/parties/p1")
    fireEvent.click(await screen.findByRole("button", { name: "End membership of Aldric" }))
    const dialog = await screen.findByRole("dialog", { name: "End this membership?" })
    // Nothing is sent without a time.
    fireEvent.click(within(dialog).getByRole("button", { name: "End membership" }))
    expect(await within(dialog).findByText("Choose when the membership ends.")).toBeInTheDocument()
    expect(server.callsTo("POST", /./)).toHaveLength(0)
    fireEvent.change(await within(dialog).findByRole("combobox", { name: /Ends at/ }), {
      target: { value: "t2" },
    })
    fireEvent.click(within(dialog).getByRole("button", { name: "End membership" }))
    await waitFor(() => expect(server.callsTo("POST", `${MEMBERS}/m1/end`)).toHaveLength(1))
    const [call] = server.callsTo("POST", `${MEMBERS}/m1/end`)
    expect(call!.body).toEqual({
      effective_to_world_time_id: "t2",
      expected_party_row_version: 4,
      reason: null,
    })
    expect(call!.headers["Idempotency-Key"]).toBeTruthy()
    await waitFor(() =>
      expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Membership ended"),
    )
  })

  it("adds a member after choosing a character and a time, and explains an overlap", async () => {
    server.on("GET", MEMBERS, { body: listing("active", []) })
    server.on("POST", MEMBERS, {
      status: 409,
      body: { error: { code: "party_membership_overlap", message: "m", correlation_id: "c" } },
    })
    openApp("/app/mundivita/parties/p1")
    fireEvent.click(await screen.findByRole("button", { name: "Add member" }))
    expect((await screen.findAllByText("Choose a character.")).length).toBeGreaterThan(0)
    expect(server.callsTo("POST", /./)).toHaveLength(0)

    fireEvent.focus(screen.getByRole("combobox", { name: "Character" }))
    fireEvent.click(await screen.findByRole("option", { name: /Cael/ }))
    fireEvent.change(await screen.findByRole("combobox", { name: /Joins at/ }), {
      target: { value: "t1" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Add member" }))
    await waitFor(() => expect(server.callsTo("POST", MEMBERS)).toHaveLength(1))
    expect(server.callsTo("POST", MEMBERS)[0]!.body).toEqual({
      character_id: "ch1",
      effective_from_world_time_id: "t1",
      expected_party_row_version: 4,
      reason: null,
    })
    expect(await screen.findByRole("alert")).toHaveTextContent("already a member")
  })

  it("offers no add form on an archived party", async () => {
    server.on("GET", MEMBERS, { body: listing("archived") })
    openApp("/app/mundivita/parties/p1")
    expect(await screen.findByText(/This party is archived/)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Add member" })).toBeNull()
    expect(screen.getByRole("button", { name: "End membership of Aldric" })).toBeInTheDocument()
  })

  it("says the party is unavailable to someone without access", async () => {
    server.on("GET", MEMBERS, {
      status: 403,
      body: { error: { code: "forbidden", message: "m", correlation_id: "c" } },
    })
    openApp("/app/mundivita/parties/p1", ["campaign.view"])
    expect(await screen.findByRole("alert")).toHaveTextContent("does not exist, or you do not have access")
  })
})
