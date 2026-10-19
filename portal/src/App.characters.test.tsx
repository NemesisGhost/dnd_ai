import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { characterSheetFixture } from "./fixtures/characterSheet"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { FetchCall, MockServer } from "./test/authoringHarness"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
  recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const NOT_FOUND = {
  status: 404,
  body: { error: { code: "not_found", message: "m", correlation_id: "c" } },
}
const NO_PERSPECTIVE = { character_perspectives: [], selected_character_id: null }

const card = (id: string, name: string, type: string, extra: object = {}) => ({
  entity_id: id,
  category: "character",
  entity_type_code: type,
  name,
  summary: `${name} summary`,
  canon_status: "canon",
  lifecycle_status: "active",
  ...extra,
})
const ALL = [
  card("npc-1", "Mira", "npc"),
  card("pc-1", "Aldric", "player_character"),
  card("bare-1", "Wanderer", "character"),
]

const character = (id: string, name: string, kind: string, full = true) => ({
  character_id: id,
  name,
  character_kind: kind,
  species_code: "human",
  size_category: "medium",
  current_hit_points: full ? 9 : null,
  maximum_hit_points: full ? 12 : null,
  temporary_hit_points: full ? 0 : null,
  exhaustion_level: full ? 0 : null,
  death_save_successes: full ? 0 : null,
  death_save_failures: full ? 0 : null,
  current_location_id: null,
  active_encounter_id: null,
  conditions: full ? [] : null,
  resources: full ? [] : null,
})
const sheet = (id: string, name: string, kind: string) => ({
  ...characterSheetFixture,
  character_id: id,
  name,
  character_kind: kind,
})

let server: MockServer

const searchCalls = (): FetchCall[] =>
  server.calls.filter((c) => c.method === "GET" && c.path.startsWith("/campaigns/mundivita/world/search?"))
const lastSearch = (): URLSearchParams => {
  const calls = searchCalls()
  return new URLSearchParams(calls[calls.length - 1]!.path.split("?")[1])
}

beforeEach(() => {
  server = installCampaignShellMocks()
  // The World search honours character_type like the server: it narrows by entity type.
  server.on("GET", /^\/campaigns\/mundivita\/world\/search\?/, (call) => {
    const params = new URLSearchParams(call.path.split("?")[1])
    const type = params.get("character_type")
    const items = type === null ? ALL : ALL.filter((c) => c.entity_type_code === type)
    return { body: { items, next_cursor: null } }
  })
  server.on("GET", "/campaigns/mundivita/characters/npc-1", { body: character("npc-1", "Mira", "npc") })
  server.on("GET", "/campaigns/mundivita/characters/npc-1/sheet", {
    body: sheet("npc-1", "Mira", "npc"),
  })
  server.on("GET", "/campaigns/mundivita/characters/pc-1", {
    body: character("pc-1", "Aldric", "player_character"),
  })
  server.on("GET", "/campaigns/mundivita/characters/pc-1/sheet", {
    body: sheet("pc-1", "Aldric", "player_character"),
  })
  server.on("GET", "/campaigns/mundivita/characters/character-ixamarra", {
    body: character("character-ixamarra", "Ixamarra", "player_character"),
  })
  server.on("GET", "/campaigns/mundivita/characters/character-ixamarra/sheet", {
    body: sheet("character-ixamarra", "Ixamarra", "player_character"),
  })
  // Authoring reads that self-gate the Manage links: only an NPC answers the NPC read, and the
  // builds read answers for either buildable kind.
  server.on("GET", "/campaigns/mundivita/authoring/npcs/npc-1", { body: { npc_id: "npc-1" } })
  server.on("GET", "/campaigns/mundivita/authoring/npcs/pc-1", NOT_FOUND)
  server.on("GET", /^\/campaigns\/mundivita\/authoring\/characters\/(npc-1|pc-1)\/builds$/, {
    body: { builds: [] },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("Characters browser", () => {
  it("is the default with no perspective and labels each character's kind in text", async () => {
    openApp("/app/mundivita/characters", ["canon.edit"], NO_PERSPECTIVE)
    expect(await screen.findByRole("link", { name: "Mira, NPC" })).toHaveAttribute(
      "href",
      "/app/mundivita/characters/npc-1",
    )
    expect(screen.getByRole("link", { name: "Aldric, Player character" })).toHaveAttribute(
      "href",
      "/app/mundivita/characters/pc-1",
    )
    expect(screen.getByRole("link", { name: "Wanderer, Character" })).toBeInTheDocument()
    expect(screen.queryByText("No character selected")).toBeNull()
    expect(lastSearch().get("category")).toBe("character")
    expect(lastSearch().has("character_type")).toBe(false)
  })

  it("filters by type through the address and the server request", async () => {
    const app = openApp("/app/mundivita/characters/all", ["canon.edit"], NO_PERSPECTIVE)
    await screen.findByRole("link", { name: "Mira, NPC" })
    expect(screen.getByRole("link", { name: "All" })).toHaveAttribute("aria-current", "page")

    fireEvent.click(screen.getByRole("link", { name: "NPCs" }))
    await waitFor(() => expect(app.router.state.location.search).toBe("?type=npc"))
    await waitFor(() => expect(screen.queryByRole("link", { name: "Aldric, Player character" })).toBeNull())
    expect(screen.getByRole("link", { name: "NPCs" })).toHaveAttribute("aria-current", "page")
    expect(lastSearch().get("character_type")).toBe("npc")

    fireEvent.click(screen.getByRole("link", { name: "Player characters" }))
    await waitFor(() => expect(app.router.state.location.search).toBe("?type=player_character"))
    await screen.findByRole("link", { name: "Aldric, Player character" })
    expect(screen.queryByRole("link", { name: "Mira, NPC" })).toBeNull()
    expect(lastSearch().get("character_type")).toBe("player_character")

    fireEvent.click(screen.getByRole("link", { name: "All" }))
    await waitFor(() => expect(app.router.state.location.search).toBe(""))
    await screen.findByRole("link", { name: "Mira, NPC" })
    expect(lastSearch().has("character_type")).toBe(false)
  })

  it("restores the filter from a direct link and ignores an unknown type", async () => {
    openApp("/app/mundivita/characters/all?type=npc", ["canon.edit"], NO_PERSPECTIVE)
    await screen.findByRole("link", { name: "Mira, NPC" })
    expect(lastSearch().get("character_type")).toBe("npc")

    openApp("/app/mundivita/characters/all?type=dragon", ["canon.edit"], NO_PERSPECTIVE)
    await waitFor(() => expect(searchCalls().length).toBeGreaterThan(1))
    expect(lastSearch().has("character_type")).toBe(false)
  })

  it("searches after a short pause and keeps the search in the address", async () => {
    const app = openApp("/app/mundivita/characters/all?type=npc", ["canon.edit"], NO_PERSPECTIVE)
    await screen.findByRole("link", { name: "Mira, NPC" })
    fireEvent.change(screen.getByRole("searchbox", { name: "Search characters" }), {
      target: { value: "mir" },
    })
    await waitFor(() => expect(app.router.state.location.search).toBe("?type=npc&q=mir"))
    await waitFor(() => expect(lastSearch().get("q")).toBe("mir"))
    expect(lastSearch().get("character_type")).toBe("npc")
  })

  it("says so when nothing matches and offers to clear the search", async () => {
    server.on("GET", /^\/campaigns\/mundivita\/world\/search\?/, {
      body: { items: [], next_cursor: null },
    })
    openApp("/app/mundivita/characters/all?q=zzz", ["canon.edit"], NO_PERSPECTIVE)
    expect(await screen.findByText("No characters match “zzz”.")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Clear search" }))
    expect(await screen.findByText("No characters to show here yet.")).toBeInTheDocument()
  })

  it("shows a retryable error", async () => {
    let fail = true
    server.on("GET", /^\/campaigns\/mundivita\/world\/search\?/, () =>
      fail ? { status: 500, body: {} } : { body: { items: ALL, next_cursor: null } },
    )
    openApp("/app/mundivita/characters/all", ["canon.edit"], NO_PERSPECTIVE)
    expect(await screen.findByText("World information unavailable")).toBeInTheDocument()
    fail = false
    fireEvent.click(screen.getByRole("button", { name: "Try again" }))
    expect(await screen.findByRole("link", { name: "Mira, NPC" })).toBeInTheDocument()
  })

  it("pages forward and back through the address", async () => {
    server.on("GET", /^\/campaigns\/mundivita\/world\/search\?/, (call) => {
      const cursor = new URLSearchParams(call.path.split("?")[1]).get("cursor")
      return cursor === null
        ? { body: { items: [ALL[0]], next_cursor: "c2" } }
        : { body: { items: [ALL[1]], next_cursor: null } }
    })
    const app = openApp("/app/mundivita/characters/all", ["canon.edit"], NO_PERSPECTIVE)
    await screen.findByRole("link", { name: "Mira, NPC" })
    fireEvent.click(screen.getByRole("button", { name: "Next page" }))
    await screen.findByRole("link", { name: "Aldric, Player character" })
    expect(app.router.state.location.search).toBe("?cursor=c2")
    expect(screen.getByText("Page 2")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Previous page" }))
    await screen.findByRole("link", { name: "Mira, NPC" })
    expect(app.router.state.location.search).toBe("")
  })

  it("offers the drafts toggle to editors only, and only editors request hidden records", async () => {
    openApp("/app/mundivita/characters/all", ["canon.edit"], NO_PERSPECTIVE)
    const toggle = await screen.findByRole("checkbox", { name: "Show drafts and archived" })
    expect(lastSearch().has("include_noncanon")).toBe(false)
    fireEvent.click(toggle)
    await waitFor(() => expect(lastSearch().get("include_noncanon")).toBe("true"))
  })

  it("labels a draft in text and gives a player no toggle and no hidden request", async () => {
    server.on("GET", /^\/campaigns\/mundivita\/world\/search\?/, {
      body: { items: [card("npc-1", "Mira", "npc", { canon_status: "draft" })], next_cursor: null },
    })
    openApp("/app/mundivita/characters/all?hidden=1", ["campaign.view"], NO_PERSPECTIVE)
    await screen.findByRole("link", { name: "Mira, NPC, draft" })
    expect(screen.queryByRole("checkbox", { name: "Show drafts and archived" })).toBeNull()
    expect(lastSearch().has("include_noncanon")).toBe(false)
  })

  it("opens a character without changing the selected perspective, and returns with the filters", async () => {
    const app = openApp("/app/mundivita/characters/all?type=npc", ["canon.edit"])
    fireEvent.click(await screen.findByRole("link", { name: "Mira, NPC" }))
    expect(await screen.findByRole("heading", { level: 1, name: "Mira" })).toBeInTheDocument()
    expect(app.router.state.location.pathname).toBe("/app/mundivita/characters/npc-1")
    // The perspective selector still names the same character it did before.
    const selector = screen.getByRole("combobox", { name: "Character perspective" })
    expect(selector).toHaveValue("character-ixamarra")

    fireEvent.click(screen.getByRole("link", { name: "Back to characters" }))
    await screen.findByRole("link", { name: "Mira, NPC" })
    expect(app.router.state.location.search).toBe("?type=npc")
    expect(screen.getByRole("combobox", { name: "Character perspective" })).toHaveValue("character-ixamarra")
  })
})

describe("Characters page with a selected perspective", () => {
  it("keeps the selected sheet as the default, with the browser one link away", async () => {
    openApp("/app/mundivita/characters", ["canon.edit"])
    expect(await screen.findByRole("heading", { level: 1, name: "Ixamarra" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "All characters" })).toHaveAttribute(
      "href",
      "/app/mundivita/characters/all",
    )
    expect(searchCalls()).toHaveLength(0)
  })
})

describe("Character sheet by address", () => {
  it("shows an NPC's sheet to an editor with the NPC controls linked, not embedded", async () => {
    openApp("/app/mundivita/characters/npc-1", ["canon.edit"], NO_PERSPECTIVE)
    const header = await screen.findByRole("banner", { name: "Mira" })
    expect(within(header).getByText("NPC")).toBeInTheDocument()
    const manage = await screen.findByRole("navigation", { name: "Manage character" })
    expect(within(manage).getByRole("link", { name: "Open in World" })).toHaveAttribute(
      "href",
      "/app/mundivita/world/character/npc-1",
    )
    expect(within(manage).getByRole("link", { name: "Edit" })).toHaveAttribute(
      "href",
      "/app/mundivita/characters/npc-1/edit",
    )
    expect(await within(manage).findByRole("link", { name: "Builds and starting state" })).toHaveAttribute(
      "href",
      "/app/mundivita/characters/npc-1/builds",
    )
    expect(within(manage).getByRole("link", { name: "Run this NPC" })).toHaveAttribute(
      "href",
      "/app/mundivita/world/character/npc-1?section=run",
    )
    expect(await within(manage).findByRole("link", { name: "How this NPC is played" })).toHaveAttribute(
      "href",
      "/app/mundivita/characters/npc-1/portrayal",
    )
    // Nothing is changed from the sheet itself, and no runtime control is embedded.
    expect(screen.queryByRole("button", { name: /Apply|Move|Save/ })).toBeNull()
    expect(server.calls.some((c) => c.method !== "GET")).toBe(false)
  })

  it("offers a player character neither Run this NPC nor the portrayal link", async () => {
    openApp("/app/mundivita/characters/pc-1", ["canon.edit"], NO_PERSPECTIVE)
    const header = await screen.findByRole("banner", { name: "Aldric" })
    expect(within(header).getByText("Player character")).toBeInTheDocument()
    const manage = await screen.findByRole("navigation", { name: "Manage character" })
    await within(manage).findByRole("link", { name: "Builds and starting state" })
    expect(within(manage).queryByRole("link", { name: "Run this NPC" })).toBeNull()
    expect(within(manage).queryByRole("link", { name: "How this NPC is played" })).toBeNull()
  })

  it("gives a player the sheet with no Manage row and sends no authoring request", async () => {
    openApp("/app/mundivita/characters/pc-1", ["campaign.view"], NO_PERSPECTIVE)
    await screen.findByRole("banner", { name: "Aldric" })
    expect(screen.queryByRole("navigation", { name: "Manage character" })).toBeNull()
    expect(server.calls.some((c) => c.path.includes("/authoring/"))).toBe(false)
  })

  it("shows the summary panels and a note, with no retry, when the full sheet is refused", async () => {
    server.on("GET", "/campaigns/mundivita/characters/pc-1", {
      body: character("pc-1", "Aldric", "player_character", false),
    })
    server.on("GET", "/campaigns/mundivita/characters/pc-1/sheet", NOT_FOUND)
    openApp("/app/mundivita/characters/pc-1", ["campaign.view"], NO_PERSPECTIVE)
    expect(await screen.findByRole("heading", { level: 1, name: "Aldric" })).toBeInTheDocument()
    expect(screen.getByText("The full sheet is not available to you.")).toBeInTheDocument()
    expect(screen.getByText("Player character")).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Overview" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull()
  })

  it("shows the unavailable placeholder without confirming existence when the character is a 404", async () => {
    server.on("GET", "/campaigns/mundivita/characters/ghost", NOT_FOUND)
    openApp("/app/mundivita/characters/ghost", ["campaign.view"], NO_PERSPECTIVE)
    expect(await screen.findByRole("heading", { name: "Character unavailable" })).toBeInTheDocument()
    expect(server.calls.some((c) => c.path === "/campaigns/mundivita/characters/ghost/sheet")).toBe(false)
  })

  it("keeps the retry for a server error on the sheet", async () => {
    server.on("GET", "/campaigns/mundivita/characters/pc-1/sheet", { status: 500, body: {} })
    openApp("/app/mundivita/characters/pc-1", ["campaign.view"], NO_PERSPECTIVE)
    expect(await screen.findByRole("button", { name: "Try again" })).toBeInTheDocument()
  })

  it("falls back to the characters browser for Back when opened by a direct link", async () => {
    openApp("/app/mundivita/characters/pc-1", ["campaign.view"], NO_PERSPECTIVE)
    await screen.findByRole("banner", { name: "Aldric" })
    expect(screen.getByRole("link", { name: "Back to characters" })).toHaveAttribute(
      "href",
      "/app/mundivita/characters/all",
    )
  })

  it("ignores a crafted return address", async () => {
    const app = openApp("/app/mundivita/characters/pc-1", ["campaign.view"], NO_PERSPECTIVE)
    await screen.findByRole("banner", { name: "Aldric" })
    void app.router.navigate("/app/mundivita/characters/pc-1", {
      state: { charactersReturn: "/app/other/characters/all" },
    })
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "Back to characters" })).toHaveAttribute(
        "href",
        "/app/mundivita/characters/all",
      ),
    )
  })
})

describe("Characters route compatibility", () => {
  it.each([
    ["/app/mundivita/characters/new", "New character"],
    ["/app/mundivita/characters/npc/new", "New NPC"],
    ["/app/mundivita/characters/pc/new", "New player character"],
  ])("%s is not captured by the character-id route", async (path, heading) => {
    server.on("GET", "/campaigns/mundivita/authoring/npcs/options", { status: 404, body: {} })
    server.on("GET", "/campaigns/mundivita/authoring/player-characters/options", { status: 404, body: {} })
    openApp(path, ["canon.edit"], NO_PERSPECTIVE)
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument()
    expect(server.calls.some((c) => /^\/campaigns\/mundivita\/characters\/(new|npc|pc)/.test(c.path))).toBe(
      false,
    )
  })

  it("serves /characters/all as the browser, not as a character called all", async () => {
    openApp("/app/mundivita/characters/all", ["canon.edit"], NO_PERSPECTIVE)
    await screen.findByRole("link", { name: "Mira, NPC" })
    expect(server.calls.some((c) => c.path === "/campaigns/mundivita/characters/all")).toBe(false)
  })
})
