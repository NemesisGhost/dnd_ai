import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const LIST = "/campaigns/mundivita/parties"

const party = (id: string, name: string, status = "active", editor = true) => ({
  party_id: id,
  name,
  description: null,
  lifecycle_status: status,
  row_version: 2,
  ...(editor
    ? { available_actions: status === "active" ? ["update", "archive"] : ["restore"] }
    : {}),
})

let server: MockServer

beforeEach(() => {
  server = installCampaignShellMocks()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("party pages", () => {
  it("lists parties for a member with no editing controls", async () => {
    server.on("GET", /\/campaigns\/mundivita\/parties(\?.*)?$/, {
      body: { can_create: false, items: [party("p1", "The Company", "active", false)] },
    })
    openApp("/app/mundivita/parties", ["campaign.view"])
    expect(await screen.findByRole("heading", { level: 1, name: "Parties" })).toBeInTheDocument()
    expect(screen.getAllByRole("main")).toHaveLength(1)
    expect(await screen.findByText("The Company")).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "New party" })).toBeNull()
    expect(screen.queryByRole("button", { name: /Archive/ })).toBeNull()
  })

  it("offers editors New party, Edit, and Archive, and shows archived ones on request", async () => {
    server.on("GET", /\/campaigns\/mundivita\/parties\?include_archived=true$/, {
      body: {
        can_create: true,
        items: [party("p1", "The Company"), party("p2", "Old Crew", "archived")],
      },
    })
    server.on("GET", LIST, {
      body: { can_create: true, items: [party("p1", "The Company")] },
    })
    openApp("/app/mundivita/parties")
    expect(await screen.findByRole("link", { name: "New party" })).toHaveAttribute(
      "href",
      "/app/mundivita/parties/new",
    )
    expect(screen.getByRole("link", { name: "Edit The Company" })).toHaveAttribute(
      "href",
      "/app/mundivita/parties/p1/edit",
    )
    expect(screen.queryByText("Old Crew")).toBeNull()
    fireEvent.click(screen.getByLabelText("Show archived parties"))
    expect(await screen.findByText("Old Crew")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Restore Old Crew" })).toBeInTheDocument()
  })

  it("archives after a confirmation, sending the version seen and an idempotency key", async () => {
    let items = [party("p1", "The Company")]
    server.on("GET", LIST, () => ({ body: { can_create: true, items } }))
    server.on("POST", `${LIST}/p1/archive`, () => {
      items = []
      return {
        body: { party_id: "p1", row_version: 3, created: false, changed: true },
      }
    })
    openApp("/app/mundivita/parties")
    fireEvent.click(await screen.findByRole("button", { name: "Archive The Company" }))
    expect(server.callsTo("POST", /./)).toHaveLength(0)
    const dialog = await screen.findByRole("dialog", { name: "Archive this party?" })
    fireEvent.click(within(dialog).getByRole("button", { name: "Archive party" }))
    await waitFor(() => expect(server.callsTo("POST", `${LIST}/p1/archive`)).toHaveLength(1))
    const [call] = server.callsTo("POST", `${LIST}/p1/archive`)
    expect(call!.body).toEqual({ expected_row_version: 2, reason: null })
    expect(call!.headers["Idempotency-Key"]).toBeTruthy()
    await waitFor(() =>
      expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Party archived"),
    )
  })

  it("requires a reason to restore and sends nothing without one", async () => {
    server.on("GET", /\/campaigns\/mundivita\/parties(\?.*)?$/, {
      body: { can_create: true, items: [party("p2", "Old Crew", "archived")] },
    })
    openApp("/app/mundivita/parties")
    fireEvent.click(await screen.findByRole("button", { name: "Restore Old Crew" }))
    const dialog = await screen.findByRole("dialog", { name: "Restore this party?" })
    fireEvent.click(within(dialog).getByRole("button", { name: "Restore party" }))
    expect(await within(dialog).findByText("Enter a reason.")).toBeInTheDocument()
    expect(server.callsTo("POST", /./)).toHaveLength(0)
  })

  it("creates a party from the form and validates the name first", async () => {
    server.on("GET", LIST, { body: { can_create: true, items: [] } })
    server.on("POST", LIST, {
      status: 201,
      body: { party_id: "p9", row_version: 1, created: true, changed: true },
    })
    openApp("/app/mundivita/parties/new")
    expect(await screen.findByRole("heading", { level: 1, name: "New party" })).toBeInTheDocument()
    fireEvent.click(await screen.findByRole("button", { name: "Create party" }))
    expect((await screen.findAllByText(/Name is required|Enter a name|required/i)).length).toBeGreaterThan(0)
    expect(server.callsTo("POST", /./)).toHaveLength(0)
    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: "The Crew" } })
    fireEvent.click(screen.getByRole("button", { name: "Create party" }))
    await waitFor(() => expect(server.callsTo("POST", LIST)).toHaveLength(1))
    expect(server.callsTo("POST", LIST)[0]!.body).toEqual({ name: "The Crew", description: null })
  })

  it("keeps the edit form and offers the latest version on a stale save", async () => {
    server.on("GET", `${LIST}/p1`, { body: party("p1", "The Company") })
    server.on("POST", `${LIST}/p1/update`, {
      status: 409,
      body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
    })
    openApp("/app/mundivita/parties/p1/edit")
    const name = await screen.findByLabelText(/Name/)
    fireEvent.change(name, { target: { value: "The Crew" } })
    fireEvent.click(screen.getByRole("button", { name: "Save party" }))
    expect(await screen.findByRole("button", { name: "Load latest version" })).toBeInTheDocument()
    expect(server.callsTo("POST", `${LIST}/p1/update`)[0]!.body).toEqual({
      name: "The Crew",
      description: null,
      expected_row_version: 2,
    })
    expect(screen.getByLabelText(/Name/)).toHaveValue("The Crew")
  })

  it("reports a confirmed archive whose list re-read fails, holds the row, and recovers by reading only", async () => {
    let items = [party("p1", "The Company")]
    let listFails = false
    server.on("GET", LIST, () =>
      listFails ? { status: 500, body: {} } : { body: { can_create: true, items } },
    )
    server.on("POST", `${LIST}/p1/archive`, () => {
      items = []
      listFails = true
      return { body: { party_id: "p1", row_version: 3, created: false, changed: true } }
    })
    openApp("/app/mundivita/parties")
    fireEvent.click(await screen.findByRole("button", { name: "Archive The Company" }))
    const dialog = await screen.findByRole("dialog", { name: "Archive this party?" })
    fireEvent.click(within(dialog).getByRole("button", { name: "Archive party" }))

    // Saved, not "done": the notice says the list is behind, the row stays but is held.
    expect(await screen.findByText(/Party archived\. The latest party list could not be loaded/)).toBeInTheDocument()
    expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Saved, but the latest data could not be loaded.")
    expect(screen.getByTestId("authoring-announcer")).not.toHaveTextContent("Party archived")
    expect(screen.getByText("The Company")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Archive The Company" })).toBeDisabled()

    // The page's own retry reads again; it never sends the archive a second time, and the first
    // read that works also completes the archive.
    listFails = false
    fireEvent.click(screen.getByRole("button", { name: "Try again" }))
    await waitFor(() => expect(screen.queryByText("The Company")).toBeNull())
    await waitFor(() => expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Party archived"))
    expect(screen.queryByText(/could not be loaded/)).toBeNull()
    expect(server.callsTo("POST", `${LIST}/p1/archive`)).toHaveLength(1)
  })

  it("says an archived or missing party cannot be edited", async () => {
    server.on("GET", `${LIST}/p2`, { body: party("p2", "Old Crew", "archived") })
    openApp("/app/mundivita/parties/p2/edit")
    expect(await screen.findByRole("alert")).toHaveTextContent("cannot be edited right now")
  })
})
