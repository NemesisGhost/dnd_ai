import { act, fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

// The unavailable/unauthorized presentation policy on the campaign pages (docs/UI_DESIGN.md,
// "Unavailable and unauthorized destinations"): a first read that fails is a failure the person can
// retry (reading only); a 403 and a 404 are closed, and a missing and a hidden record read alike.

const err = (status: number, code: string, message = "m") => ({
  status,
  body: { error: { code, message, correlation_id: "c" } },
})
const SERVER_ERROR = err(500, "internal")
const FORBIDDEN = err(403, "forbidden")
const NOT_FOUND = err(404, "not_found")
const HIDDEN = err(404, "not_found", "a different message for a record the person may not see")

interface Case {
  name: string
  entry: string
  capabilities: string[]
  // Wires every read the page makes on first load to one response.
  wire: (server: MockServer, response: object) => void
  what: string
  heading: string
}

const cases: Case[] = [
  {
    name: "party edit",
    entry: "/app/mundivita/parties/p1/edit",
    capabilities: ["campaign.view", "canon.edit"],
    wire: (s, r) => s.on("GET", "/campaigns/mundivita/parties/p1", r),
    what: "party",
    heading: "Edit party",
  },
  {
    name: "parties list",
    entry: "/app/mundivita/parties",
    capabilities: ["campaign.view"],
    wire: (s, r) => s.on("GET", /\/campaigns\/mundivita\/parties(\?.*)?$/, r),
    what: "list of parties",
    heading: "Parties",
  },
  {
    name: "event",
    entry: "/app/mundivita/events/e1",
    capabilities: ["campaign.view", "canon.edit"],
    wire: (s, r) => {
      s.on("GET", "/campaigns/mundivita/events/e1", r)
      s.on("GET", /\/campaigns\/mundivita\/events\/e1\/correction-preview/, r)
    },
    what: "event",
    heading: "Event",
  },
  {
    name: "run session",
    entry: "/app/mundivita/sessions/s1/run",
    capabilities: ["campaign.view", "canon.edit"],
    wire: (s, r) => s.on("GET", "/campaigns/mundivita/sessions/s1", r),
    what: "session",
    heading: "Run session",
  },
  {
    name: "prepared encounter",
    entry: "/app/mundivita/sessions/s1/encounters/e1",
    capabilities: ["campaign.view", "canon.edit"],
    wire: (s, r) => {
      s.on("GET", "/campaigns/mundivita/authoring/encounters/e1", r)
      s.on("GET", "/campaigns/mundivita/authoring/encounters/options", r)
      s.on("GET", "/campaigns/mundivita/sessions/s1", { body: {} })
    },
    what: "encounter",
    heading: "Encounter",
  },
  {
    name: "world times",
    entry: "/app/mundivita/world-times",
    capabilities: ["campaign.view", "canon.edit"],
    wire: (s, r) => {
      s.on("GET", /\/campaigns\/mundivita\/world-times/, r)
      s.on("GET", "/campaigns/mundivita/calendars", r)
    },
    what: "world times",
    heading: "World times",
  },
]

let server: MockServer

beforeEach(() => {
  server = installCampaignShellMocks()
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.title = "portal"
})

// The page's own output: its heading, the notice and the links around it (not the shell's generated ids).
const page = () => screen.getByRole("alert").parentElement!.textContent

const nonGet = () => server.calls.filter((call) => call.method !== "GET")

describe.each(cases)("$name: first-read states", (c) => {
  it("shows a safe failure with a read-only retry for a 5xx", async () => {
    c.wire(server, SERVER_ERROR)
    openApp(c.entry, c.capabilities)
    expect(await screen.findByText(`The ${c.what} could not be loaded.`)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { level: 1, name: c.heading })).toBeInTheDocument()
    expect(screen.getAllByRole("main")).toHaveLength(1)
    expect(document.title).toBe("Could not load · portal")
    expect(nonGet()).toEqual([])
  })

  it("retries by reading again and only reading", async () => {
    c.wire(server, SERVER_ERROR)
    openApp(c.entry, c.capabilities)
    await screen.findByText(`The ${c.what} could not be loaded.`)
    const reads = server.calls.length
    fireEvent.click(screen.getByRole("button", { name: "Try again" }))
    await waitFor(() => expect(server.calls.length).toBeGreaterThan(reads))
    expect(nonGet()).toEqual([])
  })

  it("closes on a 403 without a retry and names the refusal", async () => {
    c.wire(server, FORBIDDEN)
    openApp(c.entry, c.capabilities)
    expect(await screen.findByText(`You do not have access to the ${c.what}.`)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull()
    expect(document.title).toBe("Access denied · portal")
  })

  it("shows a missing and a hidden record identically", async () => {
    c.wire(server, NOT_FOUND)
    const first = openApp(c.entry, c.capabilities)
    expect(await screen.findByText(`The ${c.what} is not available, or you can no longer access it.`)).toBeInTheDocument()
    const missing = `${document.title}|${page()}`
    first.unmount()

    c.wire(server, HIDDEN)
    openApp(c.entry, c.capabilities)
    expect(await screen.findByText(`The ${c.what} is not available, or you can no longer access it.`)).toBeInTheDocument()
    expect(`${document.title}|${page()}`).toBe(missing)
    expect(screen.queryByText(/different message/)).toBeNull()
  })

  it("restores the title when the person navigates away", async () => {
    c.wire(server, NOT_FOUND)
    const { router } = openApp(c.entry, c.capabilities)
    await screen.findByText(`The ${c.what} is not available, or you can no longer access it.`)
    expect(document.title).toBe("Not available · portal")
    server.on("GET", /^\/campaigns\/mundivita\/(summary|home)/, { body: {} })
    await act(async () => {
      await router.navigate("/app/mundivita/parties/new")
    })
    expect(document.title).not.toBe("Not available · portal")
  })
})
