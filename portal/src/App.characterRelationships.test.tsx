import { fireEvent, screen, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { characterSheetFixture } from "./fixtures/characterSheet"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
    recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

// No party or perspective is selected anywhere in these tests: the section must not need one.
const NO_PERSPECTIVE = { character_perspectives: [], selected_character_id: null }
const NOT_FOUND = {
    status: 404,
    body: { error: { code: "not_found", message: "m", correlation_id: "c" } },
}

const character = {
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
    sections: { details: true, sheet: true, relationships: true, inventory: true, parties: false },
}
const RELATIONSHIPS = {
    character_id: "pc-1",
    as_of: null,
    truncated: false,
    items: [
        {
            relationship_id: "r1",
            kind: "family",
            kind_label: "Family",
            relationship_type: "family",
            relationship_type_label: "Family",
            symmetric: false,
            participants: [
                {
                    entity_id: "pc-1",
                    name: "Aldric",
                    entity_type_code: "player_character",
                    category: "character",
                    role: "child",
                    role_label: "Child",
                    is_self: true,
                    can_open: false,
                },
                {
                    entity_id: "npc-1",
                    name: "Mira",
                    entity_type_code: "npc",
                    category: "character",
                    role: "parent",
                    role_label: "Parent",
                    is_self: false,
                    can_open: true,
                },
            ],
            started: null,
            ended_at: null,
            period_status: "undated",
            current_status_label: null,
            details: {},
        },
    ],
}

let server: MockServer

beforeEach(() => {
    server = installCampaignShellMocks()
    server.on("GET", "/campaigns/mundivita/characters/pc-1", { body: character })
    server.on("GET", "/campaigns/mundivita/characters/pc-1/relationships", { body: RELATIONSHIPS })
})

afterEach(() => {
    vi.unstubAllGlobals()
})

const relationshipCalls = () => server.calls.filter((c) => c.path.includes("/relationships"))

describe("Relationships on a character's page", () => {
    it("shows the read-only section as the Relationships section with no party or perspective selected", async () => {
        server.on("GET", "/campaigns/mundivita/characters/pc-1/sheet", {
            body: { ...characterSheetFixture, character_id: "pc-1", name: "Aldric" },
        })
        openApp("/app/mundivita/characters/pc-1?section=relationships", ["campaign.view"], NO_PERSPECTIVE)
        const heading = await screen.findByRole("heading", { name: "Relationships (1)" })
        const section = heading.closest("section")!
        expect(within(section).getByRole("link", { name: "Mira" })).toHaveAttribute(
            "href",
            "/app/mundivita/characters/npc-1",
        )
        expect(relationshipCalls().map((c) => c.path)).toEqual([
            "/campaigns/mundivita/characters/pc-1/relationships",
        ])
        expect(server.calls.some((c) => c.path.includes("/authoring/"))).toBe(false)
        expect(server.calls.some((c) => c.method !== "GET")).toBe(false)
    })

    it("also shows it at the summary tier, where the full sheet is not available", async () => {
        server.on("GET", "/campaigns/mundivita/characters/pc-1", {
            body: {
                ...character,
                sections: { details: true, sheet: false, relationships: true, inventory: false, parties: false },
            },
        })
        server.on("GET", "/campaigns/mundivita/characters/pc-1/sheet", NOT_FOUND)
        openApp("/app/mundivita/characters/pc-1", ["campaign.view"], NO_PERSPECTIVE)
        expect(await screen.findByText("The full sheet is not available to you.")).toBeInTheDocument()
        fireEvent.click(screen.getByRole("link", { name: "Relationships" }))
        expect(await screen.findByRole("heading", { name: "Relationships (1)" })).toBeInTheDocument()
        // The sheet was never asked for: the server did not offer it.
        expect(server.calls.some((c) => c.path.endsWith("/sheet"))).toBe(false)
    })

    it("gives an editor the existing World workspace link and no duplicate panel or request", async () => {
        server.on("GET", "/campaigns/mundivita/characters/pc-1/sheet", {
            body: { ...characterSheetFixture, character_id: "pc-1", name: "Aldric" },
        })
        server.on("GET", /^\/campaigns\/mundivita\/authoring\/characters\/pc-1\/builds$/, {
            body: { builds: [] },
        })
        openApp("/app/mundivita/characters/pc-1", ["campaign.view", "canon.edit"], NO_PERSPECTIVE)
        const link = await screen.findByRole("link", { name: "Relationships" })
        expect(link).toHaveAttribute("href", "/app/mundivita/world/character/pc-1?section=relationships")
        expect(screen.queryByRole("heading", { name: /^Relationships/ })).not.toBeInTheDocument()
        expect(relationshipCalls()).toEqual([])
    })
})
