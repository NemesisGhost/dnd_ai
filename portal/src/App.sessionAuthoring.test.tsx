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

  it("lists status and gives editors Schedule and Edit links", async () => {
    server.on("GET", LIST, {
      body: [item("s1", 1), item("s2", 2, { play_status: "scheduled", scheduled_for: "2026-10-12T19:30:00Z" })],
    })
    openApp("/app/mundivita/sessions")
    expect(await screen.findByRole("link", { name: "Schedule a session" })).toHaveAttribute(
      "href",
      "/app/mundivita/sessions/new",
    )
    expect(await screen.findByText("Scheduled")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Edit Session 1" })).toHaveAttribute(
      "href",
      "/app/mundivita/sessions/s1/edit",
    )
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

  it("edits with the version it saw and keeps the values on a stale save", async () => {
    server.on("GET", `${LIST}/s1`, { body: detail() })
    server.on("POST", `${LIST}/s1/update`, {
      status: 409,
      body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
    })
    openApp("/app/mundivita/sessions/s1/edit")
    const title = await screen.findByLabelText("Title")
    expect(title).toHaveValue("Session 1")
    fireEvent.change(title, { target: { value: "Renamed" } })
    fireEvent.click(screen.getByRole("button", { name: "Save session" }))
    expect(await screen.findByRole("button", { name: "Load latest version" })).toBeInTheDocument()
    expect(server.callsTo("POST", `${LIST}/s1/update`)[0]!.body).toMatchObject({
      title: "Renamed",
      expected_row_version: 2,
    })
    expect(screen.getByLabelText("Title")).toHaveValue("Renamed")
  })

  it("disables the planned start once the session has started and explains why", async () => {
    server.on("GET", `${LIST}/s1`, {
      body: detail({
        started_at: "2026-10-12T19:30:00Z",
        play_status: "in_progress",
        available_actions: ["update"],
      }),
    })
    openApp("/app/mundivita/sessions/s1/edit")
    expect(await screen.findByLabelText("Planned start")).toBeDisabled()
    expect(screen.getByText(/has started, so its planned start cannot change/)).toBeInTheDocument()
    expect(screen.getByText("End the session before archiving it.")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Archive session" })).toBeNull()
  })

  it("archives after a confirmation", async () => {
    server.on("GET", `${LIST}/s1`, { body: detail() })
    server.on("POST", `${LIST}/s1/archive`, {
      body: { session_id: "s1", session_number: 1, row_version: 3, created: false, changed: true },
    })
    openApp("/app/mundivita/sessions/s1/edit")
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

  it("offers Restore for an archived session and requires a reason", async () => {
    server.on("GET", `${LIST}/s1`, {
      body: detail({ status_code: "archived", available_actions: ["restore"] }),
    })
    openApp("/app/mundivita/sessions/s1/edit")
    expect(await screen.findByText(/archived and cannot be edited/)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Save session" })).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "Restore session" }))
    const dialog = await screen.findByRole("dialog", { name: "Restore this session?" })
    fireEvent.click(within(dialog).getByRole("button", { name: "Restore session" }))
    expect(await within(dialog).findByText("Enter a reason.")).toBeInTheDocument()
    expect(server.callsTo("POST", /./)).toHaveLength(0)
  })

  it("denies the schedule form to a member who cannot edit canon", async () => {
    openApp("/app/mundivita/sessions/new", ["campaign.view"])
    expect(await screen.findByRole("alert")).toHaveTextContent("do not have permission")
  })
})
