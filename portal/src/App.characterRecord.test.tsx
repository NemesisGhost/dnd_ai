import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { characterSheetFixture } from "./fixtures/characterSheet"
import { CharacterPerspectiveContext } from "./context/CharacterPerspectiveContext"
import { CharacterSheetRoutePage } from "./pages/CharacterSheetRoutePage"
import { bootstrapFor, installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import { renderAuthoringRoutes } from "./test/authoringHarness"
import type { MockServer } from "./test/authoringHarness"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
    recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

// One character, two ways in: Characters (/characters/:id) and World (/world/character/:id). The
// same section row appears on both, offers what the server's `sections` say the caller may open,
// and reading a character never selects it as a perspective.
const NO_PERSPECTIVE = { character_perspectives: [], selected_character_id: null }
const NOT_FOUND = {
    status: 404,
    body: { error: { code: "not_found", message: "m", correlation_id: "c" } },
}
const FORBIDDEN = {
    status: 403,
    body: { error: { code: "forbidden", message: "m", correlation_id: "c" } },
}
const FULL = { details: true, sheet: true, relationships: true, inventory: true, parties: false }
const SUMMARY = { details: true, sheet: false, relationships: true, inventory: false, parties: false }

// `null` leaves `sections` out of the answer, as a server that predates them does.
function character(sections: object | null) {
    return {
        character_id: "pc-1",
        name: "Aldric",
        character_kind: "player_character",
        species_code: "human",
        size_category: "medium",
        current_hit_points: 9,
        maximum_hit_points: 12,
        temporary_hit_points: 0,
        exhaustion_level: 0,
        death_save_successes: 0,
        death_save_failures: 0,
        current_location_id: null,
        active_encounter_id: null,
        conditions: [],
        resources: [],
        ...(sections === null ? {} : { sections }),
    }
}
const INVENTORY = [
    {
        item_instance_id: "i1",
        name: "Longsword",
        display_name: "Longsword",
        quantity: 1,
        condition_percentage: null,
        is_equipped: true,
        is_destroyed: false,
    },
]
const RELATIONSHIPS = { character_id: "pc-1", as_of: null, truncated: false, items: [] }

let server: MockServer

function install(sections: object | null = FULL) {
    server.on("GET", "/campaigns/mundivita/characters/pc-1", { body: character(sections) })
    server.on("GET", "/campaigns/mundivita/characters/pc-1/sheet", {
        body: { ...characterSheetFixture, character_id: "pc-1", name: "Aldric" },
    })
    server.on("GET", "/campaigns/mundivita/characters/pc-1/relationships", { body: RELATIONSHIPS })
    server.on("GET", "/campaigns/mundivita/characters/pc-1/inventory", { body: INVENTORY })
}

beforeEach(() => {
    server = installCampaignShellMocks()
})

afterEach(() => {
    vi.unstubAllGlobals()
})

const SHEET = "/app/mundivita/characters/pc-1"
const WORLD = "/app/mundivita/world/character/pc-1"
const calls = (suffix: string) => server.calls.filter((c) => c.path === `/campaigns/mundivita/characters/pc-1${suffix}`)
const rowLinks = () => within(screen.getByRole("navigation", { name: "Character sections" })).getAllByRole("link")
const rowNames = () => rowLinks().map((link) => link.textContent)
const sectionLink = (name: string) =>
    within(screen.getByRole("navigation", { name: "Character sections" })).getByRole("link", { name })
const ready = () => screen.findByRole("navigation", { name: "Character sections" })

describe("Character record: reached from Characters", () => {
    it("opens on the sheet with the sections the server offered and no manager controls", async () => {
        install()
        openApp(SHEET, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        expect(rowNames()).toEqual(["Details", "Sheet", "Relationships", "Inventory"])
        expect(sectionLink("Sheet")).toHaveAttribute("aria-current", "page")
        expect(sectionLink("Details")).toHaveAttribute("href", WORLD)
        expect(screen.queryByRole("navigation", { name: "Manage character" })).not.toBeInTheDocument()
        expect(await screen.findByRole("heading", { level: 1, name: "Aldric" })).toBeInTheDocument()
        // Only the sheet is read until another section is chosen.
        expect(calls("/inventory")).toHaveLength(0)
        expect(calls("/relationships")).toHaveLength(0)
        expect(server.calls.some((c) => c.method !== "GET")).toBe(false)
    })

    it("reaches the inventory in two clicks, reading it once, and Back and Forward walk the sections", async () => {
        install()
        const { router } = openApp(SHEET, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        fireEvent.click(sectionLink("Inventory"))
        expect(await screen.findByRole("link", { name: "Longsword" })).toHaveAttribute(
            "href",
            "/app/mundivita/world/item/i1",
        )
        expect(sectionLink("Inventory")).toHaveAttribute("aria-current", "page")
        expect(router.state.location.search).toBe("?section=inventory")
        expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
        expect(screen.getAllByRole("heading", { name: "Inventory" })).toHaveLength(1)
        expect(calls("/inventory")).toHaveLength(1)

        await act(async () => {
            await router.navigate(-1)
        })
        expect(await screen.findByRole("heading", { level: 1, name: "Aldric" })).toBeInTheDocument()
        expect(sectionLink("Sheet")).toHaveAttribute("aria-current", "page")
        await act(async () => {
            await router.navigate(1)
        })
        expect(await screen.findByRole("link", { name: "Longsword" })).toBeInTheDocument()
        expect(server.calls.some((c) => c.method !== "GET")).toBe(false)
    })

    it("opens the inventory from a deep link and again after a reload, without reading the sheet", async () => {
        install()
        const first = openApp(`${SHEET}?section=inventory`, ["campaign.view"], NO_PERSPECTIVE)
        expect(await screen.findByRole("link", { name: "Longsword" })).toBeInTheDocument()
        expect(calls("/sheet")).toHaveLength(0)
        expect(calls("/relationships")).toHaveLength(0)
        first.unmount()

        const reloaded = openApp(`${SHEET}?section=inventory`, ["campaign.view"], NO_PERSPECTIVE)
        expect(await screen.findByRole("link", { name: "Longsword" })).toBeInTheDocument()
        expect(sectionLink("Inventory")).toHaveAttribute("aria-current", "page")
        reloaded.unmount()
    })

    it("keeps the Characters list context through every section and back to the list", async () => {
        install()
        const { router } = openApp("/app/mundivita/characters/all?type=npc", ["campaign.view"], NO_PERSPECTIVE)
        await act(async () => {
            await router.navigate(SHEET, { state: { charactersReturn: "/app/mundivita/characters/all?type=npc" } })
        })
        await ready()
        fireEvent.click(sectionLink("Relationships"))
        expect(await screen.findByRole("heading", { name: /^Relationships/ })).toBeInTheDocument()
        fireEvent.click(sectionLink("Inventory"))
        await screen.findByRole("link", { name: "Longsword" })
        expect(screen.getByRole("link", { name: "Back to characters" })).toHaveAttribute(
            "href",
            "/app/mundivita/characters/all?type=npc",
        )
        // Across to the World details and back to the sheet it is still the same list.
        fireEvent.click(sectionLink("Details"))
        await screen.findByRole("link", { name: "Back to World" })
        fireEvent.click(sectionLink("Sheet"))
        expect(await screen.findByRole("link", { name: "Back to characters" })).toHaveAttribute(
            "href",
            "/app/mundivita/characters/all?type=npc",
        )
    })

    it("selects no perspective by being read, and writes nothing", async () => {
        install()
        openApp(SHEET, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        fireEvent.click(sectionLink("Inventory"))
        await screen.findByRole("link", { name: "Longsword" })
        fireEvent.click(sectionLink("Relationships"))
        await screen.findByRole("heading", { name: /^Relationships/ })
        expect(server.calls.filter((c) => c.method !== "GET")).toEqual([])
        expect(server.calls.some((c) => c.path.includes("preferences"))).toBe(false)
        expect(screen.queryByText(/Playing as/)).not.toBeInTheDocument()
    })
})

describe("Character record: reached from World", () => {
    it("shows the same row with Details first and the sheet one link away", async () => {
        install()
        openApp(WORLD, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        expect(rowNames()).toEqual(["Details", "Sheet", "Relationships", "Inventory"])
        expect(sectionLink("Details")).toHaveAttribute("aria-current", "page")
        expect(sectionLink("Sheet")).toHaveAttribute("href", SHEET)
        expect(await screen.findByRole("heading", { level: 1, name: "Aldric" })).toBeInTheDocument()
        expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
        // Nothing but the character is read until a section is chosen (no eager inventory read).
        expect(calls("/inventory")).toHaveLength(0)
        expect(calls("/sheet")).toHaveLength(0)
    })

    it("reaches the inventory and relationships here too, with one heading each", async () => {
        install()
        openApp(WORLD, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        fireEvent.click(sectionLink("Inventory"))
        await screen.findByRole("link", { name: "Longsword" })
        expect(screen.getAllByRole("heading", { name: "Inventory" })).toHaveLength(1)
        fireEvent.click(sectionLink("Relationships"))
        expect(await screen.findByRole("heading", { name: /^Relationships/ })).toBeInTheDocument()
        expect(screen.getAllByRole("heading", { name: /^Relationships/ })).toHaveLength(1)
        expect(screen.queryByRole("heading", { name: "Inventory" })).not.toBeInTheDocument()
    })
})

describe("Character record: what is withheld is absent, not broken", () => {
    it("offers a summary-tier reader the summary, details and relationships, and never reads the sheet or inventory", async () => {
        install(SUMMARY)
        server.on("GET", "/campaigns/mundivita/characters/pc-1/sheet", NOT_FOUND)
        server.on("GET", "/campaigns/mundivita/characters/pc-1/inventory", NOT_FOUND)
        openApp(`${SHEET}?section=inventory`, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        expect(rowNames()).toEqual(["Details", "Summary", "Relationships"])
        // The inventory link in the address is not the caller's: the summary shows instead.
        expect(await screen.findByText("The full sheet is not available to you.")).toBeInTheDocument()
        expect(sectionLink("Summary")).toHaveAttribute("aria-current", "page")
        expect(calls("/sheet")).toHaveLength(0)
        expect(calls("/inventory")).toHaveLength(0)
        // And no full mechanics are shown.
        expect(screen.queryByRole("heading", { name: /Ability scores|Skills|Saving throws/i })).not.toBeInTheDocument()
    })

    it("offers the same reader on World no Sheet link and no Inventory", async () => {
        install(SUMMARY)
        openApp(WORLD, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        expect(rowNames()).toEqual(["Details", "Relationships"])
        expect(calls("/inventory")).toHaveLength(0)
    })

    it("lists Parties only when the server offered them, and reads them only when chosen", async () => {
        install({ ...FULL, parties: true })
        server.on("GET", "/campaigns/mundivita/characters/pc-1/parties", {
            body: { character_id: "pc-1", can_open: false, items: [{ party_id: "p1", name: "The Adventuring Party" }] },
        })
        openApp(SHEET, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        expect(rowNames()).toEqual(["Details", "Sheet", "Relationships", "Inventory", "Parties"])
        expect(calls("/parties")).toHaveLength(0)
        fireEvent.click(sectionLink("Parties"))
        expect(await screen.findByText("The Adventuring Party")).toBeVisible()
        expect(calls("/parties")).toHaveLength(1)
    })
})

// CP-6: a reader holding only `character.view_inventory` is offered the inventory and nothing else
// that is full: the server says so through `sections`, and the row carries no condition.
const INVENTORY_ONLY = { details: true, sheet: false, relationships: true, inventory: true, parties: false }
const RESTRICTED_INVENTORY = [
    {
        item_instance_id: "i1",
        name: "Longsword",
        display_name: "Longsword",
        item_category_code: "weapon",
        rarity: "common",
        quantity: 2,
        is_equipped: true,
        is_destroyed: false,
        ownership: "holder",
        identification_level: "unidentified",
        properties: null,
    },
]

describe("Character record: inventory-only reader", () => {
    const installInventoryOnly = () => {
        install(INVENTORY_ONLY)
        server.on("GET", "/campaigns/mundivita/characters/pc-1/sheet", NOT_FOUND)
        server.on("GET", "/campaigns/mundivita/characters/pc-1/inventory", { body: RESTRICTED_INVENTORY })
    }

    it("reaches the inventory from the row, with no sheet, no controls and no mutation", async () => {
        installInventoryOnly()
        openApp(SHEET, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        expect(rowNames()).toEqual(["Details", "Summary", "Relationships", "Inventory"])
        fireEvent.click(sectionLink("Inventory"))
        expect(await screen.findByText(/Longsword/)).toBeVisible()
        expect(screen.getByText(/×2/)).toBeVisible()
        expect(screen.getByText(/equipped/)).toBeVisible()
        // A row without condition does not render "undefined% condition".
        expect(screen.queryByText(/condition/)).not.toBeInTheDocument()
        expect(screen.queryByRole("navigation", { name: "Manage character" })).not.toBeInTheDocument()
        expect(calls("/sheet")).toHaveLength(0)
        expect(server.calls.some((c) => c.method !== "GET")).toBe(false)
    })

    it("opens the inventory from a deep link and after a reload, never reading the sheet", async () => {
        installInventoryOnly()
        const first = openApp(`${SHEET}?section=inventory`, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        expect(await screen.findByText(/Longsword/)).toBeVisible()
        expect(sectionLink("Inventory")).toHaveAttribute("aria-current", "page")
        first.unmount()
        openApp(`${SHEET}?section=inventory`, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        expect(await screen.findByText(/Longsword/)).toBeVisible()
        expect(calls("/sheet")).toHaveLength(0)
        expect(server.calls.some((c) => c.method !== "GET")).toBe(false)
    })

    it("offers Inventory on World", async () => {
        installInventoryOnly()
        openApp(WORLD, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        expect(rowNames()).toEqual(["Details", "Relationships", "Inventory"])
    })
})

describe("Character record: inventory states stay distinct", () => {
    const open = async () => {
        openApp(`${SHEET}?section=inventory`, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
    }

    it("says an empty inventory is empty", async () => {
        install()
        server.on("GET", "/campaigns/mundivita/characters/pc-1/inventory", { body: [] })
        await open()
        expect(await screen.findByText("Nothing carried.")).toBeInTheDocument()
    })

    it("says a refused read is closed, without a retry that could not help", async () => {
        install()
        server.on("GET", "/campaigns/mundivita/characters/pc-1/inventory", FORBIDDEN)
        await open()
        expect(await screen.findByRole("alert")).toHaveTextContent("You do not have access to the inventory.")
        expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument()
        expect(screen.queryByText("Nothing carried.")).not.toBeInTheDocument()
    })

    it("says a failed read failed, and retrying only reads again", async () => {
        install()
        let failing = true
        server.on("GET", "/campaigns/mundivita/characters/pc-1/inventory", () =>
            failing ? { status: 500, body: { error: { code: "x", message: "m", correlation_id: "c" } } } : { body: INVENTORY },
        )
        await open()
        const retry = await screen.findByRole("button", { name: /try again/i })
        failing = false
        fireEvent.click(retry)
        expect(await screen.findByRole("link", { name: "Longsword" })).toBeInTheDocument()
        await waitFor(() => expect(calls("/inventory")).toHaveLength(2))
        expect(server.calls.some((c) => c.method !== "GET")).toBe(false)
    })
})

describe("Character record: editors keep their authoring controls", () => {
    it("leaves Open in World, Relationships and Edit in the Manage row, and adds only Sheet and Inventory", async () => {
        install()
        server.on("GET", /^\/campaigns\/mundivita\/authoring\/characters\/pc-1\/builds$/, { body: { builds: [] } })
        openApp(SHEET, ["campaign.view", "canon.edit"], NO_PERSPECTIVE)
        await ready()
        expect(rowNames()).toEqual(["Sheet", "Inventory"])
        const manage = screen.getByRole("navigation", { name: "Manage character" })
        expect(within(manage).getByRole("link", { name: "Open in World" })).toBeInTheDocument()
        expect(within(manage).getByRole("link", { name: "Relationships" })).toHaveAttribute(
            "href",
            "/app/mundivita/world/character/pc-1?section=relationships",
        )
        fireEvent.click(sectionLink("Inventory"))
        expect(await screen.findByRole("link", { name: "Longsword" })).toBeInTheDocument()
        expect(calls("/relationships")).toHaveLength(0)
    })
})

describe("Character record: the perspective", () => {
    it("is neither read for its content nor changed by visiting any section", async () => {
        install()
        const selectCharacter = vi.fn()
        const syncCharacterFromUrl = vi.fn()
        const getSelectedCharacterId = vi.fn(() => null)
        renderAuthoringRoutes({
            initialEntry: `${SHEET}?section=inventory`,
            bootstrap: bootstrapFor(["campaign.view"], NO_PERSPECTIVE),
            routes: [
                {
                    path: "/app/:campaignId/characters/:characterId",
                    element: (
                        <CharacterPerspectiveContext.Provider
                            value={{ selectCharacter, syncCharacterFromUrl, getSelectedCharacterId }}
                        >
                            <CharacterSheetRoutePage />
                        </CharacterPerspectiveContext.Provider>
                    ),
                },
            ],
        })
        await screen.findByRole("link", { name: "Longsword" })
        for (const name of ["Relationships", "Sheet", "Inventory"]) {
            fireEvent.click(sectionLink(name))
            await waitFor(() => expect(sectionLink(name)).toHaveAttribute("aria-current", "page"))
        }
        expect(selectCharacter).not.toHaveBeenCalled()
        expect(syncCharacterFromUrl).not.toHaveBeenCalled()
        expect(getSelectedCharacterId).not.toHaveBeenCalled()
    })
})

describe("Character record: an answer without `sections` (a server that predates them)", () => {
    it("keeps the summary and relationships usable, and offers no inventory it was never told it may", async () => {
        install(null)
        server.on("GET", "/campaigns/mundivita/characters/pc-1/sheet", NOT_FOUND)
        server.on("GET", "/campaigns/mundivita/characters/pc-1/inventory", NOT_FOUND)
        openApp(SHEET, ["campaign.view"], NO_PERSPECTIVE)
        // The sheet is tried as it always was and its refusal falls back to the summary panels.
        expect(await screen.findByText("The full sheet is not available to you.")).toBeInTheDocument()
        await ready()
        expect(rowNames()).not.toContain("Inventory")
        expect(rowNames()).not.toContain("Parties")
        expect(rowNames()).toContain("Relationships")
        fireEvent.click(sectionLink("Relationships"))
        expect(await screen.findByRole("heading", { name: /^Relationships/ })).toBeInTheDocument()
        expect(calls("/inventory")).toHaveLength(0)
    })

    it("falls back from a direct ?section=inventory without sending an inventory request", async () => {
        install(null)
        server.on("GET", "/campaigns/mundivita/characters/pc-1/sheet", NOT_FOUND)
        const { router } = openApp(`${SHEET}?section=inventory`, ["campaign.view"], NO_PERSPECTIVE)
        expect(await screen.findByText("The full sheet is not available to you.")).toBeInTheDocument()
        expect(screen.queryByRole("link", { name: "Inventory" })).not.toBeInTheDocument()
        expect(screen.queryByRole("heading", { name: "Inventory" })).not.toBeInTheDocument()
        await waitFor(() => expect(router.state.location.search).toBe("?section=sheet"))
        expect(calls("/inventory")).toHaveLength(0)
    })

    it("offers no inventory on the World reader either, and reads none", async () => {
        install(null)
        openApp(`${WORLD}?section=inventory`, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        expect(rowNames()).not.toContain("Inventory")
        expect(calls("/inventory")).toHaveLength(0)
    })

    it("is not the same as an explicit all-false answer, which also offers and reads nothing but the page", async () => {
        install({ details: false, sheet: false, relationships: false, inventory: false, parties: false })
        openApp(SHEET, ["campaign.view"], NO_PERSPECTIVE)
        expect(await screen.findByText("The full sheet is not available to you.")).toBeInTheDocument()
        await ready()
        // Explicitly nothing: only the page's own Summary entry, and no sheet, relationships or inventory read.
        expect(rowNames()).toEqual(["Summary"])
        expect(calls("/sheet")).toHaveLength(0)
        expect(calls("/relationships")).toHaveLength(0)
        expect(calls("/inventory")).toHaveLength(0)
    })

    it("keeps matching-version full-tier inventory navigation working", async () => {
        install({ ...FULL, inventory: true })
        openApp(SHEET, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        fireEvent.click(sectionLink("Inventory"))
        expect(await screen.findByRole("link", { name: "Longsword" })).toBeInTheDocument()
        expect(calls("/inventory")).toHaveLength(1)
    })
})
