import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const E = "/campaigns/mundivita/events/e1"

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

const view = (extra: Record<string, unknown> = {}) => ({
  event_id: "e1",
  name: "Mira is hurt",
  event_type_code: "hit_points_adjusted",
  status: "recorded",
  world_time_id: "t1",
  world_time: "Year 1",
  session_id: null,
  details: "Fell from the wall",
  participants: [{ entity_id: "c1", name: "Mira", role: "actor" }],
  effects: [
    { component: "current_hit_points", target_entity_id: "c1", previous: 20, new: 13, application_status: "applied" },
  ],
  correction: null,
  corrects_event_id: null,
  ...extra,
})

const preview = (extra: Record<string, unknown> = {}) => ({
  event_id: "e1",
  status: "recorded",
  can_correct: true,
  is_correction: false,
  effects: [{ component: "current_hit_points", target_entity_id: "c1", reversible: true, reason: null }],
  ...extra,
})

let server: MockServer

beforeEach(() => {
  server = installCampaignShellMocks()
  server.on("GET", /\/campaigns\/mundivita\/world-times/, {
    body: { items: [TIME("t2", "Year 2"), TIME("t1", "Year 1")], next_cursor: null },
  })
  server.on("GET", "/campaigns/mundivita/calendars", { body: { calendars: [] } })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("event pages", () => {
  it("shows an event with what it changed and whether that can be reversed", async () => {
    server.on("GET", E, { body: view() })
    server.on("GET", `${E}/correction-preview`, { body: preview() })
    openApp("/app/mundivita/events/e1")
    expect(await screen.findByRole("heading", { level: 1, name: "Mira is hurt" })).toBeInTheDocument()
    expect(screen.getAllByRole("main")).toHaveLength(1)
    expect(await screen.findByText(/Hit points: 20 to 13 \(can be reversed\)/)).toBeInTheDocument()
    expect(screen.getByText(/GM notes: Fell from the wall/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Void event" })).toBeEnabled()
  })

  it("explains why an event cannot be corrected and disables the actions", async () => {
    server.on("GET", E, { body: view() })
    server.on("GET", `${E}/correction-preview`, {
      body: preview({
        can_correct: false,
        effects: [{ component: "current_hit_points", target_entity_id: "c1", reversible: false, reason: "state_changed" }],
      }),
    })
    openApp("/app/mundivita/events/e1")
    expect(await screen.findByText(/cannot be corrected automatically: what it changed has changed since/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Void event" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "Correct event" })).toBeDisabled()
  })

  it("voids after a confirmation that requires a reason", async () => {
    let state = view()
    server.on("GET", E, () => ({ body: state }))
    server.on("GET", `${E}/correction-preview`, () => ({ body: preview({ status: state.status }) }))
    server.on("POST", `${E}/void`, () => {
      state = view({
        status: "voided",
        correction: { kind: "void", reason: "Entered twice", correcting_event_id: "e2", replacement_event_id: null },
      })
      return { body: { event_id: "e1", status: "voided", correction_id: "k1", correcting_event_id: "e2" } }
    })
    openApp("/app/mundivita/events/e1")
    fireEvent.click(await screen.findByRole("button", { name: "Void event" }))
    const dialog = await screen.findByRole("dialog", { name: "Void this event?" })
    fireEvent.click(within(dialog).getByRole("button", { name: "Void event" }))
    expect(await within(dialog).findByText("Enter a reason.")).toBeInTheDocument()
    expect(server.callsTo("POST", /./)).toHaveLength(0)
    fireEvent.change(within(dialog).getByLabelText(/Reason/), { target: { value: "Entered twice" } })
    fireEvent.click(within(dialog).getByRole("button", { name: "Void event" }))
    await waitFor(() => expect(server.callsTo("POST", `${E}/void`)).toHaveLength(1))
    const [call] = server.callsTo("POST", `${E}/void`)
    expect(call!.body).toEqual({ reason: "Entered twice" })
    expect(call!.headers["Idempotency-Key"]).toBeTruthy()
    expect(await screen.findByText(/This event was voided: Entered twice/)).toBeInTheDocument()
  })

  it("corrects with a replacement and shows a refusal inside the dialog", async () => {
    server.on("GET", E, { body: view({ event_type_code: "other", effects: [] }) })
    server.on("GET", `${E}/correction-preview`, { body: preview({ effects: [] }) })
    server.on("POST", `${E}/correct`, {
      status: 409,
      body: { error: { code: "correction_not_reversible", message: "m", correlation_id: "c" } },
    })
    openApp("/app/mundivita/events/e1")
    fireEvent.click(await screen.findByRole("button", { name: "Correct event" }))
    const dialog = await screen.findByRole("dialog", { name: "Correct this event?" })
    fireEvent.change(within(dialog).getByLabelText(/Reason/), { target: { value: "Wrong person" } })
    fireEvent.change(within(dialog).getByLabelText(/What really happened/), {
      target: { value: "Bryn is hurt" },
    })
    fireEvent.click(within(dialog).getByRole("button", { name: "Correct event" }))
    await waitFor(() => expect(server.callsTo("POST", `${E}/correct`)).toHaveLength(1))
    expect(server.callsTo("POST", `${E}/correct`)[0]!.body).toEqual({
      reason: "Wrong person",
      replacement: { event_type_code: "other", name: "Bryn is hurt", details: "Fell from the wall", world_time_id: null },
    })
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("cannot be corrected automatically")
  })

  it("shows a correction as such with links, and offers no actions", async () => {
    server.on("GET", E, {
      body: view({
        status: "corrected",
        correction: { kind: "correct", reason: "Wrong person", correcting_event_id: "e2", replacement_event_id: "e3" },
      }),
    })
    server.on("GET", `${E}/correction-preview`, { body: preview({ status: "corrected", can_correct: false }) })
    openApp("/app/mundivita/events/e1")
    expect(await screen.findByText(/This event was corrected: Wrong person/)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "The replacement" })).toHaveAttribute(
      "href",
      "/app/mundivita/events/e3",
    )
    expect(screen.queryByRole("button", { name: "Void event" })).toBeNull()
  })

  it("records an event after validating, with an idempotency key", async () => {
    server.on("POST", "/campaigns/mundivita/events", {
      status: 201,
      body: { event_id: "e9" },
    })
    server.on("GET", "/campaigns/mundivita/events/e9", { body: view({ event_id: "e9", name: "The door opens", effects: [], event_type_code: "other" }) })
    server.on("GET", "/campaigns/mundivita/events/e9/correction-preview", { body: preview({ event_id: "e9", effects: [] }) })
    openApp("/app/mundivita/events/new")
    expect(await screen.findByRole("heading", { level: 1, name: "Record an event" })).toBeInTheDocument()
    fireEvent.click(await screen.findByRole("button", { name: "Record event" }))
    expect((await screen.findAllByText("Enter what happened.")).length).toBeGreaterThan(0)
    expect(server.callsTo("POST", /./)).toHaveLength(0)
    fireEvent.change(screen.getByLabelText(/What happened/), { target: { value: "The door opens" } })
    fireEvent.change(await screen.findByRole("combobox", { name: /When/ }), { target: { value: "t1" } })
    fireEvent.click(screen.getByRole("button", { name: "Record event" }))
    await waitFor(() => expect(server.callsTo("POST", "/campaigns/mundivita/events")).toHaveLength(1))
    expect(server.callsTo("POST", "/campaigns/mundivita/events")[0]!.body).toEqual({
      world_time_id: "t1",
      event_type_code: "other",
      name: "The door opens",
      details: null,
    })
    expect(await screen.findByRole("heading", { level: 1, name: "The door opens" })).toBeInTheDocument()
  })

  it("denies the pages to a member who cannot edit canon", async () => {
    openApp("/app/mundivita/events/e1", ["campaign.view"])
    expect(await screen.findByRole("alert")).toHaveTextContent("do not have permission")
  })
})
