import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { characterSheetFixture } from "./fixtures/characterSheet"
import { liveBody, MARKER_FIELDS, NULL_PROFILE, PUBLIC_SECTIONS, publicBody } from "./fixtures/publicCharacter"
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
const crumb = (name: string) =>
    within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByRole("link", { name })

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
        expect(crumb("Characters")).toHaveAttribute("href", "/app/mundivita/characters/all?type=npc")
        // Across to the World details and back to the sheet it is still the same Characters task and list:
        // the World route does not turn it into a World breadcrumb.
        fireEvent.click(sectionLink("Details"))
        await screen.findByRole("heading", { level: 1, name: "Aldric" })
        expect(crumb("Characters")).toHaveAttribute("href", "/app/mundivita/characters/all?type=npc")
        expect(
            within(screen.getByRole("navigation", { name: "Breadcrumb" })).queryByRole("link", { name: "World" }),
        ).toBeNull()
        fireEvent.click(sectionLink("Sheet"))
        await screen.findByRole("heading", { level: 1, name: "Aldric" })
        expect(crumb("Characters")).toHaveAttribute("href", "/app/mundivita/characters/all?type=npc")
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
        is_attuned: true,
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
        expect(screen.getByText(/attuned/)).toBeVisible()
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

// CP-6 follow-up: a player whose only access is a direct `character.view_inventory` grant is refused
// the character read itself, so the direct Inventory address must work from the inventory endpoint
// alone: it never reads the character, sheet, relationships or parties, and fails safely when the
// inventory read is refused (a revoked grant or an explicit deny answers the same 404).
describe("Direct inventory address", () => {
    const INVENTORY_URL = "/app/mundivita/characters/pc-1/inventory"
    const refuseCharacterRead = () => {
        server.on("GET", "/campaigns/mundivita/characters/pc-1", NOT_FOUND)
        server.on("GET", "/campaigns/mundivita/characters/pc-1/sheet", NOT_FOUND)
        server.on("GET", "/campaigns/mundivita/characters/pc-1/relationships", NOT_FOUND)
    }
    const onlyInventoryRead = () => {
        expect(calls("")).toHaveLength(0)
        expect(calls("/sheet")).toHaveLength(0)
        expect(calls("/relationships")).toHaveLength(0)
        expect(calls("/parties")).toHaveLength(0)
        expect(server.calls.some((c) => c.method !== "GET")).toBe(false)
    }

    it("shows the restricted inventory while the character read is refused, without reading the character", async () => {
        refuseCharacterRead()
        server.on("GET", "/campaigns/mundivita/characters/pc-1/inventory", { body: RESTRICTED_INVENTORY })
        openApp(INVENTORY_URL, ["campaign.view"], NO_PERSPECTIVE)
        expect(await screen.findByText(/Longsword/)).toBeVisible()
        expect(screen.getByText(/attuned/)).toBeVisible()
        expect(screen.getAllByRole("heading", { name: "Inventory" })).toHaveLength(1)
        expect(screen.queryByRole("navigation", { name: "Character sections" })).not.toBeInTheDocument()
        onlyInventoryRead()
        expect(calls("/inventory")).toHaveLength(1)
    })

    it("fails safely when the inventory read is refused after a revoke or an explicit deny", async () => {
        refuseCharacterRead()
        server.on("GET", "/campaigns/mundivita/characters/pc-1/inventory", NOT_FOUND)
        openApp(INVENTORY_URL, ["campaign.view"], NO_PERSPECTIVE)
        expect(await screen.findByRole("alert")).toHaveTextContent(/not available|no longer access/)
        expect(screen.queryByText(/Longsword/)).not.toBeInTheDocument()
        onlyInventoryRead()
    })

    it("says so, with a retry that only reads, when the inventory read fails", async () => {
        refuseCharacterRead()
        server.on("GET", "/campaigns/mundivita/characters/pc-1/inventory", { status: 500, body: {} })
        openApp(INVENTORY_URL, ["campaign.view"], NO_PERSPECTIVE)
        fireEvent.click(await screen.findByRole("button", { name: /try again/i }))
        await waitFor(() => expect(calls("/inventory").length).toBeGreaterThan(1))
        onlyInventoryRead()
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

// The public tier (A4 §12): what a revelation confers. Each case asserts the rendered page and the
// request log; "markers" are values in fields the tier must never render.
describe("Character record: public tier", () => {
    const PC = "/campaigns/mundivita/characters/pc-1"
    const ENDPOINTS = ["/sheet", "/builds", "/relationships", "/inventory", "/parties", "/public-profile"]
    const MARKERS = /LIVE-|MARKER|\b777\b|\b888\b/
    const LIVE_ONLY = /Hit points|Conditions|Current state|Not recorded|Additional character details/
    const unavailable = () => screen.findByRole("heading", { name: "Character unavailable" })

    function answer(...bodies: Array<object>) {
        let next = 0
        server.on("GET", PC, () => {
            const item = bodies[Math.min(next++, bodies.length - 1)]
            return "status" in item ? (item as { status: number; body: unknown }) : { body: item }
        })
    }
    const requestedEndpoints = () => ENDPOINTS.filter((suffix) => calls(suffix).length > 0)
    const without = (body: object, key: string) => {
        const copy = { ...body } as Record<string, unknown>
        delete copy[key]
        return copy
    }

    it("renders the released profile on /characters/:id, with Profile and Details, and requests nothing else (A1)", async () => {
        answer(publicBody({ ...MARKER_FIELDS }))
        openApp(SHEET, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        expect(await screen.findByRole("heading", { level: 1, name: "Aldric" })).toBeInTheDocument()
        expect(screen.getByText("Player character")).toBeInTheDocument()
        expect(screen.getByRole("heading", { level: 2, name: "Public profile" })).toBeInTheDocument()
        expect(screen.getByText("A wary river guide.")).toBeInTheDocument()
        expect(screen.getByText("Released Elf")).toBeInTheDocument()
        expect(rowNames()).toEqual(["Details", "Profile"])
        expect(sectionLink("Profile")).toHaveAttribute("aria-current", "page")
        expect(sectionLink("Details")).toHaveAttribute("href", WORLD)
        expect(screen.queryByRole("link", { name: "Sheet" })).toBeNull()
        expect(document.body.textContent).not.toMatch(MARKERS)
        expect(document.body.textContent).not.toMatch(LIVE_ONLY)
        expect(calls("")).toHaveLength(1)
        expect(requestedEndpoints()).toEqual([])
        expect(server.calls.some((c) => c.method !== "GET")).toBe(false)
    })

    it("renders the same content on /world/character/:id for a reader, without a sheet link (A2)", async () => {
        answer(publicBody({ ...MARKER_FIELDS }))
        openApp(WORLD, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        expect(await screen.findByRole("heading", { level: 1, name: "Aldric" })).toBeInTheDocument()
        expect(screen.getByText("Released Medium")).toBeInTheDocument()
        expect(rowNames()).toEqual(["Details"])
        expect(document.body.textContent).not.toMatch(MARKERS)
        expect(requestedEndpoints()).toEqual([])
    })

    it("offers inventory and parties only as the sections grant, and reads them only when chosen (A3)", async () => {
        install()
        answer(publicBody({ sections: { ...PUBLIC_SECTIONS, inventory: true, parties: true } }))
        server.on("GET", `${PC}/parties`, { body: { character_id: "pc-1", parties: [] } })
        openApp(SHEET, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        expect(rowNames()).toEqual(["Details", "Profile", "Inventory", "Parties"])
        expect(requestedEndpoints()).toEqual([])
        fireEvent.click(sectionLink("Inventory"))
        expect(await screen.findByRole("link", { name: "Longsword" })).toBeInTheDocument()
        expect(calls("/inventory")).toHaveLength(1)
        expect(calls("/sheet")).toHaveLength(0)
    })

    it("omits null fields and shows the neutral line when all are null, with no placeholder text (A5)", async () => {
        answer(publicBody({ public_profile: NULL_PROFILE }))
        openApp(SHEET, ["campaign.view"], NO_PERSPECTIVE)
        expect(await screen.findByText("No public details have been shared.")).toBeInTheDocument()
        expect(document.body.textContent).not.toMatch(/not recorded|unknown|withheld|not released/i)
    })

    it("shows the live Overview and the released profile apart at summary, and nothing at all with no release (A6, A7)", async () => {
        answer(liveBody("summary"))
        const first = openApp(WORLD, ["campaign.view"], NO_PERSPECTIVE)
        await screen.findByRole("heading", { name: "Public profile" })
        expect(screen.getByRole("heading", { name: "Overview" })).toBeInTheDocument()
        expect(screen.getByText("LIVE-SPECIES-MARKER")).toBeInTheDocument()
        expect(screen.getByText("Released Elf")).toBeInTheDocument()
        first.unmount()
        answer(liveBody("summary", { public_profile: null, sections: { ...SUMMARY, public_profile: false } }))
        openApp(WORLD, ["campaign.view"], NO_PERSPECTIVE)
        await screen.findByRole("heading", { name: "Overview" })
        expect(screen.queryByRole("heading", { name: "Public profile" })).toBeNull()
        expect(document.body.textContent).not.toMatch(/public profile|withheld|not released|no public details/i)
    })

    it("keeps the sheet and adds the profile to the Details route at full (A8)", async () => {
        answer(liveBody("full", { sections: { ...FULL, public_profile: true } }))
        server.on("GET", `${PC}/sheet`, { body: { ...characterSheetFixture, character_id: "pc-1", name: "Aldric" } })
        const { router } = openApp(SHEET, ["campaign.view"], NO_PERSPECTIVE)
        await ready()
        expect(sectionLink("Sheet")).toHaveAttribute("aria-current", "page")
        expect(await screen.findByRole("heading", { level: 1, name: "Aldric" })).toBeInTheDocument()
        expect(screen.queryByRole("heading", { name: "Public profile" })).toBeNull()
        await act(async () => {
            await router.navigate(WORLD)
        })
        expect(await screen.findByRole("heading", { name: "Public profile" })).toBeInTheDocument()
        expect(screen.getByRole("heading", { name: "Current state" })).toBeInTheDocument()
    })

    it("opens from the Characters list with its URL state, and Back returns there (A9)", async () => {
        answer(publicBody())
        const list = "/app/mundivita/characters/all?type=player_character"
        const { router } = openApp(list, ["campaign.view"], NO_PERSPECTIVE)
        await act(async () => {
            await router.navigate(SHEET, { state: { charactersReturn: list } })
        })
        await ready()
        expect(await screen.findByRole("heading", { name: "Public profile" })).toBeInTheDocument()
        expect(crumb("Characters")).toHaveAttribute("href", list)
        await act(async () => {
            await router.navigate(-1)
        })
        expect(router.state.location.pathname + router.state.location.search).toBe(list)
    })

    it("leaves no full-tier content after a later public answer (A10)", async () => {
        answer(liveBody("full", { sections: { ...FULL, public_profile: true } }), publicBody())
        server.on("GET", `${PC}/sheet`, { body: { ...characterSheetFixture, character_id: "pc-1", name: "Aldric" } })
        const { router } = openApp(WORLD, ["campaign.view"], NO_PERSPECTIVE)
        expect(await screen.findByText("MARKER-CONDITION")).toBeInTheDocument()
        await act(async () => {
            await router.navigate("/app/mundivita/characters/all")
        })
        await act(async () => {
            await router.navigate(WORLD)
        })
        await waitFor(() => expect(screen.queryByText("MARKER-CONDITION")).toBeNull())
        expect(await screen.findByRole("heading", { name: "Public profile" })).toBeInTheDocument()
        expect(document.body.textContent).not.toMatch(/LIVE-|MARKER|Hit points|Conditions/)
    })

    it.each([
        ["404", NOT_FOUND],
        ["403", FORBIDDEN],
    ])("replaces the released text with the one unavailable page for %s and drops the breadcrumb name (A11)", async (_s, refusal) => {
        answer(publicBody(), refusal)
        const { router } = openApp(WORLD, ["campaign.view"], NO_PERSPECTIVE)
        await screen.findByText("A wary river guide.")
        await act(async () => {
            await router.navigate("/app/mundivita/characters/all")
        })
        await act(async () => {
            await router.navigate(WORLD)
        })
        await unavailable()
        expect(screen.queryByText("A wary river guide.")).toBeNull()
        expect(document.body.textContent).not.toMatch(/Aldric|Released/)
    })

    it("renders each answer as its own tier: public to summary, then summary to public (A12)", async () => {
        answer(publicBody(), liveBody("summary"), publicBody())
        const { router } = openApp(WORLD, ["campaign.view"], NO_PERSPECTIVE)
        await screen.findByRole("heading", { name: "Public profile" })
        expect(screen.queryByRole("heading", { name: "Overview" })).toBeNull()
        const reopen = async () => {
            await act(async () => {
                await router.navigate("/app/mundivita/characters/all")
            })
            await act(async () => {
                await router.navigate(WORLD)
            })
        }
        await reopen()
        await screen.findByRole("heading", { name: "Overview" })
        expect(screen.getByText("LIVE-SPECIES-MARKER")).toBeInTheDocument()
        await reopen()
        await waitFor(() => expect(screen.queryByRole("heading", { name: "Overview" })).toBeNull())
        expect(screen.getByRole("heading", { name: "Public profile" })).toBeInTheDocument()
        expect(document.body.textContent).not.toMatch(MARKERS)
    })

    it("shows no character content for a 401 (A14)", async () => {
        answer({ status: 401, body: { error: { code: "unauthenticated", message: "m", correlation_id: "c" } } })
        openApp(SHEET, ["campaign.view"], NO_PERSPECTIVE)
        await waitFor(() => expect(calls("")).toHaveLength(1))
        expect(screen.queryByRole("heading", { name: "Public profile" })).toBeNull()
        expect(document.body.textContent).not.toMatch(/Aldric|Released/)
    })

    it.each([
        ["a 500", { status: 500, body: { error: { code: "server_error", message: "m", correlation_id: "c" } } }],
        ["an unknown tier", publicBody({ view_tier: "everything" })],
        ["a public tier without its profile", without(publicBody(), "public_profile")],
        ["a public-shaped body without a tier", without(publicBody(), "view_tier")],
    ])("shows the retryable error and no character content for %s (A15)", async (_label, body) => {
        answer(body)
        openApp(SHEET, ["campaign.view"], NO_PERSPECTIVE)
        expect(await screen.findByRole("heading", { name: "Character information unavailable" })).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument()
        expect(document.body.textContent).not.toMatch(/Aldric|Released|LIVE-|wary river guide/)
        expect(requestedEndpoints()).toEqual([])
    })

    it("recovers from a refused answer on Try again (A15)", async () => {
        answer(publicBody({ view_tier: "everything" }), publicBody())
        openApp(SHEET, ["campaign.view"], NO_PERSPECTIVE)
        fireEvent.click(await screen.findByRole("button", { name: "Try again" }))
        expect(await screen.findByRole("heading", { name: "Public profile" })).toBeInTheDocument()
        expect(calls("")).toHaveLength(2)
    })

    it("reads a genuine pre-tier body without view_tier as before (D-3)", async () => {
        answer(character(FULL))
        openApp(WORLD, ["campaign.view"], NO_PERSPECTIVE)
        expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument()
        expect(screen.queryByRole("heading", { name: "Public profile" })).toBeNull()
    })
})
