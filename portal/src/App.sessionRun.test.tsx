import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const S = "/campaigns/mundivita/sessions/s1"
const RUN = "/app/mundivita/sessions/s1/run"

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
  server.on("GET", "/campaigns/mundivita/authoring/encounters?session_id=s1", { body: { items: [] } })
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
    openApp(`${RUN}?section=log`)
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
    openApp(`${RUN}?section=log`)
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
    openApp(`${RUN}?section=end`)
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
      openApp(`${RUN}?section=participants`)
      await pickCael()
      fireEvent.click(screen.getByRole("button", { name: "Add participant" }))
      const panel = screen.getByRole("region", { name: "Participants" })
      expect(await within(panel).findByText(/This session is not active, so it cannot be changed/)).toBeInTheDocument()
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

const MIRA = {
  session_participant_id: "p1",
  character_id: "c9",
  character_name: "Mira",
  participation_role: "npc",
  added_at: "2026-10-12T19:00:00Z",
  removed_at: null,
}
const ENCOUNTERS = "/campaigns/mundivita/authoring/encounters?session_id=s1"

const navLinks = (name: string) =>
  within(screen.getByRole("navigation", { name })).getAllByRole("link").map((l) => l.textContent)

describe("stages and sections", () => {
  it("shows each stage's own sections in its local menu", async () => {
    server.on("GET", S, { body: playing() })
    openApp(`${RUN}?section=log`)
    await screen.findByRole("heading", { level: 1, name: "Run: The Hollow Road" })
    expect(navLinks("Session stages")).toEqual(["1. Prepare", "2. Run session", "3. Wrap up"])
    expect(navLinks("Run session sections")).toEqual(["Session log", "Travel", "Award item", "Encounters"])
    expect(screen.queryByRole("navigation", { name: "Prepare sections" })).toBeNull()

    fireEvent.click(screen.getByRole("link", { name: "1. Prepare" }))
    expect(navLinks("Prepare sections")).toEqual(["Participants", "Encounter preparation"])
    expect(screen.queryByRole("navigation", { name: "Run session sections" })).toBeNull()

    fireEvent.click(screen.getByRole("link", { name: "3. Wrap up" }))
    expect(navLinks("Wrap up sections")).toEqual(["Session review", "End session"])
    expect(screen.getByRole("link", { name: "3. Wrap up" })).toHaveAttribute("aria-current", "step")
  })

  it("displays one section at a time and marks it current", async () => {
    server.on("GET", S, { body: playing() })
    server.on("GET", "/campaigns/mundivita/parties", { body: { can_create: true, items: [] } })
    openApp(`${RUN}?section=log`)
    expect(await screen.findByRole("region", { name: "Session log" })).toBeVisible()
    expect(screen.queryByRole("region", { name: "Travel" })).toBeNull()
    expect(screen.queryByRole("region", { name: "Participants" })).toBeNull()
    fireEvent.click(screen.getByRole("link", { name: "Travel" }))
    expect(await screen.findByRole("region", { name: "Travel" })).toBeVisible()
    expect(screen.queryByRole("region", { name: "Session log" })).toBeNull()
    expect(screen.getByRole("link", { name: "Travel" })).toHaveAttribute("aria-current", "page")
  })

  it.each([
    ["unscheduled", { play_status: "unscheduled" }, "?section=participants", "Participants"],
    ["scheduled", {}, "?section=participants", "Participants"],
    ["in progress", { play_status: "in_progress", available_actions: ["log", "end"] }, "?section=log", "Session log"],
    [
      "completed",
      { play_status: "completed", available_actions: ["update", "archive"] },
      "?section=review",
      "Session review",
    ],
    ["archived", { status_code: "archived", available_actions: ["restore"] }, "?section=review", "Session review"],
  ])("opens a %s session on the right section, replacing the address", async (_name, extra, search, heading) => {
    server.on("GET", S, { body: session(extra) })
    const { router } = openApp(RUN)
    expect(await screen.findByRole("region", { name: heading })).toBeVisible()
    await waitFor(() => expect(router.state.location.search).toBe(search))
    expect(router.state.historyAction).toBe("REPLACE")
  })

  it("normalises an unknown section without adding a history entry", async () => {
    server.on("GET", S, { body: playing() })
    const { router } = openApp(`${RUN}?section=bogus`)
    expect(await screen.findByRole("region", { name: "Session log" })).toBeVisible()
    await waitFor(() => expect(router.state.location.search).toBe("?section=log"))
    expect(router.state.historyAction).toBe("REPLACE")
  })

  it("opens a deep link to a section after the session loads", async () => {
    server.on("GET", S, { body: playing() })
    server.on("GET", "/campaigns/mundivita/parties", { body: { can_create: true, items: [] } })
    openApp(`${RUN}?section=travel`)
    expect(screen.queryByRole("region", { name: "Travel" })).toBeNull()
    expect(await screen.findByRole("form", { name: "Record travel" })).toBeVisible()
    expect(screen.getByRole("link", { name: "2. Run session" })).toHaveAttribute("aria-current", "step")
  })

  it("makes no request that changes anything when moving between stages and sections", async () => {
    server.on("GET", S, { body: session() })
    openApp(`${RUN}?section=participants`)
    await screen.findByRole("region", { name: "Participants" })
    for (const name of ["2. Run session", "3. Wrap up", "End session", "Session review", "1. Prepare", "Encounter preparation"]) {
      fireEvent.click(screen.getByRole("link", { name }))
    }
    expect(server.callsTo("POST", /./)).toHaveLength(0)
    expect(server.callsTo("PUT", /./)).toHaveLength(0)
    expect(server.callsTo("PATCH", /./)).toHaveLength(0)
    expect(server.callsTo("DELETE", /./)).toHaveLength(0)
    expect(screen.getByText("Scheduled")).toBeInTheDocument()
  })

  it("keeps drafts and each stage's section across stage changes, Back and Forward", async () => {
    server.on("GET", S, { body: playing({ participants: [MIRA] }) })
    server.on("GET", "/campaigns/mundivita/parties", { body: { can_create: true, items: [] } })
    const { router } = openApp(`${RUN}?section=log`)
    fireEvent.change(await screen.findByLabelText(/What happened/), { target: { value: "Half written" } })
    fireEvent.change(screen.getByLabelText(/GM notes/), { target: { value: "Secret" } })

    fireEvent.click(screen.getByRole("link", { name: "Travel" }))
    fireEvent.click(screen.getByRole("link", { name: "1. Prepare" }))
    expect(await screen.findByRole("region", { name: "Participants" })).toBeVisible()
    fireEvent.click(screen.getByRole("link", { name: "2. Run session" }))
    // The stage reopens on the section last used in it.
    expect(await screen.findByRole("region", { name: "Travel" })).toBeVisible()
    fireEvent.click(screen.getByRole("link", { name: "Session log" }))
    expect(screen.getByLabelText(/What happened/)).toHaveValue("Half written")
    expect(screen.getByLabelText(/GM notes/)).toHaveValue("Secret")

    await act(async () => {
      await router.navigate(-1)
    })
    expect(router.state.location.search).toBe("?section=travel")
    await act(async () => {
      await router.navigate(-3)
    })
    expect(router.state.location.search).toBe("?section=log")
    expect(screen.getByLabelText(/What happened/)).toHaveValue("Half written")
    expect(server.callsTo("POST", /./)).toHaveLength(0)
  })

  it("keeps an unfinished participant choice while another stage is shown", async () => {
    server.on("GET", S, { body: session() })
    openApp(`${RUN}?section=participants`)
    fireEvent.focus(await screen.findByRole("combobox", { name: "Character" }))
    fireEvent.click(await screen.findByRole("option", { name: /Cael/ }))
    fireEvent.change(screen.getByRole("combobox", { name: "Role" }), { target: { value: "npc" } })
    fireEvent.click(screen.getByRole("link", { name: "3. Wrap up" }))
    fireEvent.click(screen.getByRole("link", { name: "1. Prepare" }))
    expect(screen.getByRole("combobox", { name: "Character" })).toHaveValue("Cael")
    expect(screen.getByRole("combobox", { name: "Role" })).toHaveValue("npc")
  })

  it("offers Advance and Correct time only in the Run stage and keeps a half-entered time", async () => {
    server.on("GET", S, { body: playing() })
    openApp(`${RUN}?section=log`)
    expect(await screen.findByText("Now: Year 1")).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Campaign time (in-world)" })).toBeInTheDocument()
    fireEvent.click(await screen.findByRole("button", { name: "Advance time" }))
    fireEvent.change(await screen.findByRole("combobox", { name: /Advance to/ }), { target: { value: "t2" } })

    fireEvent.click(screen.getByRole("link", { name: "1. Prepare" }))
    expect(screen.getByText("Now: Year 1")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Advance time" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Correct time" })).toBeNull()
    expect(screen.queryByRole("combobox", { name: /Advance to/ })).toBeNull()

    fireEvent.click(screen.getByRole("link", { name: "2. Run session" }))
    expect(screen.getByRole("combobox", { name: /Advance to/ })).toHaveValue("t2")
    expect(server.callsTo("POST", /./)).toHaveLength(0)
  })

  it("labels real-world times as such", async () => {
    server.on("GET", S, { body: playing() })
    openApp(`${RUN}?section=log`)
    expect((await screen.findAllByText(/Real-world start:/)).length).toBeGreaterThan(0)
  })

  describe("breadcrumb", () => {
    it("links Sessions and the session, and names the current page", async () => {
      server.on("GET", S, { body: playing() })
      openApp(`${RUN}?section=travel`)
      const crumbs = await screen.findByRole("navigation", { name: "Breadcrumb" })
      await within(crumbs).findByRole("link", { name: "The Hollow Road" })
      expect(within(crumbs).getByRole("link", { name: "Sessions" })).toHaveAttribute("href", "/app/mundivita/sessions")
      expect(within(crumbs).getByRole("link", { name: "The Hollow Road" })).toHaveAttribute(
        "href",
        "/app/mundivita/sessions/s1",
      )
      expect(within(crumbs).getByText("Run session")).toHaveAttribute("aria-current", "page")
      expect(within(crumbs).queryByRole("link", { name: "Run session" })).toBeNull()
      expect(within(crumbs).queryByText(/Travel/)).toBeNull()
    })

    it("does not show an identifier when the session is unavailable", async () => {
      server.on("GET", S, { status: 404, body: { error: { code: "not_found", message: "m", correlation_id: "c" } } })
      openApp(RUN)
      await screen.findByRole("alert")
      const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" })
      expect(within(crumbs).getByText("Session")).toBeInTheDocument()
      expect(within(crumbs).queryByText(/s1/)).toBeNull()
      expect(within(crumbs).getAllByRole("link")).toHaveLength(1)
    })

    it("reaches the session list route", async () => {
      server.on("GET", S, { body: playing() })
      const { router } = openApp(`${RUN}?section=log`)
      const crumbs = await screen.findByRole("navigation", { name: "Breadcrumb" })
      fireEvent.click(within(crumbs).getByRole("link", { name: "Sessions" }))
      await waitFor(() => expect(router.state.location.pathname).toBe("/app/mundivita/sessions"))
    })
  })

  describe("lifecycle and permissions", () => {
    it("explains why a scheduled session cannot be played yet and offers Start only in Run", async () => {
      server.on("GET", S, { body: session() })
      server.on("GET", "/campaigns/mundivita/parties", { body: { can_create: true, items: [] } })
      openApp(`${RUN}?section=participants`)
      expect(await screen.findByText("When the table is ready, go to Run session to start.")).toBeVisible()
      expect(screen.queryByRole("button", { name: "Start session" })).toBeNull()
      fireEvent.click(screen.getByRole("link", { name: "2. Run session" }))
      expect(screen.getByRole("button", { name: "Start session" })).toBeVisible()
      expect(
        within(screen.getByRole("region", { name: "Session log" })).getByText("Start the session to record entries."),
      ).toBeVisible()
      expect(screen.queryByRole("button", { name: "Record entry" })).toBeNull()
      fireEvent.click(screen.getByRole("link", { name: "Travel" }))
      expect(
        within(screen.getByRole("region", { name: "Travel" })).getByText("Start the session to record travel."),
      ).toBeVisible()
      expect(screen.queryByRole("form", { name: "Record travel" })).toBeNull()
      expect(server.callsTo("POST", /./)).toHaveLength(0)
    })

    it("shows a completed session read-only, with reasons", async () => {
      server.on("GET", S, {
        body: session({
          play_status: "completed",
          ended_at: "2026-10-12T22:00:00Z",
          available_actions: ["update", "archive"],
          participants: [MIRA],
        }),
      })
      openApp(`${RUN}?section=log`)
      const log = await screen.findByRole("region", { name: "Session log" })
      expect(within(log).getByText("This session has ended, so you can no longer record entries.")).toBeVisible()
      expect(screen.queryByRole("button", { name: "Record entry" })).toBeNull()
      fireEvent.click(screen.getByRole("link", { name: "3. Wrap up" }))
      fireEvent.click(screen.getByRole("link", { name: "End session" }))
      expect(within(screen.getByRole("region", { name: "End session" })).getByText("This session has ended.")).toBeVisible()
      expect(screen.queryByRole("button", { name: "End session" })).toBeNull()
      fireEvent.click(screen.getByRole("link", { name: "1. Prepare" }))
      expect(
        within(screen.getByRole("region", { name: "Participants" })).getByText("Participants can't be changed after the session ends."),
      ).toBeVisible()
    })

    it("keeps public text and GM notes apart, with their audience hints", async () => {
      server.on("GET", S, { body: playing() })
      openApp(`${RUN}?section=log`)
      const entry = await screen.findByLabelText(/What happened/)
      expect(entry).toHaveAccessibleDescription("Visible to everyone in the campaign.")
      expect(screen.getByLabelText(/GM notes/)).toHaveAccessibleDescription(
        "Visible only to people who can edit canon.",
      )
    })

    it("records an entry with an optional time", async () => {
      server.on("GET", S, { body: playing() })
      server.on("POST", `${S}/log`, {
        status: 201,
        body: { session_id: "s1", row_version: 3, changed: true, event_id: "ev1" },
      })
      openApp(`${RUN}?section=log`)
      fireEvent.change(await screen.findByLabelText(/What happened/), { target: { value: "Dawn breaks." } })
      fireEvent.change(await screen.findByRole("combobox", { name: /When/ }), { target: { value: "t2" } })
      fireEvent.click(screen.getByRole("button", { name: "Record entry" }))
      await waitFor(() => expect(server.callsTo("POST", `${S}/log`)).toHaveLength(1))
      expect(server.callsTo("POST", `${S}/log`)[0]!.body).toEqual({
        entry: "Dawn breaks.",
        details: null,
        world_time_id: "t2",
      })
    })

    it("keeps End session behind its confirmation and leaves the session running on cancel", async () => {
      server.on("GET", S, { body: playing() })
      openApp(`${RUN}?section=end`)
      expect(screen.queryByRole("dialog")).toBeNull()
      fireEvent.click(await screen.findByRole("button", { name: "End session" }))
      const dialog = await screen.findByRole("dialog", { name: "End this session?" })
      fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
      expect(server.callsTo("POST", /./)).toHaveLength(0)
      expect(screen.getByText("In progress")).toBeInTheDocument()
    })

    it("offers a link to the review after the session ends, without moving the user", async () => {
      let state = playing()
      server.on("GET", S, () => ({ body: state }))
      server.on("POST", `${S}/end`, () => {
        state = session({
          play_status: "completed",
          ended_at: "2026-10-12T22:00:00Z",
          available_actions: ["update", "archive"],
        })
        return { body: { session_id: "s1", row_version: 4, changed: true } }
      })
      const { router } = openApp(`${RUN}?section=end`)
      fireEvent.click(await screen.findByRole("button", { name: "End session" }))
      const dialog = await screen.findByRole("dialog")
      fireEvent.click(within(dialog).getByRole("button", { name: "End session" }))
      const link = await screen.findByRole("link", { name: "Go to the session review" })
      expect(router.state.location.search).toBe("?section=end")
      fireEvent.click(link)
      expect(router.state.location.search).toBe("?section=review")
    })

    it("offers a link to the log after Start, without moving the user", async () => {
      let state = session()
      server.on("GET", S, () => ({ body: state }))
      server.on("POST", `${S}/start`, () => {
        state = playing({ row_version: 4 })
        return { body: { session_id: "s1", row_version: 4, changed: true } }
      })
      const { router } = openApp(`${RUN}?section=travel`)
      fireEvent.click(await screen.findByRole("button", { name: "Start session" }))
      expect(await screen.findByRole("link", { name: "Go to the session log" })).toBeVisible()
      expect(router.state.location.search).toBe("?section=travel")
    })
  })

  describe("operations from their new sections", () => {
    it("records travel for a whole party", async () => {
      server.on("GET", S, { body: playing({ participants: [MIRA] }) })
      server.on("GET", "/campaigns/mundivita/parties", {
        body: {
          can_create: true,
          items: [{ party_id: "pa1", name: "The Company", description: null, lifecycle_status: "active", row_version: 1 }],
        },
      })
      server.on("GET", /authoring\/routes\?location_id=/, { body: { items: [] } })
      server.on("POST", "/campaigns/mundivita/travel", {
        body: { changed: true, moved: [{}], event_id: "ev9" },
      })
      openApp(`${RUN}?section=travel`)
      const form = await screen.findByRole("form", { name: "Record travel" })
      fireEvent.focus(within(form).getByRole("combobox", { name: "Destination" }))
      fireEvent.click(await within(form).findByRole("option", { name: /Cael/ }))
      fireEvent.change(await within(form).findByRole("combobox", { name: /whole party/ }), { target: { value: "pa1" } })
      fireEvent.click(within(form).getByRole("button", { name: "Record travel" }))
      await waitFor(() => expect(server.callsTo("POST", "/campaigns/mundivita/travel")).toHaveLength(1))
      expect(server.callsTo("POST", "/campaigns/mundivita/travel")[0]!.body).toEqual({
        destination_location_id: "c1",
        character_ids: [],
        party_id: "pa1",
        route_id: null,
      })
    })

    it("offers the present participants as individual travelers", async () => {
      server.on("GET", S, { body: playing({ participants: [MIRA] }) })
      server.on("GET", "/campaigns/mundivita/parties", { body: { can_create: true, items: [] } })
      openApp(`${RUN}?section=travel`)
      const form = await screen.findByRole("form", { name: "Record travel" })
      expect(within(form).getByRole("checkbox", { name: "Mira" })).toBeVisible()
    })

    it("awards an item to a present participant", async () => {
      server.on("GET", S, { body: playing({ participants: [MIRA] }) })
      server.on("GET", "/campaigns/mundivita/authoring/items", {
        body: {
          items: [
            {
              item_instance_id: "i1",
              name: "Sword",
              definition_name: "Longsword",
              category_label: "Weapon",
              canon_status: "canon",
              lifecycle_status: "active",
              holder_name: null,
              is_destroyed: false,
            },
          ],
        },
      })
      server.on("GET", "/campaigns/mundivita/authoring/items/i1", { body: { last_event_id: "ev3" } })
      server.on("POST", /campaigns\/mundivita\/items\/i1\/award/, { body: { item_instance_id: "i1" } })
      openApp(`${RUN}?section=award-item`)
      fireEvent.change(await screen.findByRole("combobox", { name: "Item" }), { target: { value: "i1" } })
      fireEvent.change(screen.getByRole("combobox", { name: "Award to" }), { target: { value: "c9" } })
      fireEvent.click(screen.getByRole("button", { name: "Award item" }))
      await waitFor(() => expect(server.callsTo("POST", /campaigns\/mundivita\/items\/i1\/award/)).toHaveLength(1))
      expect(server.callsTo("POST", /campaigns\/mundivita\/items\/i1\/award/)[0]!.body).toMatchObject({
        expected_last_event_id: "ev3",
        holder_entity_id: "c9",
      })
    })
  })

  describe("encounters and review", () => {
    const encounters = {
      items: [
        { encounter_id: "e1", status: "pending", summary: "Ambush", location_name: null, participant_count: 2 },
        { encounter_id: "e2", status: "active", summary: "Bridge fight", location_name: "Stonebridge", participant_count: 3 },
      ],
    }

    it("splits prepared and started encounters between Prepare and Run", async () => {
      server.on("GET", S, { body: playing() })
      server.on("GET", ENCOUNTERS, { body: encounters })
      openApp(`${RUN}?section=encounter-prep`)
      const prep = await screen.findByRole("region", { name: "Encounter preparation" })
      expect(await within(prep).findByRole("link", { name: "Ambush" })).toHaveAttribute(
        "href",
        "/app/mundivita/sessions/s1/encounters/e1",
      )
      expect(within(prep).queryByRole("link", { name: "Bridge fight" })).toBeNull()
      expect(within(prep).getByRole("link", { name: "Prepare an encounter" })).toHaveAttribute(
        "href",
        "/app/mundivita/sessions/s1/encounters/new",
      )
      fireEvent.click(within(prep).getByRole("link", { name: /started or finished/ }))
      const run = await screen.findByRole("region", { name: "Encounters" })
      expect(within(run).getByRole("link", { name: "Bridge fight" })).toBeVisible()
      expect(within(run).queryByRole("link", { name: "Ambush" })).toBeNull()
    })

    it("allows preparing encounters before the session starts", async () => {
      server.on("GET", S, { body: session() })
      openApp(`${RUN}?section=encounter-prep`)
      const prep = await screen.findByRole("region", { name: "Encounter preparation" })
      expect(await within(prep).findByRole("link", { name: "Prepare an encounter" })).toBeVisible()
    })

    it("does not offer encounter preparation once the session has ended", async () => {
      server.on("GET", S, {
        body: session({ play_status: "completed", available_actions: ["update", "archive"] }),
      })
      openApp(`${RUN}?section=encounter-prep`)
      const prep = await screen.findByRole("region", { name: "Encounter preparation" })
      expect(within(prep).getByText(/can no longer be prepared/)).toBeVisible()
      expect(within(prep).queryByRole("link", { name: "Prepare an encounter" })).toBeNull()
    })

    it("reports an encounter list that cannot load", async () => {
      server.on("GET", S, { body: playing() })
      server.on("GET", ENCOUNTERS, { status: 500 })
      openApp(`${RUN}?section=encounters`)
      const run = await screen.findByRole("region", { name: "Encounters" })
      expect(await within(run).findByRole("alert")).toHaveTextContent("Encounters could not be loaded.")
    })

    it("reviews the session and links only to sections that are offered", async () => {
      server.on("GET", S, {
        body: playing({
          participants: [MIRA],
          summary: "Into the hollow.",
          events: [
            {
              event_id: "ev1",
              name: "The party enters the crypt.",
              summary: null,
              event_type_code: "session_narrative",
              event_status_code: "recorded",
              world_time_id: "t1",
              details: "Trapped door",
            },
          ],
        }),
      })
      server.on("GET", ENCOUNTERS, { body: encounters })
      openApp(`${RUN}?section=review`)
      const review = await screen.findByRole("region", { name: "Session review" })
      expect(within(review).getByText("Recap: Into the hollow.")).toBeVisible()
      expect(within(review).getByText("Mira: NPC")).toBeVisible()
      expect(within(review).getByRole("link", { name: "The party enters the crypt." })).toHaveAttribute(
        "href",
        "/app/mundivita/events/ev1",
      )
      // The page is editors-only, so the review shows each entry's GM notes as the log does.
      expect(within(review).getByText("GM notes: Trapped door")).toBeVisible()
      expect(within(review).getByRole("link", { name: "Change participants" })).toHaveAttribute(
        "href",
        expect.stringMatching(/\?section=participants$/),
      )
      expect(within(review).getByRole("link", { name: "Add to the log" })).toHaveAttribute("href", expect.stringMatching(/\?section=log$/))
      expect(await within(review).findByText("1 prepared, 1 started or finished.")).toBeVisible()
      expect(within(review).getByRole("link", { name: "Edit session details" })).toHaveAttribute(
        "href",
        "/app/mundivita/sessions/s1",
      )
    })

    it("replaces go-to links with reasons when the session cannot be changed", async () => {
      server.on("GET", S, {
        body: session({ play_status: "completed", available_actions: ["update", "archive"] }),
      })
      openApp(RUN)
      const review = await screen.findByRole("region", { name: "Session review" })
      expect(within(review).queryByRole("link", { name: "Add to the log" })).toBeNull()
      expect(within(review).queryByRole("link", { name: "Change participants" })).toBeNull()
      expect(within(review).getByText("This session has ended, so you can no longer record entries.")).toBeVisible()
      expect(within(review).getByText("Participants can't be changed now.")).toBeVisible()
    })
  })

  it("shows an unavailable session without stage controls", async () => {
    server.on("GET", S, { status: 404, body: { error: { code: "not_found", message: "m", correlation_id: "c" } } })
    openApp(RUN)
    expect(await screen.findByRole("alert")).toHaveTextContent("does not exist, or you do not have access")
    expect(screen.queryByRole("navigation", { name: "Session stages" })).toBeNull()
  })

  it("shows no stage controls to a member who cannot edit canon", async () => {
    openApp(RUN, ["campaign.view"])
    expect(await screen.findByRole("alert")).toHaveTextContent("do not have permission")
    expect(screen.queryByRole("navigation", { name: "Session stages" })).toBeNull()
  })
})
