import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"
import { fromLocalInput, toLocalInput } from "./utils/sessionForm"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const LIST = "/campaigns/mundivita/sessions"

const item = (id: string, n: number, extra: Record<string, unknown> = {}) => ({
  session_id: id,
  session_number: n,
  title: `Session ${n}`,
  status_code: "active",
  started_at: null,
  ended_at: null,
  scheduled_for: null,
  play_status: "unscheduled",
  row_version: 2,
  available_actions: ["update", "archive"],
  ...extra,
})

const detail = (extra: Record<string, unknown> = {}) => ({
  ...item("s1", 1, { summary: "Recap", start_world_time_id: null, end_world_time_id: null, events: [] }),
  ...extra,
})

let server: MockServer

beforeEach(() => {
  server = installCampaignShellMocks()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("session authoring pages", () => {
  it("round-trips a planned start through the datetime-local input", () => {
    const iso = "2026-10-12T19:30:00.000Z"
    expect(fromLocalInput(toLocalInput(iso))).toBe(iso)
    expect(toLocalInput(null)).toBe("")
    expect(fromLocalInput("")).toBeNull()
    expect(fromLocalInput("not a date")).toBeNull()
  })

  it("lists status, links titles to the canonical page and has no Edit links", async () => {
    server.on("GET", LIST, {
      body: [item("s1", 1), item("s2", 2, { play_status: "scheduled", scheduled_for: "2026-10-12T19:30:00Z" })],
    })
    openApp("/app/mundivita/sessions")
    expect(await screen.findByRole("link", { name: "Schedule a session" })).toHaveAttribute(
      "href",
      "/app/mundivita/sessions/new",
    )
    expect(await screen.findByText("Scheduled")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Session 1" })).toHaveAttribute(
      "href",
      "/app/mundivita/sessions/s1",
    )
    expect(screen.queryByRole("link", { name: /^Edit / })).toBeNull()
  })

  it("shows players the status but no editing controls", async () => {
    server.on("GET", LIST, {
      body: [item("s1", 1, { row_version: null, available_actions: null })],
    })
    openApp("/app/mundivita/sessions", ["campaign.view"])
    expect(await screen.findByText("Not scheduled")).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "Schedule a session" })).toBeNull()
    expect(screen.queryByRole("link", { name: /^Edit / })).toBeNull()
  })

  it("schedules a session after validating, sending an idempotency key", async () => {
    server.on("GET", LIST, { body: [] })
    server.on("POST", LIST, {
      status: 201,
      body: { session_id: "s9", session_number: 1, row_version: 1, created: true, changed: true },
    })
    openApp("/app/mundivita/sessions/new")
    expect(await screen.findByRole("heading", { level: 1, name: "Schedule a session" })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("Planned start"), { target: { value: "not-a-date" } })
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "x".repeat(500) } })
    fireEvent.click(screen.getByRole("button", { name: "Schedule session" }))
    expect((await screen.findAllByText(/Title must be/)).length).toBeGreaterThan(0)
    expect(server.callsTo("POST", /./)).toHaveLength(0)

    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "The Hollow Road" } })
    fireEvent.change(screen.getByLabelText("Planned start"), { target: { value: "2026-10-12T19:30" } })
    fireEvent.click(screen.getByRole("button", { name: "Schedule session" }))
    await waitFor(() => expect(server.callsTo("POST", LIST)).toHaveLength(1))
    const [call] = server.callsTo("POST", LIST)
    expect(call!.body).toMatchObject({ title: "The Hollow Road", summary: null })
    expect(new Date((call!.body as { scheduled_for: string }).scheduled_for).getTime()).toBe(
      new Date("2026-10-12T19:30").getTime(),
    )
    expect(call!.headers["Idempotency-Key"]).toBeTruthy()
  })

  it("redirects an old /edit URL to the canonical page, replacing history", async () => {
    server.on("GET", `${LIST}/s1`, { body: detail() })
    const { router } = openApp("/app/mundivita/sessions/s1/edit")
    expect(await screen.findByLabelText("Title")).toHaveValue("Session 1")
    expect(router.state.location.pathname).toBe("/app/mundivita/sessions/s1")
    expect(router.state.historyAction).toBe("REPLACE")
  })

  it("lets an editor edit in place and saves without leaving the page", async () => {
    const calls = { gets: 0 }
    server.on("GET", `${LIST}/s1`, () => {
      calls.gets += 1
      return {
        body:
          calls.gets === 1
            ? detail()
            : detail({ title: "Renamed", row_version: 3 }),
      }
    })
    server.on("POST", `${LIST}/s1/update`, {
      body: { session_id: "s1", session_number: 1, row_version: 3, created: false, changed: true },
    })
    const { router } = openApp("/app/mundivita/sessions/s1")
    const title = await screen.findByLabelText("Title")
    expect(title).toHaveValue("Session 1")
    expect(screen.queryByRole("link", { name: /Edit/ })).toBeNull()
    fireEvent.change(title, { target: { value: "Renamed" } })
    fireEvent.click(screen.getByRole("button", { name: "Save" }))
    expect(await screen.findByText("Session saved.")).toBeInTheDocument()
    const [call] = server.callsTo("POST", `${LIST}/s1/update`)
    expect(call!.body).toEqual({
      title: "Renamed",
      scheduled_for: null,
      summary: "Recap",
      expected_row_version: 2,
    })
    expect(call!.headers["Idempotency-Key"]).toBeTruthy()
    expect(router.state.location.pathname).toBe("/app/mundivita/sessions/s1")
    expect(screen.getByRole("heading", { level: 1, name: "Renamed" })).toBeInTheDocument()
    expect(screen.getByLabelText("Title")).toHaveValue("Renamed")
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull()

    // The next save uses the refreshed row version.
    server.on("POST", `${LIST}/s1/update`, {
      body: { session_id: "s1", session_number: 1, row_version: 4, created: false, changed: true },
    })
    fireEvent.change(screen.getByLabelText("Summary"), { target: { value: "More" } })
    fireEvent.click(screen.getByRole("button", { name: "Save" }))
    await waitFor(() => expect(server.callsTo("POST", `${LIST}/s1/update`)).toHaveLength(2))
    expect(server.callsTo("POST", `${LIST}/s1/update`)[1]!.body).toMatchObject({
      expected_row_version: 3,
    })
  })

  it("discards edits back to the latest loaded values without navigating", async () => {
    server.on("GET", `${LIST}/s1`, { body: detail() })
    const { router } = openApp("/app/mundivita/sessions/s1")
    const summary = await screen.findByLabelText("Summary")
    fireEvent.change(summary, { target: { value: "Changed" } })
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }))
    expect(screen.getByLabelText("Summary")).toHaveValue("Recap")
    expect(router.state.location.pathname).toBe("/app/mundivita/sessions/s1")
    expect(server.callsTo("POST", /./)).toHaveLength(0)
  })

  it("protects unsaved edits when navigating away", async () => {
    server.on("GET", `${LIST}/s1`, { body: detail() })
    server.on("GET", LIST, { body: [item("s1", 1)] })
    const { router } = openApp("/app/mundivita/sessions/s1")
    fireEvent.change(await screen.findByLabelText("Title"), { target: { value: "Draft" } })
    fireEvent.click(screen.getByRole("link", { name: "Back to sessions" }))
    const dialog = await screen.findByRole("dialog", { name: "Discard your changes?" })
    expect(router.state.location.pathname).toBe("/app/mundivita/sessions/s1")
    fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
    expect(screen.getByLabelText("Title")).toHaveValue("Draft")
    fireEvent.click(screen.getByRole("link", { name: "Back to sessions" }))
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "Discard your changes?" })).getByRole(
        "button",
        { name: "Discard" },
      ),
    )
    await waitFor(() => expect(router.state.location.pathname).toBe("/app/mundivita/sessions"))
  })

  it("validates before saving and keeps what was typed", async () => {
    server.on("GET", `${LIST}/s1`, { body: detail() })
    openApp("/app/mundivita/sessions/s1")
    const title = await screen.findByLabelText("Title")
    fireEvent.change(title, { target: { value: "x".repeat(500) } })
    fireEvent.click(screen.getByRole("button", { name: "Save" }))
    expect((await screen.findAllByText(/Title must be/)).length).toBeGreaterThan(0)
    expect(server.callsTo("POST", /./)).toHaveLength(0)
    expect(screen.getByLabelText("Title")).toHaveValue("x".repeat(500))
  })

  it("adopts the latest version into untouched fields and preserves typed input", async () => {
    let latest = false
    server.on("GET", `${LIST}/s1`, () => ({
      body: latest ? detail({ summary: "Someone else", row_version: 5 }) : detail(),
    }))
    server.on("POST", `${LIST}/s1/update`, {
      status: 409,
      body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
    })
    openApp("/app/mundivita/sessions/s1")
    fireEvent.change(await screen.findByLabelText("Title"), { target: { value: "Renamed" } })
    fireEvent.click(screen.getByRole("button", { name: "Save" }))
    latest = true
    fireEvent.click(await screen.findByRole("button", { name: "Load latest version" }))
    await waitFor(() => expect(screen.getByLabelText("Summary")).toHaveValue("Someone else"))
    expect(screen.getByLabelText("Title")).toHaveValue("Renamed")
    expect(screen.queryByRole("button", { name: "Load latest version" })).toBeNull()
  })

  it("keeps the input and offers Retry after a server error", async () => {
    server.on("GET", `${LIST}/s1`, { body: detail() })
    server.on("POST", `${LIST}/s1/update`, {
      status: 500,
      body: { error: { code: "internal", message: "m", correlation_id: "c" } },
    })
    openApp("/app/mundivita/sessions/s1")
    fireEvent.change(await screen.findByLabelText("Title"), { target: { value: "Renamed" } })
    fireEvent.click(screen.getByRole("button", { name: "Save" }))
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument()
    expect(screen.getByLabelText("Title")).toHaveValue("Renamed")
  })

  it("echoes a started session's planned start untouched when saving title and summary", async () => {
    const planned = "2026-10-12T19:30:45.123Z"
    server.on("GET", `${LIST}/s1`, {
      body: detail({
        started_at: "2026-10-12T19:31:00Z",
        scheduled_for: planned,
        play_status: "in_progress",
        available_actions: ["update"],
      }),
    })
    server.on("POST", `${LIST}/s1/update`, {
      body: { session_id: "s1", session_number: 1, row_version: 3, created: false, changed: true },
    })
    openApp("/app/mundivita/sessions/s1")
    const scheduled = await screen.findByLabelText("Planned start")
    expect(scheduled).toHaveAttribute("readonly")
    expect(screen.getByText(/has started, so its planned start cannot change/)).toBeInTheDocument()
    expect(screen.getByText("End the session before archiving it.")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Archive session" })).toBeNull()
    fireEvent.change(scheduled, { target: { value: "2030-01-01T00:00" } })
    fireEvent.change(screen.getByLabelText("Summary"), { target: { value: "New recap" } })
    fireEvent.click(screen.getByRole("button", { name: "Save" }))
    await waitFor(() => expect(server.callsTo("POST", `${LIST}/s1/update`)).toHaveLength(1))
    expect(server.callsTo("POST", `${LIST}/s1/update`)[0]!.body).toEqual({
      title: "Session 1",
      scheduled_for: planned,
      summary: "New recap",
      expected_row_version: 2,
    })
  })

  it("shows a viewer the same fields read-only and never submits an update", async () => {
    server.on("GET", `${LIST}/s1`, { body: detail({ row_version: null, available_actions: null }) })
    openApp("/app/mundivita/sessions/s1", ["campaign.view"])
    const title = await screen.findByLabelText("Title")
    expect(title).toHaveAttribute("readonly")
    expect(screen.getByLabelText("Planned start")).toHaveAttribute("readonly")
    expect(screen.getByLabelText("Summary")).toHaveAttribute("readonly")
    fireEvent.change(title, { target: { value: "tampered" } })
    fireEvent.submit(screen.getByRole("form", { name: "Session details" }))
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull()
    expect(server.callsTo("POST", /./)).toHaveLength(0)
  })

  it("prevents editing with the canon.edit capability when the server lists no update action", async () => {
    server.on("GET", `${LIST}/s1`, { body: detail({ available_actions: ["archive"] }) })
    openApp("/app/mundivita/sessions/s1")
    expect(await screen.findByLabelText("Title")).toHaveAttribute("readonly")
    expect(screen.getByText("This session cannot be edited right now.")).toBeInTheDocument()
  })

  it("archives after a confirmation", async () => {
    server.on("GET", `${LIST}/s1`, { body: detail() })
    server.on("POST", `${LIST}/s1/archive`, {
      body: { session_id: "s1", session_number: 1, row_version: 3, created: false, changed: true },
    })
    openApp("/app/mundivita/sessions/s1")
    fireEvent.click(await screen.findByRole("button", { name: "Archive session" }))
    expect(server.callsTo("POST", /./)).toHaveLength(0)
    const dialog = await screen.findByRole("dialog", { name: "Archive this session?" })
    fireEvent.click(within(dialog).getByRole("button", { name: "Archive session" }))
    await waitFor(() => expect(server.callsTo("POST", `${LIST}/s1/archive`)).toHaveLength(1))
    expect(server.callsTo("POST", `${LIST}/s1/archive`)[0]!.body).toEqual({
      expected_row_version: 2,
      reason: null,
    })
  })

  it("shows an archived session read-only; Restore needs a reason and then enables editing", async () => {
    let restored = false
    server.on("GET", `${LIST}/s1`, () => ({
      body: restored
        ? detail({ row_version: 4 })
        : detail({ status_code: "archived", available_actions: ["restore"] }),
    }))
    server.on("POST", `${LIST}/s1/restore`, () => {
      restored = true
      return {
        body: { session_id: "s1", session_number: 1, row_version: 4, created: false, changed: true },
      }
    })
    openApp("/app/mundivita/sessions/s1")
    expect(await screen.findByLabelText("Title")).toHaveAttribute("readonly")
    expect(screen.getByText(/archived, so its fields are read-only/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Restore session" }))
    const dialog = await screen.findByRole("dialog", { name: "Restore this session?" })
    fireEvent.click(within(dialog).getByRole("button", { name: "Restore session" }))
    expect(await within(dialog).findByText("Enter a reason.")).toBeInTheDocument()
    expect(server.callsTo("POST", /./)).toHaveLength(0)
    fireEvent.change(within(dialog).getByLabelText(/Reason/), { target: { value: "Reopened" } })
    fireEvent.click(within(dialog).getByRole("button", { name: "Restore session" }))
    await waitFor(() => expect(screen.getByLabelText("Title")).not.toHaveAttribute("readonly"))
  })

  it("denies the schedule form to a member who cannot edit canon", async () => {
    openApp("/app/mundivita/sessions/new", ["campaign.view"])
    expect(await screen.findByRole("alert")).toHaveTextContent("do not have permission")
  })
})
