import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const OPTIONS = {
  can_create: true,
  species: [{ species_id: "sp-human", name: "Human", ruleset_name: "D&D 5e" }],
  sizes: [{ code: "medium", label: "Medium" }],
  limits: { name_max_length: 200, summary_max_length: 4000, text_max_length: 4000, change_note_max_length: 1000 },
}
const NEW = "/app/mundivita/characters/new"
const ALL = "/app/mundivita/characters/all"
const FROM = "/app/mundivita/characters/all?type=npc&q=mira"

let server: MockServer

// The sidebar also has Characters and World links; the breadcrumb is in the page.
const page = () => within(screen.getByRole("main"))

beforeEach(() => {
  server = installCampaignShellMocks()
  server.on("GET", "/campaigns/mundivita/authoring/npcs/options", { body: OPTIONS })
  server.on("GET", "/campaigns/mundivita/authoring/player-characters/options", { body: OPTIONS })
  server.on("GET", /\/campaigns\/mundivita\/parties(\?.*)?$/, { body: { can_create: true, items: [] } })
})

describe("Parties list is the top-level Parties destination", () => {
  it("has no Campaign Home breadcrumb", async () => {
    openApp("/app/mundivita/parties", ["campaign.edit", "canon.edit"])
    await screen.findByRole("heading", { level: 1, name: "Parties" })
    const main = screen.getByRole("main")
    expect(within(main).queryByRole("link", { name: "Campaign Home" })).toBeNull()
    expect(main.querySelector(".authoring-page__breadcrumb")).toBeNull()
  })

  it("keeps the New party page returning to Parties", async () => {
    openApp("/app/mundivita/parties/new", ["campaign.edit", "canon.edit"])
    await screen.findByRole("heading", { level: 1, name: /New party/ })
    expect(page().getByRole("link", { name: "Parties" })).toHaveAttribute(
      "href",
      "/app/mundivita/parties",
    )
  })
})

describe("New character breadcrumb", () => {
  it("falls back to the characters browser when opened directly", async () => {
    openApp(NEW, ["canon.edit"])
    await screen.findByRole("heading", { level: 1, name: "New character" })
    const main = screen.getByRole("main")
    expect(page().getByRole("link", { name: "Characters" })).toHaveAttribute("href", ALL)
    fireEvent.click(within(main).getByRole("link", { name: "New NPC" }))
    await screen.findByRole("heading", { level: 1, name: "New NPC" })
    expect(page().getByRole("link", { name: "World" })).toHaveAttribute("href", "/app/mundivita/world")
  })

  it("returns to the validated Characters view and forwards it to the NPC and PC pages", async () => {
    const app = openApp(NEW, ["canon.edit"])
    await screen.findByRole("heading", { level: 1, name: "New character" })
    await act(() => app.router.navigate(NEW, { state: { charactersReturn: FROM } }))
    const main = screen.getByRole("main")
    await waitFor(() => expect(page().getByRole("link", { name: "Characters" })).toHaveAttribute("href", FROM))

    fireEvent.click(within(main).getByRole("link", { name: "New NPC" }))
    await screen.findByRole("heading", { level: 1, name: "New NPC" })
    expect(app.router.state.location.state).toMatchObject({ charactersReturn: FROM })
    expect(page().getByRole("link", { name: "Characters" })).toHaveAttribute("href", FROM)
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }))
    await waitFor(() =>
      expect(app.router.state.location.pathname + app.router.state.location.search).toBe(FROM),
    )

    await act(() => app.router.navigate(NEW, { state: { charactersReturn: FROM } }))
    await screen.findByRole("heading", { level: 1, name: "New character" })
    fireEvent.click(await screen.findByRole("link", { name: "New player character" }))
    await screen.findByRole("heading", { level: 1, name: "New player character" })
    expect(app.router.state.location.state).toMatchObject({ charactersReturn: FROM })
    expect(page().getByRole("link", { name: "Characters" })).toHaveAttribute("href", FROM)
  })

  it.each([
    ["another campaign", "/app/other/characters/all"],
    ["a parent traversal", "/app/mundivita/characters/../world"],
    ["an external address", "https://example.com/app/mundivita/characters"],
    ["a protocol-relative address", "//evil.example/app/mundivita/characters"],
    ["a sibling prefix", "/app/mundivita/characters-secret"],
    ["encoded dot segments into another campaign", "/app/mundivita/characters/%2e%2e/%2e%2e/other/characters/all"],
    ["mixed-case encoded dot segments", "/app/mundivita/characters/%2E%2e/%2e%2E/other/characters/all"],
    ["an encoded separator", "/app/mundivita/characters%2f..%2f..%2fother/characters/all"],
    ["a creation route in another casing", "/app/mundivita/characters/New"],
    ["a doubly encoded separator in an id", "/app/mundivita/characters/a%252Fb"],
  ])("ignores a crafted return from %s", async (_name, crafted) => {
    const app = openApp(NEW, ["canon.edit"])
    await screen.findByRole("heading", { level: 1, name: "New character" })
    await act(() => app.router.navigate(NEW, { state: { charactersReturn: crafted } }))
    const main = screen.getByRole("main")
    await waitFor(() => expect(app.router.state.location.state).toMatchObject({ charactersReturn: crafted }))
    expect(page().getByRole("link", { name: "Characters" })).toHaveAttribute("href", ALL)

    fireEvent.click(within(main).getByRole("link", { name: "New NPC" }))
    await screen.findByRole("heading", { level: 1, name: "New NPC" })
    expect(app.router.state.location.state).not.toHaveProperty("charactersReturn")
    expect(page().getByRole("link", { name: "World" })).toHaveAttribute("href", "/app/mundivita/world")

    // Where the crafted state would actually have led stays inside the campaign.
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }))
    await screen.findByRole("heading", { level: 1, name: "Campaign World" })
    expect(app.router.state.location.pathname).toBe("/app/mundivita/world")
  })

  it.each([
    ["encoded dot segments", "/app/mundivita/characters/%2e%2e/%2e%2e/other/characters/all"],
    ["mixed-case encoded dot segments", "/app/mundivita/characters/%2E%2e/%2e%2E/other/characters/all"],
  ])("never navigates out of the campaign through the chooser breadcrumb (%s)", async (_name, crafted) => {
    const app = openApp(NEW, ["canon.edit"])
    await screen.findByRole("heading", { level: 1, name: "New character" })
    await act(() => app.router.navigate(NEW, { state: { charactersReturn: crafted } }))
    await waitFor(() => expect(app.router.state.location.state).toMatchObject({ charactersReturn: crafted }))
    const href = page().getByRole("link", { name: "Characters" }).getAttribute("href") ?? ""
    expect(new URL(href, "http://x.invalid").pathname).toBe(ALL)
    fireEvent.click(page().getByRole("link", { name: "Characters" }))
    await waitFor(() => expect(app.router.state.location.pathname).toBe(ALL))
  })

  it("keeps World as the NPC breadcrumb when reached from World People", async () => {
    openApp("/app/mundivita/characters/npc/new", ["canon.edit"])
    await screen.findByRole("heading", { level: 1, name: "New NPC" })
    expect(page().getByRole("link", { name: "World" })).toHaveAttribute("href", "/app/mundivita/world")
    expect(page().queryByRole("link", { name: "Characters" })).toBeNull()
  })
})
