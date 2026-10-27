import { act, fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { useSessionBootstrap } from "./hooks/useSessionBootstrap"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockResponse, MockServer } from "./test/authoringHarness"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

// Recovery of the reads that back one page (docs/UI_DESIGN.md §5.11): every required read that fails
// has a way back, the closed answers keep their order (404, then 403, then failure), a retry only
// reads, and a retry that replaces the control holding focus hands focus on.

const err = (status: number, code = "x"): MockResponse => ({
  status,
  body: { error: { code, message: "m", correlation_id: "c" } },
})
const BROKEN = err(500, "internal")
const FORBIDDEN = err(403, "forbidden")
const MISSING = err(404, "not_found")

const E = "/campaigns/mundivita/events/e1"
const PREVIEW = `${E}/correction-preview`

const eventBody: MockResponse = {
  body: {
    event_id: "e1",
    name: "Mira is hurt",
    event_type_code: "hit_points_adjusted",
    status: "recorded",
    world_time_id: "t1",
    world_time: "Year 1",
    session_id: null,
    details: null,
    participants: [],
    effects: [
      { component: "current_hit_points", target_entity_id: "c1", previous: 20, new: 13, application_status: "applied" },
    ],
    correction: null,
    corrects_event_id: null,
  },
}
const previewBody: MockResponse = {
  body: {
    event_id: "e1",
    status: "recorded",
    can_correct: true,
    is_correction: false,
    effects: [{ component: "current_hit_points", target_entity_id: "c1", reversible: true, reason: null }],
  },
}

let server: MockServer
// What each read answers next; a test changes these between attempts.
let eventAnswer: MockResponse | Promise<MockResponse>
let previewAnswer: MockResponse | Promise<MockResponse>

beforeEach(() => {
  server = installCampaignShellMocks()
  server.on("GET", /\/campaigns\/mundivita\/world-times/, { body: { items: [], next_cursor: null } })
  server.on("GET", "/campaigns/mundivita/calendars", { body: { calendars: [] } })
  eventAnswer = eventBody
  previewAnswer = previewBody
  server.on("GET", E, () => Promise.resolve(eventAnswer))
  server.on("GET", PREVIEW, () => Promise.resolve(previewAnswer))
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.title = "portal"
})

const reads = (path: string) => server.callsTo("GET", path).length
const nonGet = () => server.calls.filter((call) => call.method !== "GET")
const tryAgain = () => screen.getByRole("button", { name: /Try again|Loading…/ })
const PREVIEW_FAILED = "The correction options for this event could not be loaded."

describe("event page: the event and its correction check", () => {
  it("recovers a failed event read alone, reading only the event again", async () => {
    eventAnswer = BROKEN
    openApp("/app/mundivita/events/e1")
    await screen.findByText("The event could not be loaded.")
    const [eventReads, previewReads] = [reads(E), reads(PREVIEW)]
    eventAnswer = eventBody
    fireEvent.click(tryAgain())
    expect(await screen.findByRole("button", { name: "Void event" })).toBeEnabled()
    expect(reads(E)).toBe(eventReads + 1)
    expect(reads(PREVIEW)).toBe(previewReads)
    expect(nonGet()).toEqual([])
  })

  it("keeps the event and says the correction check is missing, then recovers the controls", async () => {
    previewAnswer = BROKEN
    openApp("/app/mundivita/events/e1")
    expect(await screen.findByRole("heading", { level: 1, name: "Mira is hurt" })).toBeInTheDocument()
    expect(await screen.findByText(PREVIEW_FAILED)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Void event" })).toBeNull()
    // The page itself is working, so its title is not replaced by the panel's failure.
    expect(document.title).not.toBe("Could not load · portal")
    const [eventReads, previewReads] = [reads(E), reads(PREVIEW)]
    previewAnswer = previewBody
    fireEvent.click(tryAgain())
    expect(await screen.findByRole("button", { name: "Void event" })).toBeEnabled()
    expect(screen.queryByText(PREVIEW_FAILED)).toBeNull()
    expect(reads(E)).toBe(eventReads)
    expect(reads(PREVIEW)).toBe(previewReads + 1)
    expect(await screen.findByText(/Hit points: 20 to 13 \(can be reversed\)/)).toBeInTheDocument()
    expect(nonGet()).toEqual([])
  })

  it("recovers both reads failing together, through a partial recovery", async () => {
    eventAnswer = BROKEN
    previewAnswer = BROKEN
    openApp("/app/mundivita/events/e1")
    await screen.findByText("The event could not be loaded.")
    // The event comes back, the check does not: the page opens with the missing check explained.
    eventAnswer = eventBody
    fireEvent.click(tryAgain())
    expect(await screen.findByText(PREVIEW_FAILED)).toBeInTheDocument()
    expect(screen.getByRole("heading", { level: 1, name: "Mira is hurt" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Void event" })).toBeNull()
    previewAnswer = previewBody
    fireEvent.click(tryAgain())
    expect(await screen.findByRole("button", { name: "Void event" })).toBeEnabled()
    expect(nonGet()).toEqual([])
  })

  it("retries only the read that failed when both were asked", async () => {
    eventAnswer = BROKEN
    previewAnswer = BROKEN
    openApp("/app/mundivita/events/e1")
    await screen.findByText("The event could not be loaded.")
    const [eventReads, previewReads] = [reads(E), reads(PREVIEW)]
    fireEvent.click(tryAgain())
    await waitFor(() => expect(reads(E)).toBe(eventReads + 1))
    expect(reads(PREVIEW)).toBe(previewReads + 1)
  })

  it("never treats a refused or missing check as a retryable failure", async () => {
    previewAnswer = FORBIDDEN
    const first = openApp("/app/mundivita/events/e1")
    expect(await screen.findByText("You do not have access to the correction options for this event.")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Try again/ })).toBeNull()
    expect(screen.queryByRole("button", { name: "Void event" })).toBeNull()
    first.unmount()

    previewAnswer = MISSING
    openApp("/app/mundivita/events/e1")
    expect(
      await screen.findByText("The correction options for this event is not available, or you can no longer access it."),
    ).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Try again/ })).toBeNull()
  })

  it("answers a 404 before a 403 before a failure when the reads disagree", async () => {
    eventAnswer = BROKEN
    previewAnswer = MISSING
    const first = openApp("/app/mundivita/events/e1")
    expect(await screen.findByText("The event is not available, or you can no longer access it.")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Try again/ })).toBeNull()
    await waitFor(() => expect(document.title).toBe("Not available · portal"))
    first.unmount()

    previewAnswer = FORBIDDEN
    openApp("/app/mundivita/events/e1")
    expect(await screen.findByText("You do not have access to the event.")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Try again/ })).toBeNull()
  })

  it("does not show one event's failed check on the next event", async () => {
    previewAnswer = BROKEN
    const { router } = openApp("/app/mundivita/events/e1")
    await screen.findByText(PREVIEW_FAILED)
    server.on("GET", "/campaigns/mundivita/events/e2", {
      body: { ...(eventBody.body as object), event_id: "e2", name: "Mira is healed" },
    })
    server.on("GET", "/campaigns/mundivita/events/e2/correction-preview", {
      body: { ...(previewBody.body as object), event_id: "e2" },
    })
    await act(async () => {
      await router.navigate("/app/mundivita/events/e2")
    })
    expect(await screen.findByRole("heading", { level: 1, name: "Mira is healed" })).toBeInTheDocument()
    expect(await screen.findByRole("button", { name: "Void event" })).toBeEnabled()
    expect(screen.queryByText(PREVIEW_FAILED)).toBeNull()
  })

  it("lets the session boundary take over on a 401 during a retry, without showing stale content", async () => {
    eventAnswer = BROKEN
    openApp("/app/mundivita/events/e1")
    await screen.findByText("The event could not be loaded.")
    eventAnswer = err(401, "unauthenticated")
    fireEvent.click(tryAgain())
    await waitFor(() => expect(vi.mocked(useSessionBootstrap)().reload).toHaveBeenCalled())
    expect(screen.queryByRole("button", { name: "Void event" })).toBeNull()
  })
})

describe("retry focus", () => {
  it("keeps focus on the retry button while it reads, and on repeated failure", async () => {
    eventAnswer = BROKEN
    previewAnswer = BROKEN
    openApp("/app/mundivita/events/e1")
    await screen.findByText("The event could not be loaded.")
    let release: (r: MockResponse) => void = () => {}
    eventAnswer = new Promise<MockResponse>((resolve) => (release = resolve))
    tryAgain().focus()
    fireEvent.click(tryAgain())
    const busy = await screen.findByRole("button", { name: "Loading…" })
    expect(busy).toHaveFocus()
    expect(busy).toHaveAttribute("aria-disabled", "true")
    release(BROKEN)
    const again = await screen.findByRole("button", { name: "Try again" })
    expect(again).toHaveFocus()
  })

  it("moves focus to the page heading when the retry succeeds and removes the focused button", async () => {
    eventAnswer = BROKEN
    previewAnswer = BROKEN
    openApp("/app/mundivita/events/e1")
    await screen.findByText("The event could not be loaded.")
    eventAnswer = eventBody
    previewAnswer = previewBody
    tryAgain().focus()
    fireEvent.click(tryAgain())
    const heading = await screen.findByRole("heading", { level: 1, name: "Mira is hurt" })
    await waitFor(() => expect(heading).toHaveFocus())
    expect(document.activeElement).not.toBe(document.body)
  })

  it("hands focus on from the degraded panel's retry too", async () => {
    previewAnswer = BROKEN
    openApp("/app/mundivita/events/e1")
    await screen.findByText(PREVIEW_FAILED)
    previewAnswer = previewBody
    tryAgain().focus()
    fireEvent.click(tryAgain())
    await screen.findByRole("button", { name: "Void event" })
    await waitFor(() => expect(screen.getByRole("heading", { level: 1, name: "Mira is hurt" })).toHaveFocus())
  })

  it("does not take focus back after the person moved elsewhere", async () => {
    eventAnswer = BROKEN
    previewAnswer = BROKEN
    openApp("/app/mundivita/events/e1")
    await screen.findByText("The event could not be loaded.")
    let release: (r: MockResponse) => void = () => {}
    eventAnswer = new Promise<MockResponse>((resolve) => (release = resolve))
    previewAnswer = previewBody
    tryAgain().focus()
    fireEvent.click(tryAgain())
    await screen.findByRole("button", { name: "Loading…" })
    const elsewhere = screen.getAllByRole("link", { name: "Campaign Home" })[0]!
    elsewhere.focus()
    release(eventBody)
    await screen.findByRole("heading", { level: 1, name: "Mira is hurt" })
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(elsewhere).toHaveFocus()
  })
})
