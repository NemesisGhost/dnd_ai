import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const S = "/campaigns/mundivita/sessions/s1"

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

function session(extra: Record<string, unknown> = {}) {
  return {
    session_id: "s1",
    session_number: 1,
    title: "The Hollow Road",
    status_code: "active",
    started_at: null,
    ended_at: null,
    summary: null,
    start_world_time_id: null,
    end_world_time_id: null,
    scheduled_for: null,
    play_status: "scheduled",
    row_version: 3,
    available_actions: ["update", "start", "manage_participants", "archive"],
    participants: [],
    events: [],
    ...extra,
  }
}

const playing = (extra: Record<string, unknown> = {}) =>
  session({
    started_at: "2026-10-12T19:30:00Z",
    play_status: "in_progress",
    available_actions: ["update", "manage_participants", "log", "end"],
    ...extra,
  })

let server: MockServer

beforeEach(() => {
  server = installCampaignShellMocks()
  server.on("GET", "/campaigns/mundivita/clock", {
    body: { current: { world_time_id: "t1", display: "Year 1" }, row_version: 1, inherited: false, last_event_id: "e1" },
  })
  server.on("GET", /\/campaigns\/mundivita\/world-times/, {
    body: { items: [TIME("t2", "Year 2"), TIME("t1", "Year 1")], next_cursor: null },
  })
  server.on("GET", "/campaigns/mundivita/calendars", { body: { calendars: [] } })
  server.on("GET", /\/campaigns\/mundivita\/world\/search/, {
    body: {
      items: [
        { entity_id: "c1", category: "character", entity_type_code: "player_character", name: "Cael", summary: null },
      ],
      next_cursor: null,
    },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("session run page", () => {
  it("loads with one main and one h1 and shows the status and the clock", async () => {
    server.on("GET", S, { body: session() })
    openApp("/app/mundivita/sessions/s1/run")
    expect(
      await screen.findByRole("heading", { level: 1, name: "Run: The Hollow Road" }),
    ).toBeInTheDocument()
    expect(screen.getAllByRole("main")).toHaveLength(1)
    expect(screen.getByText("Scheduled")).toBeInTheDocument()
    expect(await screen.findByText("Now: Year 1")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "End session" })).toBeNull()
  })

  it("starts with the version it saw, defaulting to the campaign time", async () => {
    let state = session()
    server.on("GET", S, () => ({ body: state }))
    server.on("POST", `${S}/start`, () => {
      state = playing({ row_version: 4 })
      return { body: { session_id: "s1", row_version: 4, changed: true } }
    })
    openApp("/app/mundivita/sessions/s1/run")
    fireEvent.click(await screen.findByRole("button", { name: "Start session" }))
    await waitFor(() => expect(server.callsTo("POST", `${S}/start`)).toHaveLength(1))
    const [call] = server.callsTo("POST", `${S}/start`)
    expect(call!.body).toEqual({ expected_row_version: 3, start_world_time_id: null })
    expect(call!.headers["Idempotency-Key"]).toBeTruthy()
    expect(await screen.findByText("In progress")).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Session started"),
    )
  })

  it("explains why a start was refused", async () => {
    server.on("GET", S, { body: session() })
    server.on("POST", `${S}/start`, {
      status: 409,
      body: { error: { code: "another_session_in_progress", message: "m", correlation_id: "c" } },
    })
    openApp("/app/mundivita/sessions/s1/run")
    fireEvent.click(await screen.findByRole("button", { name: "Start session" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("Another session of this campaign")
  })

  it("adds a participant, validating the choice first, and removes one", async () => {
    server.on("GET", S, {
      body: session({
        participants: [
          { session_participant_id: "p1", character_id: "c9", character_name: "Mira", participation_role: "npc", added_at: "2026-10-12T19:00:00Z", removed_at: null },
        ],
      }),
    })
    server.on("POST", `${S}/participants`, {
      status: 201,
      body: { session_id: "s1", row_version: 4, changed: true, session_participant_id: "p2" },
    })
    server.on("POST", `${S}/participants/p1/remove`, {
      body: { session_id: "s1", row_version: 4, changed: true, session_participant_id: "p1" },
    })
    openApp("/app/mundivita/sessions/s1/run")
    expect(await screen.findByText(/Mira \(npc\)/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Add participant" }))
    expect((await screen.findAllByText("Choose a character.")).length).toBeGreaterThan(0)
    expect(server.callsTo("POST", /./)).toHaveLength(0)

    fireEvent.focus(screen.getByRole("combobox", { name: "Character" }))
    fireEvent.click(await screen.findByRole("option", { name: /Cael/ }))
    fireEvent.change(screen.getByRole("combobox", { name: "Role" }), { target: { value: "player_character" } })
    fireEvent.click(screen.getByRole("button", { name: "Add participant" }))
    await waitFor(() => expect(server.callsTo("POST", `${S}/participants`)).toHaveLength(1))
    expect(server.callsTo("POST", `${S}/participants`)[0]!.body).toEqual({
      expected_row_version: 3,
      character_id: "c1",
      participation_role: "player_character",
    })

    fireEvent.click(screen.getByRole("button", { name: "Remove Mira" }))
    await waitFor(() => expect(server.callsTo("POST", `${S}/participants/p1/remove`)).toHaveLength(1))
  })

  it("records a log entry with GM notes and lists the entries", async () => {
    let state = playing()
    server.on("GET", S, () => ({ body: state }))
    server.on("POST", `${S}/log`, () => {
      state = playing({
        events: [
          { event_id: "ev1", name: "The party enters the crypt.", summary: null, event_type_code: "session_narrative", event_status_code: "recorded", world_time_id: "t1", details: "The door is trapped" },
        ],
      })
      return { status: 201, body: { session_id: "s1", row_version: 3, changed: true, event_id: "ev1" } }
    })
    openApp("/app/mundivita/sessions/s1/run")
    fireEvent.click(await screen.findByRole("button", { name: "Record entry" }))
    expect((await screen.findAllByText("Enter what happened.")).length).toBeGreaterThan(0)
    expect(server.callsTo("POST", /./)).toHaveLength(0)
    fireEvent.change(screen.getByLabelText(/What happened/), { target: { value: "The party enters the crypt." } })
    fireEvent.change(screen.getByLabelText(/GM notes/), { target: { value: "The door is trapped" } })
    fireEvent.click(screen.getByRole("button", { name: "Record entry" }))
    await waitFor(() => expect(server.callsTo("POST", `${S}/log`)).toHaveLength(1))
    expect(server.callsTo("POST", `${S}/log`)[0]!.body).toEqual({
      entry: "The party enters the crypt.",
      details: "The door is trapped",
      world_time_id: null,
    })
    const log = await screen.findByRole("list", { name: "Session log" })
    expect(within(log).getByText("The party enters the crypt.")).toBeInTheDocument()
    expect(within(log).getByText(/GM notes: The door is trapped/)).toBeInTheDocument()
  })

  it("ends after a confirmation with the recap", async () => {
    server.on("GET", S, { body: playing() })
    server.on("POST", `${S}/end`, {
      body: { session_id: "s1", row_version: 4, changed: true },
    })
    openApp("/app/mundivita/sessions/s1/run")
    fireEvent.click(await screen.findByRole("button", { name: "End session" }))
    expect(server.callsTo("POST", /./)).toHaveLength(0)
    const dialog = await screen.findByRole("dialog", { name: "End this session?" })
    fireEvent.change(within(dialog).getByLabelText(/Recap/), { target: { value: "They survived." } })
    fireEvent.click(within(dialog).getByRole("button", { name: "End session" }))
    await waitFor(() => expect(server.callsTo("POST", `${S}/end`)).toHaveLength(1))
    expect(server.callsTo("POST", `${S}/end`)[0]!.body).toEqual({
      expected_row_version: 3,
      end_world_time_id: null,
      summary: "They survived.",
    })
  })

  it("shows a finished session as completed with no controls", async () => {
    server.on("GET", S, {
      body: session({ play_status: "completed", ended_at: "2026-10-12T22:00:00Z", available_actions: ["update", "archive"] }),
    })
    openApp("/app/mundivita/sessions/s1/run")
    expect(await screen.findByText("Completed")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Start session" })).toBeNull()
    expect(screen.queryByRole("button", { name: "End session" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Record entry" })).toBeNull()
  })

  describe("participants", () => {
    const person = (id: string, characterId: string, name: string, role: string, removedAt: string | null = null) => ({
      session_participant_id: id,
      character_id: characterId,
      character_name: name,
      participation_role: role,
      added_at: "2026-10-12T19:00:00Z",
      removed_at: removedAt,
    })
    const CAEL = person("p2", "c1", "Cael", "player_character")
    const DUPLICATE = {
      status: 409,
      body: { error: { code: "session_participant_exists", message: "m", correlation_id: "c" } },
    }

    async function pickCael() {
      fireEvent.focus(await screen.findByRole("combobox", { name: "Character" }))
      fireEvent.click(await screen.findByRole("option", { name: /Cael/ }))
    }

    it("lists active participants with roles on load and the removed ones separately", async () => {
      server.on("GET", S, {
        body: session({
          participants: [
            person("p1", "c9", "Mira", "npc"),
            person("p3", "c8", "Borin", "guest", "2026-10-12T20:00:00Z"),
          ],
        }),
      })
      openApp("/app/mundivita/sessions/s1/run")
      expect(await screen.findByText(/Mira \(npc\)/)).toBeInTheDocument()
      expect(screen.getByText("Left: Borin")).toBeInTheDocument()
      expect(screen.queryByRole("button", { name: "Remove Borin" })).toBeNull()
    })

    it("shows the roster, without management controls, when participants cannot be edited", async () => {
      server.on("GET", S, {
        body: session({
          play_status: "completed",
          ended_at: "2026-10-12T22:00:00Z",
          available_actions: ["update", "archive"],
          participants: [person("p1", "c9", "Mira", "npc")],
        }),
      })
      openApp("/app/mundivita/sessions/s1/run")
      expect(await screen.findByText(/Mira \(npc\)/)).toBeInTheDocument()
      expect(screen.queryByRole("button", { name: "Remove Mira" })).toBeNull()
      expect(screen.queryByRole("button", { name: "Add participant" })).toBeNull()
    })

    it("explains a refused add on a session that is not active", async () => {
      server.on("GET", S, { body: session({ status_code: "pending", available_actions: ["manage_participants"] }) })
      server.on("POST", `${S}/participants`, {
        status: 409,
        body: { error: { code: "session_not_active", message: "m", correlation_id: "c" } },
      })
      openApp("/app/mundivita/sessions/s1/run")
      await pickCael()
      fireEvent.click(screen.getByRole("button", { name: "Add participant" }))
      expect(await screen.findByText(/This session is not active, so it cannot be changed/)).toBeInTheDocument()
    })

    it("shows a duplicate conflict, reloads the roster, and keeps the message after the version changes", async () => {
      let state = session()
      server.on("GET", S, () => ({ body: state }))
      server.on("POST", `${S}/participants`, () => {
        // Someone else added Cael first, which also moved the row version.
        state = session({ row_version: 4, participants: [CAEL] })
        return DUPLICATE
      })
      openApp("/app/mundivita/sessions/s1/run")
      await pickCael()
      fireEvent.click(screen.getByRole("button", { name: "Add participant" }))
      expect(await screen.findByText(/Cael \(player character\)/)).toBeInTheDocument()
      expect(server.callsTo("GET", S).length).toBeGreaterThanOrEqual(2)
      expect(screen.getByText("That character is already in this session.")).toBeInTheDocument()
    })

    it("stops a duplicate before it is sent and does not offer present characters", async () => {
      server.on("GET", S, { body: session({ participants: [CAEL] }) })
      openApp("/app/mundivita/sessions/s1/run")
      await screen.findByText(/Cael \(player character\)/)
      fireEvent.focus(screen.getByRole("combobox", { name: "Character" }))
      await waitFor(() => expect(server.callsTo("GET", /world\/search/).length).toBeGreaterThan(0))
      expect(screen.queryByRole("option", { name: /Cael/ })).toBeNull()
    })

    it("recovers from a stale write: loads the latest version, keeps the choice, resubmits with it", async () => {
      let state = session()
      server.on("GET", S, () => ({ body: state }))
      let attempts = 0
      server.on("POST", `${S}/participants`, () => {
        attempts += 1
        if (attempts === 1) {
          state = session({ row_version: 4 })
          return { status: 409, body: { error: { code: "stale_write", message: "m", correlation_id: "c" } } }
        }
        state = session({ row_version: 5, participants: [CAEL] })
        return { status: 201, body: { session_id: "s1", row_version: 5, changed: true, session_participant_id: "p2" } }
      })
      openApp("/app/mundivita/sessions/s1/run")
      await pickCael()
      fireEvent.change(screen.getByRole("combobox", { name: "Role" }), { target: { value: "player_character" } })
      fireEvent.click(screen.getByRole("button", { name: "Add participant" }))
      fireEvent.click(await screen.findByRole("button", { name: "Load latest version" }))
      await waitFor(() => expect(screen.queryByRole("button", { name: "Load latest version" })).toBeNull())
      expect(screen.getByRole("combobox", { name: "Character" })).toHaveValue("Cael")
      fireEvent.click(screen.getByRole("button", { name: "Add participant" }))
      await waitFor(() => expect(server.callsTo("POST", `${S}/participants`)).toHaveLength(2))
      expect(server.callsTo("POST", `${S}/participants`)[0]!.body).toMatchObject({ expected_row_version: 3 })
      expect(server.callsTo("POST", `${S}/participants`)[1]!.body).toMatchObject({
        expected_row_version: 4,
        character_id: "c1",
        participation_role: "player_character",
      })
      expect(await screen.findByText(/Cael \(player character\)/)).toBeInTheDocument()
    })

    it("falls back to a visible message for an unrecognised or non-JSON conflict", async () => {
      server.on("GET", S, { body: session({ participants: [person("p1", "c9", "Mira", "npc")] }) })
      server.on("POST", `${S}/participants`, { status: 409 })
      server.on("POST", `${S}/participants/p1/remove`, { status: 409 })
      openApp("/app/mundivita/sessions/s1/run")
      await pickCael()
      fireEvent.click(screen.getByRole("button", { name: "Add participant" }))
      expect(await screen.findByRole("alert")).toHaveTextContent("conflicts with the record's current state")
      fireEvent.click(screen.getByRole("button", { name: "Remove Mira" }))
      await waitFor(() => expect(server.callsTo("POST", `${S}/participants/p1/remove`)).toHaveLength(1))
      await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(2))
    })

    it("updates the roster after a successful add and remove, and lets a removed character be added again", async () => {
      let state = session({ participants: [CAEL] })
      server.on("GET", S, () => ({ body: state }))
      server.on("POST", `${S}/participants/p2/remove`, () => {
        state = session({ row_version: 4, participants: [{ ...CAEL, removed_at: "2026-10-12T20:00:00Z" }] })
        return { body: { session_id: "s1", row_version: 4, changed: true, session_participant_id: "p2" } }
      })
      server.on("POST", `${S}/participants`, () => {
        state = session({
          row_version: 5,
          participants: [{ ...CAEL, removed_at: "2026-10-12T20:00:00Z" }, person("p4", "c1", "Cael", "guest")],
        })
        return { status: 201, body: { session_id: "s1", row_version: 5, changed: true, session_participant_id: "p4" } }
      })
      openApp("/app/mundivita/sessions/s1/run")
      fireEvent.click(await screen.findByRole("button", { name: "Remove Cael" }))
      expect(await screen.findByText("Left: Cael")).toBeInTheDocument()
      expect(screen.getByText("No one is in this session yet.")).toBeInTheDocument()

      await pickCael() // the removed character is offered again
      fireEvent.click(screen.getByRole("button", { name: "Add participant" }))
      expect(await screen.findByText(/Cael \(guest\)/)).toBeInTheDocument()
      expect(server.callsTo("POST", `${S}/participants`)[0]!.body).toMatchObject({ expected_row_version: 4 })
    })
  })

  it("denies the page to a member who cannot edit canon", async () => {
    openApp("/app/mundivita/sessions/s1/run", ["campaign.view"])
    expect(await screen.findByRole("alert")).toHaveTextContent("do not have permission")
  })
})
