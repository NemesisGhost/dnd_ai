import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"
import { useSessionBootstrap } from "./hooks/useSessionBootstrap"

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

type Status = "in_effect" | "not_started" | "ended" | "clock_unset"

// A row as the server sends it: `period_status` is the server's classification against the campaign
// clock, `is_current` is true only for `in_effect`, `left_at` is the stored end (null = open-ended).
const member = (
  id: string,
  name: string,
  current: boolean,
  status: Status = current ? "in_effect" : "ended",
  leftAt: string | null = current ? null : "Year 3",
) => ({
  party_membership_id: id,
  character_id: `c-${id}`,
  character_name: name,
  joined_at: "Year 1",
  left_at: leftAt,
  joined_reason: null,
  left_reason: null,
  is_current: status === "in_effect",
  period_status: status,
})

function listing(
  status = "active",
  members = [member("m1", "Aldric", true), member("m2", "Bryn", false)],
  clock: { as_of: string | null; clock_unset: boolean } = { as_of: "Year 2", clock_unset: false },
) {
  return {
    ...clock,
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
  server.on("GET", "/campaigns/mundivita/parties/p1/inventory", { body: { party_id: "p1", members: [] } })
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

  it("reports an ended membership whose roster re-read fails, holds further writes, and recovers by reading only", async () => {
    let state = listing()
    let rosterFails = false
    server.on("GET", MEMBERS, () => (rosterFails ? { status: 500, body: {} } : { body: state }))
    server.on("POST", `${MEMBERS}/m1/end`, () => {
      state = listing("active", [member("m1", "Aldric", false)])
      rosterFails = true
      return {
        body: { party_id: "p1", party_membership_id: "m1", row_version: 5, event_id: "ev", created: false, changed: true },
      }
    })
    openApp("/app/mundivita/parties/p1")
    fireEvent.click(await screen.findByRole("button", { name: "End membership of Aldric" }))
    const dialog = await screen.findByRole("dialog", { name: "End this membership?" })
    fireEvent.change(await within(dialog).findByRole("combobox", { name: /Ends at/ }), { target: { value: "t2" } })
    fireEvent.click(within(dialog).getByRole("button", { name: "End membership" }))

    expect(await screen.findByText(/Membership ended\. The latest party members could not be loaded/)).toBeInTheDocument()
    const live = screen.getByTestId("authoring-announcer")
    expect(live).toHaveTextContent("Saved, but the latest data could not be loaded.")
    expect(live).not.toHaveTextContent(/^Membership ended/)
    // The roster on screen is the older one, and it is not replaced by an error screen. It carries
    // party version 4, so nothing that sends a version is offered until it is read again.
    expect(screen.getByRole("button", { name: "End membership of Aldric" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "Add member" })).toBeDisabled()

    rosterFails = false
    fireEvent.click(screen.getByRole("button", { name: "Try again" }))
    await waitFor(() => expect(screen.queryByRole("button", { name: "End membership of Aldric" })).toBeNull())
    await waitFor(() => expect(live).toHaveTextContent("Membership ended"))
    expect(screen.queryByText(/could not be loaded/)).toBeNull()
    expect(server.callsTo("POST", `${MEMBERS}/m1/end`)).toHaveLength(1)
  })

  it("reports an added member whose roster re-read fails and never resends the add", async () => {
    let state = listing("active", [])
    let rosterFails = false
    server.on("GET", MEMBERS, () => (rosterFails ? { status: 500, body: {} } : { body: state }))
    server.on("POST", MEMBERS, () => {
      state = listing("active", [member("m9", "Cael", true)])
      rosterFails = true
      return {
        body: { party_id: "p1", party_membership_id: "m9", row_version: 5, event_id: "ev", created: true, changed: true },
      }
    })
    openApp("/app/mundivita/parties/p1")
    await screen.findByRole("heading", { level: 2, name: "Add a member" })
    fireEvent.focus(screen.getByRole("combobox", { name: "Character" }))
    fireEvent.click(await screen.findByRole("option", { name: /Cael/ }))
    fireEvent.change(await screen.findByRole("combobox", { name: /Joins at/ }), { target: { value: "t1" } })
    fireEvent.click(screen.getByRole("button", { name: "Add member" }))

    expect(await screen.findByText(/Member added\. The latest party members could not be loaded/)).toBeInTheDocument()
    expect(screen.getByTestId("authoring-announcer")).not.toHaveTextContent(/^Member added/)
    // Saved once; the form is cleared and held, so the same member cannot be added again from here.
    expect(screen.getByRole("button", { name: "Add member" })).toBeDisabled()
    expect(server.callsTo("POST", MEMBERS)).toHaveLength(1)

    rosterFails = false
    fireEvent.click(screen.getByRole("button", { name: "Try again" }))
    expect(await screen.findByRole("button", { name: "End membership of Cael" })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Member added"))
    expect(server.callsTo("POST", MEMBERS)).toHaveLength(1)
  })

  it("retries an add whose answer was lost with the same body and key, and then reports the failed roster read without a third send", async () => {
    let state = listing("active", [])
    let rosterFails = false
    let posts = 0
    server.on("GET", MEMBERS, () => (rosterFails ? { status: 500, body: {} } : { body: state }))
    server.on("POST", MEMBERS, () => {
      posts += 1
      if (posts === 1) return { networkError: true }
      state = listing("active", [member("m9", "Cael", true)])
      rosterFails = true
      return {
        body: { party_id: "p1", party_membership_id: "m9", row_version: 5, event_id: "ev", created: true, changed: true },
      }
    })
    openApp("/app/mundivita/parties/p1")
    await screen.findByRole("heading", { level: 2, name: "Add a member" })
    fireEvent.focus(screen.getByRole("combobox", { name: "Character" }))
    fireEvent.click(await screen.findByRole("option", { name: /Cael/ }))
    fireEvent.change(await screen.findByRole("combobox", { name: /Joins at/ }), { target: { value: "t1" } })
    fireEvent.click(screen.getByRole("button", { name: "Add member" }))

    // The answer was lost: nothing is claimed, the input is kept, and Retry sends the same request.
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }))
    expect(await screen.findByText(/Member added\. The latest party members could not be loaded/)).toBeInTheDocument()
    const sent = server.callsTo("POST", MEMBERS)
    expect(sent).toHaveLength(2)
    expect(sent[1]!.body).toEqual(sent[0]!.body)
    expect(sent[1]!.headers["Idempotency-Key"]).toBe(sent[0]!.headers["Idempotency-Key"])
    expect(screen.getByRole("button", { name: "Add member" })).toBeDisabled()
    expect(screen.getByTestId("authoring-announcer")).not.toHaveTextContent(/^Member added/)
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
    server.on("GET", "/campaigns/mundivita/parties/p1/roster", {
      status: 404,
      body: { error: { code: "not_found", message: "m", correlation_id: "c" } },
    })
    openApp("/app/mundivita/parties/p1", ["campaign.view"])
    expect(await screen.findByRole("alert")).toHaveTextContent("does not exist, or you do not have access")
  })
})

describe("party members page: recording a time in the picker", () => {
    // Record a narrative time ("after Year 1") through the picker's dialog.
    async function recordThroughDialog() {
        fireEvent.click(await screen.findByRole("button", { name: "Record a new time" }))
        const dialog = await screen.findByRole("dialog", { name: "Record a world time" })
        fireEvent.change(within(dialog).getByRole("textbox", { name: /Describe this moment/ }), { target: { value: "Dawn" } })
        fireEvent.change(within(dialog).getByRole("combobox", { name: /Comes after/ }), { target: { value: "t1" } })
        fireEvent.click(within(dialog).getByRole("button", { name: "Record time" }))
        await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    }

    it("keeps the add form's character, chooses the recorded time, and adds nobody", async () => {
        let recorded = false
        server.on("GET", MEMBERS, { body: listing("active", []) })
        server.on("GET", /\/campaigns\/mundivita\/world-times/, () => ({
            body: { items: recorded ? [TIME("t9", "Dawn"), TIME("t1", "Year 1")] : [TIME("t1", "Year 1")], next_cursor: null },
        }))
        server.on("POST", /\/campaigns\/mundivita\/world-times/, () => {
            recorded = true
            return { status: 201, body: { world_time_id: "t9", created: true, changed: true } }
        })
        openApp("/app/mundivita/parties/p1")
        fireEvent.click(await screen.findByRole("button", { name: "Add member" }))
        fireEvent.focus(screen.getByRole("combobox", { name: "Character" }))
        fireEvent.click(await screen.findByRole("option", { name: /Cael/ }))
        await recordThroughDialog()
        await waitFor(() => expect(screen.getByRole("combobox", { name: /Joins at/ })).toHaveValue("t9"))
        expect(screen.getByRole("combobox", { name: "Character" })).toHaveValue("Cael")
        expect(server.callsTo("POST", MEMBERS)).toHaveLength(0)
    })
})

describe("party members page: effective-time groups", () => {
  const CLOCK_LINK = { name: /Set the campaign time on Campaign Home/ }

  it("groups by the server's classification: current, upcoming and history", async () => {
    server.on("GET", MEMBERS, {
      body: listing("active", [
        member("m1", "Aldric", true),
        member("m2", "Bryn", false),
        // Stored open-ended, but not started at the campaign clock: upcoming, never history.
        member("m3", "Cael", false, "not_started", null),
        // A finite membership containing the clock: current, with its stored end shown, not endable.
        member("m4", "Dara", true, "in_effect", "Year 5"),
      ]),
    })
    openApp("/app/mundivita/parties/p1")
    const current = await screen.findByRole("table", { name: "Current members" })
    expect(within(current).getByRole("rowheader", { name: "Aldric" })).toBeInTheDocument()
    expect(within(current).getByRole("rowheader", { name: "Dara" })).toBeInTheDocument()
    expect(within(current).getByText("Year 5")).toBeInTheDocument()
    expect(within(current).queryByRole("rowheader", { name: "Cael" })).toBeNull()
    const upcoming = screen.getByRole("table", { name: "Upcoming members" })
    expect(within(upcoming).getByRole("rowheader", { name: "Cael" })).toBeInTheDocument()
    const past = screen.getByRole("table", { name: "Past members" })
    expect(within(past).getByRole("rowheader", { name: "Bryn" })).toBeInTheDocument()
    expect(within(past).queryByRole("rowheader", { name: "Cael" })).toBeNull()
    // The command ends only a membership with no recorded end: Aldric and the upcoming Cael, not
    // the finite Dara or the ended Bryn.
    expect(screen.getByRole("button", { name: "End membership of Aldric" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "End membership of Cael" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "End membership of Dara" })).toBeNull()
    expect(screen.queryByRole("button", { name: "End membership of Bryn" })).toBeNull()
    expect(screen.queryByText(/campaign time has not been set/)).toBeNull()
  })

  it("lists every membership as undetermined, never as history or upcoming, when the clock is unset", async () => {
    server.on("GET", MEMBERS, {
      body: listing(
        "active",
        [
          member("m1", "Aldric", false, "clock_unset", null),
          member("m2", "Bryn", false, "clock_unset", "Year 3"),
        ],
        { as_of: null, clock_unset: true },
      ),
    })
    openApp("/app/mundivita/parties/p1")
    const all = await screen.findByRole("table", { name: "Members (current status unknown)" })
    expect(within(all).getByRole("rowheader", { name: "Aldric" })).toBeInTheDocument()
    expect(within(all).getByRole("rowheader", { name: "Bryn" })).toBeInTheDocument()
    expect(screen.getByText(/Party membership cannot be determined|Current membership cannot be determined/)).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "History" })).toBeNull()
    expect(screen.queryByRole("heading", { name: "Upcoming members" })).toBeNull()
    expect(screen.queryByRole("heading", { name: "Current members" })).toBeNull()
    expect(screen.queryByText("No current members.")).toBeNull()
    // The GM may still manage: the open-ended one can be ended, the finite one cannot.
    expect(screen.getByRole("button", { name: "End membership of Aldric" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "End membership of Bryn" })).toBeNull()
    // The clock-setup route is offered to a user who can edit canon.
    expect(screen.getByRole("link", CLOCK_LINK)).toHaveAttribute("href", "/app/mundivita")
  })

  it("says an unset-clock party with no memberships has none recorded, not that nobody is current", async () => {
    server.on("GET", MEMBERS, { body: listing("active", [], { as_of: null, clock_unset: true }) })
    server.on("GET", "/campaigns/mundivita/parties/p1/inventory", {
      body: { party_id: "p1", as_of: null, clock_unset: true, members: [] },
    })
    openApp("/app/mundivita/parties/p1")
    expect(await screen.findByText("No memberships are recorded for this party.")).toBeInTheDocument()
    expect(screen.queryByText("No current members.")).toBeNull()
  })

  it("ends an upcoming open-ended membership with the same command and party version", async () => {
    server.on("GET", MEMBERS, {
      body: listing("active", [member("m3", "Cael", false, "not_started", null)]),
    })
    server.on("POST", `${MEMBERS}/m3/end`, {
      body: { party_id: "p1", party_membership_id: "m3", row_version: 5, event_id: "ev", created: false, changed: true },
    })
    openApp("/app/mundivita/parties/p1")
    fireEvent.click(await screen.findByRole("button", { name: "End membership of Cael" }))
    const dialog = await screen.findByRole("dialog", { name: "End this membership?" })
    fireEvent.change(await within(dialog).findByRole("combobox", { name: /Ends at/ }), { target: { value: "t2" } })
    fireEvent.click(within(dialog).getByRole("button", { name: "End membership" }))
    await waitFor(() => expect(server.callsTo("POST", `${MEMBERS}/m3/end`)).toHaveLength(1))
    expect(server.callsTo("POST", `${MEMBERS}/m3/end`)[0]!.body).toMatchObject({
      effective_to_world_time_id: "t2",
      expected_party_row_version: 4,
    })
  })

  it("keeps the add form and its draft when the clock is unset", async () => {
    server.on("GET", MEMBERS, { body: listing("active", [], { as_of: null, clock_unset: true }) })
    openApp("/app/mundivita/parties/p1")
    fireEvent.click(await screen.findByRole("button", { name: "Add member" }))
    fireEvent.focus(screen.getByRole("combobox", { name: "Character" }))
    fireEvent.click(await screen.findByRole("option", { name: /Cael/ }))
    expect(screen.getByRole("combobox", { name: "Character" })).toHaveValue("Cael")
    expect(server.callsTo("POST", MEMBERS)).toHaveLength(0)
  })

  it("shows the inventory panel's undetermined notice instead of 'No current members' when the clock is unset", async () => {
    server.on("GET", MEMBERS, { body: listing("active", [], { as_of: null, clock_unset: true }) })
    server.on("GET", "/campaigns/mundivita/parties/p1/inventory", {
      body: { party_id: "p1", as_of: null, clock_unset: true, members: [] },
    })
    openApp("/app/mundivita/parties/p1")
    const heading = await screen.findByRole("heading", { name: "Party inventory" })
    const panel = heading.closest("section")!
    expect(within(panel).getByText(/cannot be determined because the campaign time has not been set/)).toBeInTheDocument()
    expect(within(panel).queryByText("No current members.")).toBeNull()
  })
})

describe("party members page: membership end wording", () => {
  it("does not call a future end 'Left' for a current finite membership, and keeps 'Left' for history", async () => {
    server.on("GET", MEMBERS, {
      body: listing("active", [
        member("m4", "Dara", true, "in_effect", "Year 5"),
        member("m3", "Cael", false, "not_started", "Year 9"),
        member("m2", "Bryn", false),
      ]),
    })
    openApp("/app/mundivita/parties/p1")
    const current = await screen.findByRole("table", { name: "Current members" })
    expect(within(current).getByRole("columnheader", { name: "Membership end" })).toBeInTheDocument()
    expect(within(current).queryByRole("columnheader", { name: "Left" })).toBeNull()
    const upcoming = screen.getByRole("table", { name: "Upcoming members" })
    expect(within(upcoming).getByRole("columnheader", { name: "Membership end" })).toBeInTheDocument()
    const past = screen.getByRole("table", { name: "Past members" })
    expect(within(past).getByRole("columnheader", { name: "Left" })).toBeInTheDocument()
  })

  it("uses the neutral heading for undetermined memberships", async () => {
    server.on("GET", MEMBERS, {
      body: listing("active", [member("m2", "Bryn", false, "clock_unset", "Year 3")], { as_of: null, clock_unset: true }),
    })
    openApp("/app/mundivita/parties/p1")
    const all = await screen.findByRole("table", { name: "Members (current status unknown)" })
    expect(within(all).getByRole("columnheader", { name: "Membership end" })).toBeInTheDocument()
    expect(within(all).queryByRole("columnheader", { name: "Left" })).toBeNull()
  })
})

describe("party members page: eligibility refresh after a confirmed membership change", () => {
  const refreshOf = () => {
    const results = vi.mocked(useSessionBootstrap).mock.results
    return results[results.length - 1]!.value.refresh as ReturnType<typeof vi.fn>
  }

  async function endAldric() {
    fireEvent.click(await screen.findByRole("button", { name: "End membership of Aldric" }))
    const dialog = await screen.findByRole("dialog", { name: "End this membership?" })
    fireEvent.change(await within(dialog).findByRole("combobox", { name: /Ends at/ }), { target: { value: "t2" } })
    fireEvent.click(within(dialog).getByRole("button", { name: "End membership" }))
  }

  it("refreshes once after a confirmed end, even when the roster re-read fails, and never resends the end", async () => {
    let rosterFails = false
    server.on("GET", MEMBERS, () => (rosterFails ? { status: 500, body: {} } : { body: listing() }))
    server.on("POST", `${MEMBERS}/m1/end`, () => {
      rosterFails = true
      return {
        body: { party_id: "p1", party_membership_id: "m1", row_version: 5, event_id: "ev", created: false, changed: true },
      }
    })
    openApp("/app/mundivita/parties/p1")
    await endAldric()
    expect(await screen.findByText(/Membership ended\. The latest party members could not be loaded/)).toBeInTheDocument()
    expect(refreshOf()).toHaveBeenCalledTimes(1)
    expect(server.callsTo("POST", `${MEMBERS}/m1/end`)).toHaveLength(1)
  })

  it("does not refresh after an end that failed", async () => {
    server.on("GET", MEMBERS, { body: listing() })
    server.on("POST", `${MEMBERS}/m1/end`, {
      status: 409,
      body: { error: { code: "party_membership_not_open", message: "m", correlation_id: "c" } },
    })
    openApp("/app/mundivita/parties/p1")
    await endAldric()
    expect(await screen.findByText("That membership has already ended.")).toBeInTheDocument()
    expect(refreshOf()).not.toHaveBeenCalled()
  })

  it("refreshes once after a confirmed add and does not resend it", async () => {
    server.on("GET", MEMBERS, { body: listing("active", []) })
    server.on("POST", MEMBERS, {
      body: { party_id: "p1", party_membership_id: "m9", row_version: 5, event_id: "ev", created: true, changed: true },
    })
    openApp("/app/mundivita/parties/p1")
    fireEvent.click(await screen.findByRole("button", { name: "Add member" }))
    fireEvent.focus(screen.getByRole("combobox", { name: "Character" }))
    fireEvent.click(await screen.findByRole("option", { name: /Cael/ }))
    fireEvent.change(await screen.findByRole("combobox", { name: /Joins at/ }), { target: { value: "t1" } })
    fireEvent.click(screen.getAllByRole("button", { name: "Add member" }).at(-1)!)
    await waitFor(() => expect(server.callsTo("POST", MEMBERS)).toHaveLength(1))
    await waitFor(() => expect(refreshOf()).toHaveBeenCalledTimes(1))
    expect(server.callsTo("POST", MEMBERS)).toHaveLength(1)
  })
})
